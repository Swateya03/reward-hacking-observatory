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
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from agent.clients.anthropic_client import AnthropicClient
from agent.loop import AgentLoop
from agent.workspace_client import WorkspaceClient
from tasks.task import TaskBank
from rewards.scorer import Scorer
from hacking.detector import HackingDetector
from hacking.report import DetectionResult, print_report, aggregate
from config import MAX_STEPS, MAX_TOKENS, MODEL, TEMPERATURE
from agent.cost import BudgetExceeded
from hacking.unsafe_action import unsafe_action_under_ambiguity
from hacking.detector import check_availability, CHECKS
from rewards.outcome import robust_outcome_available

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

TASK_BANK_PATH = "tasks/task_bank.json"
RESULT_SCHEMA_VERSION = 6   # v6: metadata.thinking (the setting sent; null if none); v5: metadata.max_tokens; v4: hacking.checks (per-check available/fired); v3: robust_outcome null when N/A; policy_metrics


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
        default=MAX_STEPS,
        help=f"Maximum steps per episode (default from config.py: {MAX_STEPS})"
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
        "--run-index",
        type=int,
        default=None,
        help="Run number k (1-based). Writes to results/runs/<model>/run_0k/ unless --output-dir is "
             "given, and applies config.RUN_BUDGET_USD to this run's spend."
    )
    parser.add_argument(
        "--task-ids",
        default=None,
        help="Comma-separated task ids to run, e.g. task_001,task_021 (applied after --ambiguity)"
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


def fmt(value, signed: bool = False) -> str:
    """Format a score for printing; N/A for None."""
    if value is None:
        return "N/A"
    return f"{value:+.2f}" if signed else f"{value:.2f}"


def mean_available(values: list) -> float:
    """Mean of the non-None values; 0.0 if none are available."""
    present = [v for v in values if v is not None]
    return sum(present) / len(present) if present else 0.0


def summarise_scores(scores: dict, task=None) -> dict:
    """Flatten the Scorer output into the plain numbers stored in a result file.

    robust_outcome and divergence are null (N/A) when the task has no
    expected_state, because there is no outcome to check. They are never
    filled with a constant. Without a task, both are treated as available.
    """
    available = True if task is None else robust_outcome_available(task)
    return {
        "naive": round(scores["naive"].score, 3),
        "intermediate": round(scores["intermediate"].score, 3),
        "robust_outcome": round(scores["robust"].score, 3) if available else None,
        "divergence": scores["divergence"] if available else None,
        "robust_outcome_available": available,
    }


def summarise_hacking(hacking_events: list, robust_available: bool = True) -> dict:
    """Detector output in the shape stored in a result file.

    was_hacked is the hack label: true when any available check fired.
    checks records, per check, whether it could run (available) and whether it
    fired (fired is null when not available). primary_hack_type is the first
    event in detector order (not highest severity).
    """
    fired_types = {event.hack_type.value for event in hacking_events}
    availability = check_availability(robust_available)
    return {
        "was_hacked": len(hacking_events) > 0,
        "checks": {
            name: {
                "available": availability[name],
                "fired": (name in fired_types) if availability[name] else None,
            }
            for name in CHECKS
        },
        "primary_hack_type": hacking_events[0].hack_type.value if hacking_events else None,
        "events": [
            {
                "type": event.hack_type.value,
                "severity": round(event.severity, 3),
                "description": event.description,
            }
            for event in hacking_events
        ],
    }


def build_result(
    task,
    trajectory: list,
    scores: dict,
    hacking_events: list,
    *,
    model: str,
    temperature: float,
    max_steps: int,
    max_tokens: int = MAX_TOKENS,
    thinking: dict | None = None,
) -> dict:
    """Build the JSON record written to results/<task_id>.json.

    This is the only writer of per-task results. findings.py reads this shape.
    The metadata block records the settings the episode was run with.
    """
    completion_type = trajectory[-1]["type"] if trajectory else None
    # The loop only stops early on completion or clarification; anything else ran out of steps.
    stopped_reason = completion_type if completion_type in ("completion", "clarification") else "step_limit"
    return {
        "task_id": task.id,
        "ambiguity_level": task.ambiguity_level,
        "model": model,
        "trajectory": trajectory,
        "step_count": len(trajectory),
        "tool_call_count": sum(1 for step in trajectory if step["type"] == "tool_call"),
        "completed": completion_type in ("completion", "tool_call"),
        "completion_type": completion_type,
        "stopped_reason": stopped_reason,
        "scores": summarise_scores(scores, task),
        "hacking": summarise_hacking(hacking_events, robust_available=robust_outcome_available(task)),
        "policy_metrics": {
            "unsafe_action_under_ambiguity": unsafe_action_under_ambiguity(trajectory, task.ambiguity_level),
        },
        "metadata": {
            "schema_version": RESULT_SCHEMA_VERSION,
            "model": model,
            "temperature": temperature,
            "max_steps": max_steps,
            "max_tokens": max_tokens,
            "thinking": thinking,
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


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

            # Label this episode's cost-log entries with the task id
            model_client.set_task(task.id)

            # Create and run episode
            loop = AgentLoop(model_client, workspace_client, task)
            trajectory = loop.run(max_steps=max_steps)

            # Score the trajectory with all three reward functions (before deleting session)
            scorer = Scorer(workspace_client, task)
            scores = scorer.score_all(trajectory, loop.session_id)

            # Run hacking detector (before deleting session)
            detector = HackingDetector(task, workspace_client)
            # The detector gets no robust score for N/A tasks, so METRIC_GAMING cannot fire.
            detector_robust = scores["robust"].score if robust_outcome_available(task) else None
            hacking_events = detector.detect(
                trajectory,
                scores["naive"].score,
                detector_robust,
                loop.session_id
            )

            # Clean up workspace session after detection
            workspace_client.delete_session(loop.session_id)

            result = build_result(
                task, trajectory, scores, hacking_events,
                model=model_client.model,
                temperature=model_client.temperature,
                max_steps=max_steps,
                max_tokens=model_client.max_tokens,
                thinking=model_client.thinking,
            )

            # Store hacking events for reporting
            result["_hacking_events"] = hacking_events

            logger.info(
                "Task completed: %s (steps=%d, tools=%d, naive=%.2f, robust_outcome=%s, divergence=%s)",
                task.id, result["step_count"], result["tool_call_count"],
                result["scores"]["naive"], fmt(result["scores"]["robust_outcome"]), fmt(result["scores"]["divergence"], signed=True)
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

        except BudgetExceeded:
            # Not a task failure: the run must stop. main() handles it.
            raise

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
    robust = result["scores"]["robust_outcome"]
    hacked = "YES" if result["hacking"]["was_hacked"] else "NO"
    hack_type = result["hacking"]["primary_hack_type"] or "NONE"

    print(f"{task_id:12} | {ambiguity:6} | {steps:2} | naive={naive:.2f} | robust={fmt(robust)} | hacked={hacked:3} | type={hack_type}")


def save_run_summary(results: list[dict], output_dir: str, total_tasks: int, failed_count: int, skipped_count: int, run_config: dict):
    """Save experiment summary to JSON file."""
    output_path = Path(output_dir) / "run_summary.json"

    completed_count = len(results)

    # Calculate statistics
    avg_naive = sum(r["scores"]["naive"] for r in results) / len(results) if results else 0.0
    avg_robust = mean_available([r["scores"]["robust_outcome"] for r in results])
    avg_divergence = mean_available([r["scores"]["divergence"] for r in results])

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
            robust_score=result["scores"]["robust_outcome"],
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
            "robust_outcome": result["scores"]["robust_outcome"],
            "divergence": result["scores"]["divergence"],
            "hack_type": result["hacking"]["primary_hack_type"] or "NONE"
        })

    summary = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": run_config["model"],
        "metadata": run_config,
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
    avg_robust = mean_available([r["scores"]["robust_outcome"] for r in results])
    avg_divergence = mean_available([r["scores"]["divergence"] for r in results])
    high_divergence_count = sum(1 for r in results if r["scores"]["divergence"] is not None and r["scores"]["divergence"] > 0.3)
    robust_na_count = sum(1 for r in results if not r["scores"]["robust_outcome_available"])

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
    print(f"Average robust outcome:    {avg_robust:.3f}  ({total - robust_na_count} of {total} tasks; {robust_na_count} N/A, excluded)")
    print(f"Average divergence:        {avg_divergence:+.3f}  (same tasks)")

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

    if args.task_ids:
        wanted = [t.strip() for t in args.task_ids.split(",") if t.strip()]
        known = {t.id for t in tasks}
        missing = [t for t in wanted if t not in known]
        if missing:
            logger.error("Unknown or filtered-out task ids: %s", ", ".join(missing))
            sys.exit(1)
        tasks = [t for t in tasks if t.id in set(wanted)]

    total_tasks = len(tasks)

    # Dry run: just print task list
    if args.dry_run:
        print(f"\nDry run: {total_tasks} task(s) would run")
        for task in tasks:
            print(f"  {task.id:12} | {task.ambiguity_level:6} | {task.prompt[:50]}")
        return

    # A numbered run gets its own directory, unless the output directory was set explicitly
    run_id = None
    if args.run_index is not None:
        run_id = f"run_{args.run_index:02d}"
        if args.output_dir == "results/":
            args.output_dir = str(Path("results") / "runs" / MODEL / run_id)

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
    if run_id is not None:
        model_client.set_run(run_id)
    workspace_client = WorkspaceClient()
    run_config = {
        "model": model_client.model,
        "temperature": model_client.temperature,
        "max_steps": args.max_steps,
    }

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

    budget_stop = None
    for idx, task in enumerate(tasks, 1):
        try:
            result = run_task(task, model_client, workspace_client, args.max_steps)
        except BudgetExceeded as e:
            budget_stop = e
            print(f"\nBUDGET GUARD ({e.scope} cap): stopped before {e.task_id or task.id}, step {e.step}. "
                  f"Spent so far ${e.running_total:.4f}; next call could cost up to ${e.worst_case:.4f}; "
                  f"cap ${e.budget:.2f}. Completed episodes are saved in {args.output_dir}. "
                  f"Re-run with --resume to continue.")
            break

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
                robust_score=result["scores"]["robust_outcome"],
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
    save_run_summary(results, args.output_dir, total_tasks, failed_count, skipped_count, run_config)

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

    run_state_path = Path(args.output_dir) / "run_state.json"
    if budget_stop is not None:
        state = {
            "status": "stopped_by_budget",
            "task_id": budget_stop.task_id,
            "step": budget_stop.step,
            "running_total_usd": round(budget_stop.running_total, 6),
            "worst_case_next_call_usd": round(budget_stop.worst_case, 6),
            "budget_usd": budget_stop.budget,
            "completed_this_invocation": len(results),
            "failed_this_invocation": failed_count,
            "resume": "re-run the same command with --resume and the same --output-dir",
        }
        Path(args.output_dir).mkdir(parents=True, exist_ok=True)
        run_state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        print(f"Run state saved to {run_state_path}. Re-run with --resume to continue.")
        sys.exit(3)
    if run_state_path.exists():
        run_state_path.unlink()  # a finished run leaves no stale stop record


if __name__ == "__main__":
    main()
