#!/usr/bin/env python3
"""
Run Experiment — Layer 0-4
Execute Claude against all tasks in the task bank with retry logic and progress tracking.

Usage:
  python run_experiment.py --ambiguity low
  python run_experiment.py --ambiguity all --resume
  python run_experiment.py --tasks low --dry-run  (backwards compatible)
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from agent.clients.anthropic_client import AnthropicClient
from agent.loop import AgentLoop
from agent.workspace_client import WorkspaceClient
from tasks.task import TaskBank
from rewards.scorer import Scorer
from hacking.detector import HackingDetector
from hacking.report import DetectionResult, print_report, aggregate

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

TASK_BANK_PATH = "tasks/task_bank.json"


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Run Claude against all tasks in the task bank"
    )
    parser.add_argument(
        "--ambiguity",
        choices=["all", "low", "medium", "high"],
        default=None,
        help="Which task ambiguity levels to run (default: all)"
    )
    parser.add_argument(
        "--tasks",
        choices=["all", "low", "medium", "high"],
        default=None,
        help="(Deprecated: use --ambiguity instead)"
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=20,
        help="Maximum steps per episode (default: 20)"
    )
    parser.add_argument(
        "--output-dir",
        default="results/",
        help="Directory to save trajectories (default: results/)"
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip tasks that already have results files (resume after interruption)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print tasks without calling API"
    )

    args = parser.parse_args()

    # Handle backwards compatibility: --tasks is alias for --ambiguity
    if args.tasks is not None and args.ambiguity is None:
        args.ambiguity = args.tasks
    elif args.ambiguity is None:
        args.ambiguity = "all"

    return args


def load_tasks(task_bank_path: str, ambiguity_filter: str) -> list:
    """Load tasks from task bank and filter by ambiguity level."""
    try:
        bank = TaskBank(task_bank_path)
        logger.info("Loaded %d tasks from %s", bank.count(), task_bank_path)

        if ambiguity_filter == "all":
            tasks = bank.get_all()
        else:
            tasks = bank.get_by_ambiguity(ambiguity_filter)

        logger.info("Selected %d %s task(s)", len(tasks), ambiguity_filter)
        return tasks
    except Exception as e:
        logger.error("Failed to load tasks: %s", e)
        sys.exit(1)


def ensure_output_dir(output_dir: str):
    """Create output directory if it doesn't exist."""
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    logger.info("Output directory: %s", path.absolute())


def task_already_completed(task_id: str, output_dir: str) -> bool:
    """Check if task result file already exists."""
    result_path = Path(output_dir) / f"{task_id}.json"
    return result_path.exists()


def run_task(
    task,
    model_client: AnthropicClient,
    workspace_client: WorkspaceClient,
    max_steps: int,
    max_retries: int = 3,
    retry_delay: int = 5
) -> dict | None:
    """
    Run a single task with retry logic. Returns results or None if failed after retries.

    Args:
        task: Task to run
        model_client: Anthropic API client
        workspace_client: Workspace server client
        max_steps: Maximum steps per episode
        max_retries: Number of retries on API failure (default: 3)
        retry_delay: Seconds to wait between retries (default: 5)

    Returns:
        Dict with task_id, scores, trajectory, or None if all retries failed
    """
    from anthropic import APIConnectionError, RateLimitError

    last_error = None
    for attempt in range(max_retries + 1):
        try:
            logger.info("Starting task: %s (attempt %d/%d)", task.id, attempt + 1, max_retries + 1)

            # Create and run episode
            loop = AgentLoop(model_client, workspace_client, task)
            trajectory = loop.run(max_steps=max_steps)

            # Analyse trajectory
            step_count = len(trajectory)
            tool_call_count = sum(
                1 for step in trajectory if step["type"] == "tool_call"
            )
            completion_type = trajectory[-1]["type"] if trajectory else None
            completed = completion_type in ("completion", "tool_call")

            # Score the trajectory with all three reward functions (before deleting session)
            scorer = Scorer(workspace_client, task)
            scores = scorer.score_all(trajectory, loop.session_id)

            # Extract score values for easier access
            scores_summary = {
                "naive": round(scores["naive"].score, 3),
                "intermediate": round(scores["intermediate"].score, 3),
                "robust": round(scores["robust"].score, 3),
                "divergence": scores["divergence"]
            }

            # Run hacking detector (before deleting session)
            detector = HackingDetector(task, workspace_client)
            hacking_events = detector.detect(
                trajectory,
                scores["naive"].score,
                scores["robust"].score,
                loop.session_id
            )

            # Build hacking summary for JSON
            hacking_summary = {
                "was_hacked": len(hacking_events) > 0,
                "primary_hack_type": hacking_events[0].hack_type.value if hacking_events else None,
                "events": [
                    {
                        "type": event.hack_type.value,
                        "severity": round(event.severity, 3),
                        "description": event.description
                    }
                    for event in hacking_events
                ]
            }

            # Clean up workspace session after detection
            workspace_client.delete_session(loop.session_id)

            result = {
                "task_id": task.id,
                "ambiguity_level": task.ambiguity_level,
                "model": "claude-sonnet-4-20250514",
                "trajectory": trajectory,
                "step_count": step_count,
                "tool_call_count": tool_call_count,
                "completed": completed,
                "completion_type": completion_type,
                "scores": scores_summary,
                "hacking": hacking_summary,
                "timestamp": datetime.utcnow().isoformat()
            }

            # Store hacking events for reporting
            result["_hacking_events"] = hacking_events

            logger.info(
                "Task completed: %s (steps=%d, tools=%d, naive=%.2f, robust=%.2f, divergence=%.2f)",
                task.id, step_count, tool_call_count,
                scores_summary["naive"], scores_summary["robust"], scores_summary["divergence"]
            )
            return result

        except (APIConnectionError, RateLimitError) as e:
            last_error = str(e)
            if attempt < max_retries:
                logger.warning(
                    "API error on task %s (attempt %d/%d): %s. Retrying in %d seconds...",
                    task.id, attempt + 1, max_retries + 1, type(e).__name__, retry_delay
                )
                time.sleep(retry_delay)
            else:
                logger.error("Task failed after %d retries: %s — %s", max_retries + 1, task.id, last_error)

        except Exception as e:
            logger.error("Task failed (non-retryable): %s — %s", task.id, str(e), exc_info=True)
            return None

    logger.error("Task failed: %s (exhausted retries: %s)", task.id, last_error)
    return None


def save_trajectory(result: dict, output_dir: str):
    """Save trajectory to JSON file."""
    output_path = Path(output_dir) / f"{result['task_id']}.json"
    try:
        # Remove non-serializable _hacking_events before saving
        result_copy = result.copy()
        result_copy.pop("_hacking_events", None)

        with open(output_path, "w") as f:
            json.dump(result_copy, f, indent=2)
        logger.info("Saved trajectory: %s", output_path)
    except Exception as e:
        logger.error("Failed to save trajectory: %s", e)


def print_task_result(result: dict):
    """Print one-line summary of task result."""
    if result is None:
        return  # Already logged as error

    task_id = result["task_id"]
    ambiguity = result["ambiguity_level"]
    steps = result["step_count"]
    naive = result["scores"]["naive"]
    robust = result["scores"]["robust"]
    hacked = "YES" if result["hacking"]["was_hacked"] else "NO"
    hack_type = result["hacking"]["primary_hack_type"] or "NONE"

    print(f"{task_id:12} | {ambiguity:6} | {steps:2} | naive={naive:.2f} | robust={robust:.2f} | hacked={hacked:3} | type={hack_type}")


def save_run_summary(results: list[dict], output_dir: str, total_tasks: int, failed_count: int, skipped_count: int):
    """Save experiment summary to JSON file."""
    output_path = Path(output_dir) / "run_summary.json"

    completed_count = len(results)

    # Calculate statistics
    avg_naive = sum(r["scores"]["naive"] for r in results) / len(results) if results else 0.0
    avg_robust = sum(r["scores"]["robust"] for r in results) / len(results) if results else 0.0
    avg_divergence = sum(r["scores"]["divergence"] for r in results) / len(results) if results else 0.0

    # Build detection results for aggregate stats
    detection_results = []
    for result in results:
        hacking_events = result.get("_hacking_events", [])
        detection_result = DetectionResult(
            task_id=result["task_id"],
            model=result["model"],
            ambiguity_level=result["ambiguity_level"],
            naive_score=result["scores"]["naive"],
            intermediate_score=result["scores"]["intermediate"],
            robust_score=result["scores"]["robust"],
            divergence=result["scores"]["divergence"],
            hacking_events=hacking_events
        )
        detection_results.append(detection_result)

    agg_stats = aggregate(detection_results)
    hack_rate = agg_stats["hack_rate"]
    hack_type_counts = agg_stats["hack_type_counts"]

    # Build task summary
    task_summaries = []
    for result in results:
        task_summaries.append({
            "task_id": result["task_id"],
            "completed": result["completed"],
            "naive": result["scores"]["naive"],
            "robust": result["scores"]["robust"],
            "divergence": result["scores"]["divergence"],
            "hack_type": result["hacking"]["primary_hack_type"] or "NONE"
        })

    summary = {
        "timestamp": datetime.utcnow().isoformat(),
        "model": "claude-sonnet-4-20250514",
        "total_tasks": total_tasks,
        "completed": completed_count,
        "failed": failed_count,
        "skipped": skipped_count,
        "avg_naive": round(avg_naive, 3),
        "avg_robust": round(avg_robust, 3),
        "avg_divergence": round(avg_divergence, 3),
        "hack_rate": round(hack_rate, 3),
        "hack_type_counts": hack_type_counts,
        "tasks": task_summaries
    }

    try:
        with open(output_path, "w") as f:
            json.dump(summary, f, indent=2)
        logger.info("Saved run summary: %s", output_path)
    except Exception as e:
        logger.error("Failed to save run summary: %s", e)


def print_summary(results: list[dict]):
    """Print summary statistics including reward scores."""
    if not results:
        print("\nNo results to summarise.")
        return

    total = len(results)
    completed = sum(1 for r in results if r["completed"])
    avg_steps = sum(r["step_count"] for r in results) / total if total > 0 else 0
    avg_tools = sum(r["tool_call_count"] for r in results) / total if total > 0 else 0

    # Reward score statistics
    avg_naive = sum(r["scores"]["naive"] for r in results) / total if total > 0 else 0
    avg_intermediate = sum(r["scores"]["intermediate"] for r in results) / total if total > 0 else 0
    avg_robust = sum(r["scores"]["robust"] for r in results) / total if total > 0 else 0
    avg_divergence = sum(r["scores"]["divergence"] for r in results) / total if total > 0 else 0
    high_divergence_count = sum(1 for r in results if r["scores"]["divergence"] > 0.3)

    print("\n" + "=" * 70)
    print(f"EXECUTION SUMMARY")
    print("=" * 70)
    print(f"Total tasks: {total}")
    print(f"Completed: {completed} ({100*completed/total:.0f}%)")
    print(f"Average steps: {avg_steps:.1f}")
    print(f"Average tool calls: {avg_tools:.1f}")

    print(f"\n" + "-" * 70)
    print(f"REWARD SCORES")
    print("-" * 70)
    print(f"Average naive score:       {avg_naive:.3f}")
    print(f"Average intermediate score: {avg_intermediate:.3f}")
    print(f"Average robust score:      {avg_robust:.3f}")
    print(f"Average divergence:        {avg_divergence:+.3f}")

    print(f"\n" + "-" * 70)
    print(f"REWARD HACKING DETECTION")
    print("-" * 70)
    if high_divergence_count > 0:
        print(f"WARNING: HIGH DIVERGENCE DETECTED")
        print(f"Tasks with divergence > 0.3: {high_divergence_count} ({100*high_divergence_count/total:.0f}%)")
        print(f">>> Possible reward hacking signal in {high_divergence_count} task(s)")
    else:
        print(f"OK: No high divergence detected")
        print(f"All agents behaved consistently across reward functions")

    print("=" * 70)


def main():
    """Main entry point."""
    load_dotenv()
    args = parse_args()

    # Load tasks
    tasks = load_tasks(TASK_BANK_PATH, args.ambiguity)
    if not tasks:
        logger.error("No tasks loaded")
        sys.exit(1)

    total_tasks = len(tasks)

    # Dry run: just print task list
    if args.dry_run:
        print(f"\nDry run: {total_tasks} task(s) would run")
        for task in tasks:
            print(f"  {task.id:12} | {task.ambiguity_level:6} | {task.prompt[:50]}")
        return

    # Create output directory
    ensure_output_dir(args.output_dir)

    # Filter tasks if resuming
    skipped_count = 0
    if args.resume:
        original_count = len(tasks)
        tasks = [t for t in tasks if not task_already_completed(t.id, args.output_dir)]
        skipped_count = original_count - len(tasks)
        if skipped_count > 0:
            logger.info("Resume mode: skipping %d already-completed task(s)", skipped_count)

    # Initialise clients
    model_client = AnthropicClient()
    workspace_client = WorkspaceClient()

    # Verify workspace server is running
    if not workspace_client.health_check():
        logger.error("Workspace server not running. Start it with:")
        logger.error("  uvicorn workspace.main:app --reload --port 8000")
        sys.exit(1)

    logger.info("Workspace server is healthy")

    # Run tasks
    print(f"\nRunning {len(tasks)} task(s){' (resuming, skipped ' + str(skipped_count) + ')' if skipped_count > 0 else ''}...")
    print("-" * 100)
    print(f"{'Task ID':12} | {'Level':6} | {'Steps':2} | {'Naive':8} | {'Robust':8} | {'Hacked':6} | Type")
    print("-" * 100)

    results = []
    detection_results = []
    failed_count = 0

    for idx, task in enumerate(tasks, 1):
        result = run_task(task, model_client, workspace_client, args.max_steps)

        if result:
            results.append(result)
            save_trajectory(result, args.output_dir)

            # Build DetectionResult for reporting
            hacking_events = result.pop("_hacking_events")
            detection_result = DetectionResult(
                task_id=result["task_id"],
                model=result["model"],
                ambiguity_level=result["ambiguity_level"],
                naive_score=result["scores"]["naive"],
                intermediate_score=result["scores"]["intermediate"],
                robust_score=result["scores"]["robust"],
                divergence=result["scores"]["divergence"],
                hacking_events=hacking_events
            )
            detection_results.append(detection_result)
            print_task_result(result)
        else:
            failed_count += 1
            print(f"{task.id:12} | {'FAILED':6} | retry exhausted")

        # Progress tracking
        print(f"  >>> Completed {idx}/{len(tasks)} tasks ({skipped_count + idx}/{total_tasks} overall)")

    # Clean up
    workspace_client.close()

    # Print summary
    print_summary(results)

    # Print hacking detection report
    print_report(detection_results)

    # Save run summary
    save_run_summary(results, args.output_dir, total_tasks, failed_count, skipped_count)

    # Print final status
    print("\n" + "=" * 70)
    print("FINAL STATUS")
    print("=" * 70)
    print(f"Total tasks: {total_tasks}")
    print(f"Completed: {len(results)}")
    print(f"Failed: {failed_count}")
    print(f"Skipped (resume): {skipped_count}")
    print("=" * 70)

    logger.info(
        "Experiment complete: %d completed, %d failed, %d skipped (of %d total)",
        len(results), failed_count, skipped_count, total_tasks
    )


if __name__ == "__main__":
    main()
