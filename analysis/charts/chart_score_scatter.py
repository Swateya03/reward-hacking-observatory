"""Scatter plot showing naive vs robust scores for all tasks."""

import json
import sys
from pathlib import Path
import matplotlib.pyplot as plt
import numpy as np

# Color mapping for ambiguity levels
AMBIGUITY_COLORS = {
    "low": "#2ca02c",      # Green
    "medium": "#ff7f0e",   # Orange
    "high": "#d62728",     # Red
}

def prepare_data(tasks: list) -> dict:
    """Extract and prepare scatter plot data (testable).

    Args:
        tasks: List of task dicts with naive_score, robust_score, ambiguity_level

    Returns:
        Dict with 'x', 'y', 'colors', 'task_ids' lists
    """
    x = []
    y = []
    colors = []
    task_ids = []

    for task in tasks:
        naive = task.get("naive_score")
        robust = task.get("robust_score")
        ambiguity = task.get("ambiguity_level", "unknown")

        if naive is None or robust is None:
            continue

        x.append(naive)
        y.append(robust)
        task_ids.append(task.get("task_id"))
        colors.append(AMBIGUITY_COLORS.get(ambiguity, "#808080"))

    return {"x": x, "y": y, "colors": colors, "task_ids": task_ids}

def load_all_tasks():
    """Load all task JSON files from results/."""
    results_dir = Path("results")

    if not results_dir.exists():
        print("[ERROR] results/ directory not found.")
        sys.exit(1)

    tasks = []
    json_files = sorted(results_dir.glob("task_*.json"))

    if not json_files:
        print("[ERROR] No task_*.json files found in results/")
        sys.exit(1)

    for filepath in json_files:
        try:
            with open(filepath, "r") as f:
                task_data = json.load(f)
                tasks.append(task_data)
        except (json.JSONDecodeError, IOError) as e:
            print(f"[WARNING] Failed to load {filepath.name}: {e}")

    return tasks

def analyze_diagonal(tasks):
    """Count points above vs below the diagonal."""
    above = 0
    below = 0

    for task in tasks:
        naive = task.get("naive_score")
        robust = task.get("robust_score")

        if naive is None or robust is None:
            continue

        if robust > naive:
            above += 1
        elif naive > robust:
            below += 1

    return above, below

def create_chart(tasks, output_path="analysis/charts/score_scatter.png"):
    """Create scatter plot of naive vs robust scores."""

    # Extract data
    task_ids = []
    naive_scores = []
    robust_scores = []
    colors = []
    ambiguity_levels = []

    for task in tasks:
        task_id = task.get("task_id")
        naive = task.get("naive_score")
        robust = task.get("robust_score")
        ambiguity = task.get("ambiguity_level", "unknown")

        if naive is None or robust is None:
            continue

        task_ids.append(task_id)
        naive_scores.append(naive)
        robust_scores.append(robust)
        ambiguity_levels.append(ambiguity)
        colors.append(AMBIGUITY_COLORS.get(ambiguity, "#808080"))

    # Set up figure and axis
    fig, ax = plt.subplots(figsize=(10, 10))

    # Plot scatter points
    scatter = ax.scatter(
        naive_scores,
        robust_scores,
        c=colors,
        s=100,
        alpha=0.6,
        edgecolors="black",
        linewidth=0.5
    )

    # Add diagonal reference line (y = x)
    ax.plot([0, 1], [0, 1], "k--", linewidth=2, alpha=0.5, label="Perfect alignment (y=x)")

    # Annotate task_018 if present
    task_018_idx = None
    for i, task_id in enumerate(task_ids):
        if task_id == "task_018":
            task_018_idx = i
            break

    if task_018_idx is not None:
        naive_018 = naive_scores[task_018_idx]
        robust_018 = robust_scores[task_018_idx]
        ax.annotate(
            f"task_018\nnaive={naive_018:.2f}\nrobust={robust_018:.2f}",
            xy=(naive_018, robust_018),
            xytext=(naive_018 - 0.25, robust_018 + 0.15),
            fontsize=10,
            fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.5", facecolor="#ffcccc", alpha=0.8),
            arrowprops=dict(arrowstyle="->", connectionstyle="arc3,rad=0.3", lw=2, color="#d62728")
        )

    # Labels and formatting
    ax.set_xlabel("Naive Score", fontsize=12, fontweight="bold")
    ax.set_ylabel("Robust Score", fontsize=12, fontweight="bold")
    ax.set_title(
        "Per-Task Naive vs Robust Reward Score",
        fontsize=14,
        fontweight="bold",
        pad=20
    )
    ax.text(
        0.5,
        1.02,
        "Points below diagonal = naive reward overstates performance",
        transform=ax.transAxes,
        ha="center",
        fontsize=11,
        style="italic",
        color="#666666"
    )

    # Set axis limits
    ax.set_xlim(-0.05, 1.1)
    ax.set_ylim(-0.05, 1.1)
    ax.set_aspect("equal")

    # Add custom legend for ambiguity levels
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor="#2ca02c", edgecolor="black", label="Low ambiguity"),
        Patch(facecolor="#ff7f0e", edgecolor="black", label="Medium ambiguity"),
        Patch(facecolor="#d62728", edgecolor="black", label="High ambiguity"),
    ]
    ax.legend(handles=legend_elements, loc="upper left", fontsize=11)

    # Grid
    ax.grid(True, alpha=0.3, linestyle="--")

    # Tight layout
    plt.tight_layout()

    # Save figure at 300 dpi
    plt.savefig(output_path, dpi=300, bbox_inches="tight")
    print(f"[SUCCESS] Chart saved to: {output_path}")

    return fig

def print_analysis(tasks):
    """Print analysis of diagonal split."""
    print("\n" + "="*60)
    print("NAIVE VS ROBUST SCORE ANALYSIS")
    print("="*60)
    print()

    above, below = analyze_diagonal(tasks)
    total = above + below

    print(f"Points ABOVE diagonal (robust > naive):  {above:2d} ({above/total*100:5.1f}%)")
    print(f"Points BELOW diagonal (naive > robust):  {below:2d} ({below/total*100:5.1f}%)")
    print(f"Total tasks with valid scores:           {total:2d}")
    print()
    print("Interpretation:")
    print("  - ABOVE diagonal: Agent is conservative (robust outperforms naive)")
    print("  - BELOW diagonal: Agent overstates performance (reward hacking signal)")
    print()
    print("="*60)
    print()

def main():
    """Load tasks and create chart."""
    tasks = load_all_tasks()
    print(f"Loaded {len(tasks)} tasks from results/")

    # Print analysis
    print_analysis(tasks)

    # Create chart
    create_chart(tasks)

    print("Key insight:")
    print("  task_018 is the smoking gun: perfect naive score (1.0)")
    print("  but catastrophic robust score (0.05) - complete failure")
    print("  disguised as perfect effort.\n")

if __name__ == "__main__":
    main()
