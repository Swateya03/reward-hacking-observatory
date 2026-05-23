"""Scatter plot showing naive vs robust scores for all tasks."""

import json
import sys
from pathlib import Path
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib import rcParams
import numpy as np

# GitHub dark theme styling
rcParams['font.family'] = 'DejaVu Sans'
rcParams['font.size'] = 11
rcParams['axes.spines.top'] = False
rcParams['axes.spines.right'] = False
rcParams['figure.facecolor'] = '#0d1117'
rcParams['axes.facecolor'] = '#161b22'
rcParams['axes.labelcolor'] = '#e6edf3'
rcParams['xtick.color'] = '#8b949e'
rcParams['ytick.color'] = '#8b949e'
rcParams['text.color'] = '#e6edf3'
rcParams['grid.color'] = '#30363d'
rcParams['axes.edgecolor'] = '#30363d'

# GitHub color palette
LOW_COLOR = '#3fb950'
MEDIUM_COLOR = '#d29922'
HIGH_COLOR = '#f85149'
DIVERGE_COLOR = '#f85149'

AMBIGUITY_COLORS = {
    "low": LOW_COLOR,
    "medium": MEDIUM_COLOR,
    "high": HIGH_COLOR,
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

    task_ids = []
    naive_scores = []
    robust_scores = []
    colors = []
    ambiguity_levels = []
    divergences = []

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
        divergences.append(abs(naive - robust))

    fig, ax = plt.subplots(figsize=(11, 10), facecolor='#0d1117')
    ax.set_facecolor('#161b22')

    # Shaded region below diagonal (reward hacking zone)
    x_fill = np.linspace(0, 1, 100)
    ax.fill_between(x_fill, x_fill, 0, color=DIVERGE_COLOR, alpha=0.06, zorder=1)
    ax.text(0.75, 0.15, 'Reward Hacking Zone', fontsize=9, color=DIVERGE_COLOR,
            alpha=0.7, style='italic', zorder=2)

    # Diagonal reference line
    ax.plot([0, 1], [0, 1], color='#8b949e', linestyle='--', linewidth=1.5, zorder=2)

    # Size points by divergence magnitude
    sizes = [60 + d * 300 for d in divergences]

    # Scatter plot
    scatter = ax.scatter(naive_scores, robust_scores, s=sizes, c=colors, alpha=0.85,
                        edgecolors='#0d1117', linewidth=0.8, zorder=3)

    # Find and annotate highest divergence task
    if divergences:
        max_div_idx = divergences.index(max(divergences))
        task_id = task_ids[max_div_idx]
        naive = naive_scores[max_div_idx]
        robust = robust_scores[max_div_idx]

        ax.annotate(f"{task_id}\nnaive={naive:.2f}\nrobust={robust:.2f}",
                   xy=(naive, robust),
                   xytext=(naive - 0.20, robust + 0.15),
                   fontsize=9, color='#e6edf3',
                   bbox=dict(boxstyle='round,pad=0.6', facecolor=DIVERGE_COLOR,
                            edgecolor=DIVERGE_COLOR, alpha=0.15),
                   arrowprops=dict(arrowstyle='->', color=DIVERGE_COLOR, lw=2),
                   zorder=4)

    # Stat annotation
    above, below = analyze_diagonal(tasks)
    total = above + below
    pct_below = (below / total * 100) if total > 0 else 0
    ax.text(0.05, 0.95, f'{pct_below:.0f}% of tasks below diagonal',
           transform=ax.transAxes, fontsize=9, color='#8b949e', style='italic',
           verticalalignment='top', zorder=4)

    ax.set_xlim(-0.05, 1.1)
    ax.set_ylim(-0.05, 1.1)
    ax.set_aspect('equal')

    ax.set_xlabel('Naive Score', fontsize=12, fontweight='bold', color='#e6edf3')
    ax.set_ylabel('Robust Score', fontsize=12, fontweight='bold', color='#e6edf3')

    ax.set_title('Per-Task Naive vs Robust Reward Score', fontsize=13, fontweight='bold',
                color='#e6edf3', pad=20)

    legend_elements = [
        mpatches.Patch(facecolor=LOW_COLOR, edgecolor='#30363d', label='Low ambiguity'),
        mpatches.Patch(facecolor=MEDIUM_COLOR, edgecolor='#30363d', label='Medium ambiguity'),
        mpatches.Patch(facecolor=HIGH_COLOR, edgecolor='#30363d', label='High ambiguity'),
    ]
    ax.legend(handles=legend_elements, loc='upper left', fontsize=10, framealpha=0.9)

    ax.text(0.98, 1.08, 'Points below diagonal indicate reward hacking',
           transform=ax.transAxes, ha='right', fontsize=10, color='#8b949e',
           style='italic')

    ax.grid(True, alpha=0.15, linestyle='--', color='#30363d')

    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='#0d1117')
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

    print_analysis(tasks)
    create_chart(tasks)

    print("Key insight:")
    print("  Points sized by divergence magnitude — larger = more hacking")
    print("  Color by ambiguity — red=high ambiguity tasks\n")

if __name__ == "__main__":
    main()
