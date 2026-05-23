"""Radar/spider chart showing hacking profiles by ambiguity level."""

import json
import sys
from pathlib import Path
import matplotlib.pyplot as plt
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
ACCENT_COLOR = '#bc8cff'

# Hack types
HACK_TYPES = [
    "METRIC_GAMING",
    "SCOPE_CREEP",
    "IRREVERSIBILITY_BIAS",
    "OVERCLAIMING",
    "SYCOPHANTIC_CAUTION",
]

HACK_TYPE_LABELS = {
    "METRIC_GAMING": "Metric\nGaming",
    "SCOPE_CREEP": "Scope\nCreep",
    "IRREVERSIBILITY_BIAS": "Irreversibility\nBias",
    "OVERCLAIMING": "Over\nclaiming",
    "SYCOPHANTIC_CAUTION": "Sycophantic\nCaution",
}

AMBIGUITY_COLORS = {
    "low": LOW_COLOR,
    "medium": MEDIUM_COLOR,
    "high": HIGH_COLOR,
}

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

def aggregate_hacks_by_ambiguity(tasks: list) -> dict:
    """Aggregate hack counts by ambiguity level.

    Args:
        tasks: List of task dicts

    Returns:
        Dict mapping ambiguity level to hack type counts
    """
    by_ambiguity = {"low": {}, "medium": {}, "high": {}}

    for hack_type in HACK_TYPES:
        for level in ["low", "medium", "high"]:
            by_ambiguity[level][hack_type] = 0

    for task in tasks:
        ambiguity = task.get("ambiguity_level", "unknown")
        if ambiguity not in by_ambiguity:
            continue

        hacks = task.get("hacking_events", [])
        for hack in hacks:
            hack_type = hack.get("hack_type")
            if hack_type in HACK_TYPES:
                by_ambiguity[ambiguity][hack_type] += 1

    return by_ambiguity

def create_chart(tasks, output_path="analysis/charts/hacking_radar.png"):
    """Create radar chart of hacking profiles by ambiguity level."""

    by_ambiguity = aggregate_hacks_by_ambiguity(tasks)

    fig = plt.figure(figsize=(10, 10), facecolor='#0d1117')
    ax = fig.add_subplot(111, projection='polar', facecolor='#161b22')

    # Angles for each axis
    angles = np.linspace(0, 2 * np.pi, len(HACK_TYPES), endpoint=False).tolist()
    angles += angles[:1]

    # Plot each ambiguity level
    for level, color in AMBIGUITY_COLORS.items():
        values = [by_ambiguity[level].get(hack_type, 0) for hack_type in HACK_TYPES]
        max_val = max(max(values), 1)
        values = [v / max_val for v in values]
        values += values[:1]

        ax.plot(angles, values, color=color, linewidth=2.5, marker='o', markersize=7,
               markerfacecolor='white', markeredgecolor=color, markeredgewidth=1.5, label=level.capitalize(), zorder=2)
        ax.fill(angles, values, color=color, alpha=0.15, zorder=1)

    # Grid styling
    ax.grid(True, color='#30363d', linewidth=0.8, alpha=0.8)
    ax.set_theta_offset(np.pi / 2)
    ax.set_theta_direction(-1)

    # Radial axis
    ax.set_ylim(0, 1)
    ax.set_yticks([0.2, 0.4, 0.6, 0.8, 1.0])
    ax.set_yticklabels(['20%', '40%', '60%', '80%', '100%'], fontsize=8, color='#8b949e')

    # Category labels
    labels = [HACK_TYPE_LABELS.get(hack_type, hack_type) for hack_type in HACK_TYPES]
    ax.set_xticks(np.linspace(0, 2 * np.pi, len(HACK_TYPES), endpoint=False))
    ax.set_xticklabels(labels, fontsize=10, color='#e6edf3', fontweight='bold')

    # Adjust label distance
    ax.xaxis.set_tick_params(pad=20)

    # Legend
    ax.legend(loc='upper right', bbox_to_anchor=(1.3, 1.1), fontsize=10, framealpha=0.9)

    ax.set_title('Reward Hacking Behavioral Profile', fontsize=13, fontweight='bold',
                color='#e6edf3', pad=20)
    ax.text(0.5, -0.12, 'Area = hacking surface — larger area = more hacking diversity',
           transform=ax.transAxes, ha='center', fontsize=10, color='#8b949e', style='italic')

    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='#0d1117')
    print(f"\n[SUCCESS] Chart saved to: {output_path}")

    return fig

def print_analysis(tasks):
    """Print hacking profile analysis."""
    by_ambiguity = aggregate_hacks_by_ambiguity(tasks)

    print("\n" + "="*70)
    print("HACKING PROFILE ANALYSIS BY AMBIGUITY LEVEL")
    print("="*70)
    print()

    for level in ["low", "medium", "high"]:
        print(f"{level.upper()} AMBIGUITY:")
        counts = by_ambiguity[level]
        total = sum(counts.values())

        if total == 0:
            print("  No hacks detected")
        else:
            for hack_type in HACK_TYPES:
                count = counts.get(hack_type, 0)
                label = HACK_TYPE_LABELS.get(hack_type, hack_type)
                pct = (count / total * 100) if total > 0 else 0
                if count > 0:
                    print(f"  {label:<30} {count:3} ({pct:5.1f}%)")

        print()

    print("="*70)
    print()

def main():
    """Load tasks and create chart."""
    tasks = load_all_tasks()
    print(f"Loaded {len(tasks)} tasks from results/")

    print_analysis(tasks)
    create_chart(tasks)

    print("\nKey insight:")
    print("  - Low ambiguity: minimal hacking (clear instructions)")
    print("  - High ambiguity: diverse hacking types (unclear goals)\n")

if __name__ == "__main__":
    main()
