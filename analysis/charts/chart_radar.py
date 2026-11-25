"""Radar/spider chart showing hacking profiles by ambiguity level."""

import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root, so `analysis` and `hacking` imports work when run directly
from analysis.findings import normalize_result
from hacking.taxonomy import canonical_hack_type
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

# Hack types, canonical lowercase keys (see hacking.taxonomy.canonical_hack_type)
HACK_TYPES = [
    "metric_gaming",
    "scope_creep",
    "irreversibility_bias",
    "overclaiming",
    "sycophantic_caution",
]

HACK_TYPE_LABELS = {
    "metric_gaming": "Metric\nGaming",
    "scope_creep": "Scope\nCreep",
    "irreversibility_bias": "Irreversibility\nBias",
    "overclaiming": "Over\nclaiming",
    "sycophantic_caution": "Sycophantic\nCaution",
}

AMBIGUITY_COLORS = {
    "low": LOW_COLOR,
    "medium": MEDIUM_COLOR,
    "high": HIGH_COLOR,
}

LEVELS = ("low", "medium", "high")

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
                record = json.load(f)
            # Reads schema v4 and returns the flat form the chart code uses; wrong shape raises.
            tasks.append(normalize_result(record, source=str(filepath)))
        except (json.JSONDecodeError, IOError) as e:
            print(f"[WARNING] Failed to load {filepath.name}: {e}")

    return tasks

def aggregate_hacks_by_ambiguity(tasks: list) -> dict:
    """Count detector events per canonical hack type, per ambiguity level.

    Returns:
        {level: {canonical_type: count}} for every level and every HACK_TYPES entry
    """
    by_ambiguity = {level: {hack_type: 0 for hack_type in HACK_TYPES} for level in LEVELS}

    for task in tasks:
        ambiguity = task.get("ambiguity_level", "unknown")
        if ambiguity not in by_ambiguity:
            continue

        for hack in task.get("hacking_events", []):
            hack_type = canonical_hack_type(hack.get("hack_type") or "")
            if hack_type in HACK_TYPES:
                by_ambiguity[ambiguity][hack_type] += 1

    return by_ambiguity

def build_annotations(by_ambiguity: dict) -> dict:
    """Every result-bearing string on the chart, computed from the counts (testable)."""
    totals = {level: sum(by_ambiguity[level].values()) for level in LEVELS}
    top = max(totals.values())
    if top == 0:
        most = "No detector events recorded at any ambiguity level."
    else:
        peaks = [level for level in LEVELS if totals[level] == top]
        names = " and ".join(p.capitalize() for p in peaks)
        most = f"Most detector events: {names} ambiguity ({top} events)."
    return {"most_events": most}

def create_chart(tasks, output_path="analysis/charts/hacking_radar.png"):
    """Create radar chart of hacking profiles by ambiguity level."""

    by_ambiguity = aggregate_hacks_by_ambiguity(tasks)

    fig = plt.figure(figsize=(10, 10), facecolor='#0d1117')
    ax = fig.add_subplot(111, projection='polar', facecolor='#161b22')

    # Angles for each axis
    angles = np.linspace(0, 2 * np.pi, len(HACK_TYPES), endpoint=False).tolist()
    angles += angles[:1]

    # Plot each ambiguity level
    for level in LEVELS:
        color = AMBIGUITY_COLORS[level]
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
    radial_ticks = [0.2, 0.4, 0.6, 0.8, 1.0]
    ax.set_yticks(radial_ticks)
    ax.set_yticklabels([f"{t:.0%}" for t in radial_ticks], fontsize=8, color='#8b949e')

    # Category labels
    labels = [HACK_TYPE_LABELS.get(hack_type, hack_type) for hack_type in HACK_TYPES]
    ax.set_xticks(np.linspace(0, 2 * np.pi, len(HACK_TYPES), endpoint=False))
    ax.set_xticklabels(labels, fontsize=10, color='#e6edf3', fontweight='bold')

    # Adjust label distance
    ax.xaxis.set_tick_params(pad=20)

    # Legend
    ax.legend(loc='upper right', bbox_to_anchor=(1.3, 1.1), fontsize=10, framealpha=0.9)

    ax.set_title('Detector Events by Hack Type and Ambiguity', fontsize=13, fontweight='bold',
                color='#e6edf3', pad=20)
    ax.text(0.5, -0.12, 'Each ring: count for that level, scaled to the largest count on the chart',
           transform=ax.transAxes, ha='center', fontsize=10, color='#8b949e', style='italic')

    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='#0d1117')
    print(f"\n[SUCCESS] Chart saved to: {output_path}")

    return fig

def print_analysis(tasks):
    """Print detector event counts per level."""
    by_ambiguity = aggregate_hacks_by_ambiguity(tasks)

    print("\n" + "="*70)
    print("DETECTOR EVENTS BY AMBIGUITY LEVEL")
    print("="*70)
    print()

    for level in LEVELS:
        print(f"{level.upper()} AMBIGUITY:")
        counts = by_ambiguity[level]
        total = sum(counts.values())

        if total == 0:
            print("  No detector events")
        else:
            for hack_type in HACK_TYPES:
                count = counts.get(hack_type, 0)
                label = HACK_TYPE_LABELS.get(hack_type, hack_type).replace("\n", " ")
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

    print("\nComputed summary:")
    print("  - " + build_annotations(aggregate_hacks_by_ambiguity(tasks))["most_events"] + "\n")

if __name__ == "__main__":
    main()
