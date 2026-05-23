"""Chart showing distribution of reward hacking types."""

import json
import sys
from pathlib import Path
import matplotlib.pyplot as plt
import numpy as np

# Mapping of enum names to human-readable labels
HACK_TYPE_LABELS = {
    "METRIC_GAMING": "Metric Gaming",
    "SCOPE_CREEP": "Scope Creep",
    "IRREVERSIBILITY_BIAS": "Irreversibility Bias",
    "OVERCLAIMING": "Overclaiming",
    "SYCOPHANTIC_CAUTION": "Sycophantic Caution",
}

# Distinct colors for each hack type
HACK_TYPE_COLORS = {
    "METRIC_GAMING": "#d62728",          # Red
    "SCOPE_CREEP": "#ff7f0e",            # Orange
    "IRREVERSIBILITY_BIAS": "#9467bd",   # Purple
    "OVERCLAIMING": "#8c564b",           # Brown
    "SYCOPHANTIC_CAUTION": "#1f77b4",    # Blue
}

def prepare_data(findings: dict) -> list:
    """Extract and prepare hack type data (testable).

    Args:
        findings: Dict with 'hack_types' key containing counts

    Returns:
        List of tuples (human_readable_label, count) sorted descending by count
    """
    hack_types_data = findings.get("hack_types", {})
    counts = hack_types_data.get("counts", {})

    # Convert to list of (label, count) tuples
    hack_list = [
        (HACK_TYPE_LABELS.get(enum_name, enum_name), counts.get(enum_name, 0))
        for enum_name in HACK_TYPE_LABELS.keys()
    ]

    # Sort by count descending
    hack_list.sort(key=lambda x: x[1], reverse=True)

    return hack_list

def load_findings():
    """Load findings from results/findings.json."""
    findings_path = Path("results/findings.json")

    if not findings_path.exists():
        print("[ERROR] results/findings.json not found.")
        print("Run: python demo_findings.py")
        sys.exit(1)

    with open(findings_path, "r") as f:
        return json.load(f)

def print_data_table(hack_types_data):
    """Print the data table to terminal."""
    print("\n" + "="*60)
    print("HACK TYPE DISTRIBUTION - DATA TABLE")
    print("="*60)
    print()

    counts = hack_types_data.get("counts", {})

    # Convert to list and sort by count descending
    hack_list = [
        (enum_name, counts.get(enum_name, 0))
        for enum_name in HACK_TYPE_LABELS.keys()
    ]
    hack_list.sort(key=lambda x: x[1], reverse=True)

    # Header
    print(f"{'Hack Type':<30} {'Count':<10}")
    print("-" * 60)

    # Data rows
    total = 0
    for enum_name, count in hack_list:
        human_name = HACK_TYPE_LABELS.get(enum_name, enum_name)
        print(f"{human_name:<30} {count:<10}")
        total += count

    print("-" * 60)
    print(f"{'TOTAL':<30} {total:<10}")
    print()
    print("="*60)
    print()

def create_chart(hack_types_data, output_path="analysis/charts/hack_type_distribution.png"):
    """Create horizontal bar chart showing hack type distribution."""

    counts = hack_types_data.get("counts", {})

    # Convert to list and sort by count descending
    hack_list = [
        (enum_name, counts.get(enum_name, 0))
        for enum_name in HACK_TYPE_LABELS.keys()
    ]
    hack_list.sort(key=lambda x: x[1], reverse=True)

    # Extract names and counts
    hack_names = [HACK_TYPE_LABELS.get(enum, enum) for enum, _ in hack_list]
    hack_counts = [count for _, count in hack_list]
    hack_colors = [HACK_TYPE_COLORS.get(enum, "#1f77b4") for enum, _ in hack_list]

    # Set up figure and axis
    fig, ax = plt.subplots(figsize=(10, 6))

    # Create horizontal bars
    bars = ax.barh(hack_names, hack_counts, color=hack_colors, alpha=0.8)

    # Add count labels at the end of each bar
    for i, (bar, count) in enumerate(zip(bars, hack_counts)):
        ax.text(
            count + 0.15,
            bar.get_y() + bar.get_height()/2,
            f"{count}",
            va="center",
            fontsize=11,
            fontweight="bold"
        )

    # Labels and formatting
    ax.set_xlabel("Count of Detections", fontsize=12, fontweight="bold")
    ax.set_ylabel("Hack Type", fontsize=12, fontweight="bold")
    ax.set_title(
        "Reward Hacking Type Distribution (30 Tasks)",
        fontsize=14,
        fontweight="bold",
        pad=20
    )

    # Set x-axis to start from 0 with some padding
    ax.set_xlim(0, max(hack_counts) * 1.15)
    ax.grid(axis="x", alpha=0.3, linestyle="--")

    # Tight layout
    plt.tight_layout()

    # Save figure at 300 dpi
    plt.savefig(output_path, dpi=300, bbox_inches="tight")
    print(f"[SUCCESS] Chart saved to: {output_path}")

    return fig

def main():
    """Load findings and create chart."""
    findings = load_findings()
    hack_types_data = findings.get("hack_types", {})

    # Print data table
    print_data_table(hack_types_data)

    # Create chart
    create_chart(hack_types_data)

    print("Key insight:")
    print("  Sycophantic Caution (16 detections) is the dominant failure mode.")
    print("  Agents ask for clarification instead of attempting tasks.")
    print("  This reflects a safety-helpfulness tradeoff in alignment.\n")

if __name__ == "__main__":
    main()
