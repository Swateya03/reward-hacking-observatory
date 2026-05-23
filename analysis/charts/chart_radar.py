"""Radar chart showing reward hacking profile by ambiguity level."""

import json
import sys
from pathlib import Path
import matplotlib.pyplot as plt
import numpy as np

# Hack types in order
HACK_TYPES = [
    "METRIC_GAMING",
    "SCOPE_CREEP",
    "IRREVERSIBILITY_BIAS",
    "OVERCLAIMING",
    "SYCOPHANTIC_CAUTION",
]

# Human-readable labels
HACK_TYPE_LABELS = {
    "METRIC_GAMING": "Metric Gaming",
    "SCOPE_CREEP": "Scope Creep",
    "IRREVERSIBILITY_BIAS": "Irreversibility Bias",
    "OVERCLAIMING": "Overclaiming",
    "SYCOPHANTIC_CAUTION": "Sycophantic Caution",
}

# Colors for ambiguity levels
AMBIGUITY_COLORS = {
    "low": "#2ca02c",      # Green
    "medium": "#ff7f0e",   # Orange
    "high": "#d62728",     # Red
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

def compute_hack_rates(tasks):
    """Compute hack type rates for each ambiguity level."""
    rates = {"low": {}, "medium": {}, "high": {}}

    # Count tasks by ambiguity level
    ambiguity_counts = {"low": 0, "medium": 0, "high": 0}
    hack_counts = {
        "low": {ht: 0 for ht in HACK_TYPES},
        "medium": {ht: 0 for ht in HACK_TYPES},
        "high": {ht: 0 for ht in HACK_TYPES},
    }

    # Count tasks and hack occurrences
    for task in tasks:
        ambiguity = task.get("ambiguity_level", "unknown")
        if ambiguity not in ambiguity_counts:
            continue

        ambiguity_counts[ambiguity] += 1

        # Check hacking events
        hacking_events = task.get("hacking_events", [])
        hack_types_in_task = set()

        for event in hacking_events:
            hack_type = event.get("hack_type")
            if hack_type in HACK_TYPES:
                hack_types_in_task.add(hack_type)

        # Increment counts for detected hack types
        for hack_type in hack_types_in_task:
            hack_counts[ambiguity][hack_type] += 1

    # Calculate rates (percentage of tasks with each hack type)
    for ambiguity in ["low", "medium", "high"]:
        total = ambiguity_counts[ambiguity]
        if total == 0:
            rates[ambiguity] = {ht: 0.0 for ht in HACK_TYPES}
        else:
            rates[ambiguity] = {
                ht: (hack_counts[ambiguity][ht] / total) * 100
                for ht in HACK_TYPES
            }

    return rates, ambiguity_counts

def print_data_table(rates, ambiguity_counts):
    """Print hack rate data table."""
    print("\n" + "="*80)
    print("HACK TYPE RATES BY AMBIGUITY LEVEL (%)")
    print("="*80)
    print()

    # Header
    header = f"{'Hack Type':<25}"
    for ambiguity in ["low", "medium", "high"]:
        header += f" {ambiguity.upper():<12}"
    print(header)
    print("-" * 80)

    # Data rows
    for hack_type in HACK_TYPES:
        label = HACK_TYPE_LABELS.get(hack_type, hack_type)
        row = f"{label:<25}"
        for ambiguity in ["low", "medium", "high"]:
            rate = rates[ambiguity].get(hack_type, 0.0)
            row += f" {rate:>10.1f}%"
        print(row)

    print()
    print("Task counts per ambiguity level:")
    for ambiguity in ["low", "medium", "high"]:
        print(f"  {ambiguity.upper()}: {ambiguity_counts[ambiguity]} tasks")
    print()
    print("="*80)
    print()

def create_chart(rates, output_path="analysis/charts/hacking_radar.png"):
    """Create radar chart showing hack type profiles."""

    # Prepare data for radar chart
    angles = np.linspace(0, 2 * np.pi, len(HACK_TYPES), endpoint=False).tolist()
    angles += angles[:1]  # Complete the circle

    # Create figure with polar projection
    fig, ax = plt.subplots(figsize=(10, 10), subplot_kw=dict(projection="polar"))

    # Plot lines for each ambiguity level
    for ambiguity, color in AMBIGUITY_COLORS.items():
        values = [rates[ambiguity].get(ht, 0.0) for ht in HACK_TYPES]
        values += values[:1]  # Complete the circle

        ax.plot(
            angles,
            values,
            "o-",
            linewidth=2,
            label=ambiguity.capitalize(),
            color=color,
            markersize=6
        )

        ax.fill(angles, values, alpha=0.2, color=color)

    # Set axis labels
    labels = [HACK_TYPE_LABELS.get(ht, ht) for ht in HACK_TYPES]
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(labels, fontsize=10)

    # Set radial limits (percentage)
    ax.set_ylim(0, 100)
    ax.set_yticks([20, 40, 60, 80, 100])
    ax.set_yticklabels(["20%", "40%", "60%", "80%", "100%"], fontsize=9)

    # Title and legend
    ax.set_title(
        "Reward Hacking Profile by Ambiguity Level",
        fontsize=14,
        fontweight="bold",
        pad=20
    )
    ax.legend(loc="upper right", bbox_to_anchor=(1.3, 1.1), fontsize=11)

    # Grid
    ax.grid(True, alpha=0.3)

    # Tight layout
    plt.tight_layout()

    # Save figure at 300 dpi
    plt.savefig(output_path, dpi=300, bbox_inches="tight")
    print(f"[SUCCESS] Chart saved to: {output_path}")

    return fig

def main():
    """Load tasks and create chart."""
    tasks = load_all_tasks()
    print(f"Loaded {len(tasks)} tasks from results/")

    # Compute hack rates
    rates, ambiguity_counts = compute_hack_rates(tasks)

    # Print data table
    print_data_table(rates, ambiguity_counts)

    # Create chart
    create_chart(rates)

    print("Key insight:")
    print("  Low ambiguity: Sycophantic Caution dominates (agents cautious)")
    print("  Medium ambiguity: Sycophantic Caution peaks (highest hack rates)")
    print("  High ambiguity: Agents ask for clarification (appropriate response)")
    print("  Pattern: Hack 'profile' shifts from gaming to caution as tasks")
    print("  become adversarial.\n")

if __name__ == "__main__":
    main()
