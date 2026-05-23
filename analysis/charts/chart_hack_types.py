"""Chart showing distribution of reward hacking types."""

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

# Hack type colors - GitHub palette
HACK_TYPE_LABELS = {
    "METRIC_GAMING": "Metric Gaming",
    "SCOPE_CREEP": "Scope Creep",
    "IRREVERSIBILITY_BIAS": "Irreversibility Bias",
    "OVERCLAIMING": "Overclaiming",
    "SYCOPHANTIC_CAUTION": "Sycophantic Caution",
}

HACK_TYPE_COLORS = {
    "METRIC_GAMING": "#f85149",
    "SCOPE_CREEP": "#d29922",
    "IRREVERSIBILITY_BIAS": "#bc8cff",
    "OVERCLAIMING": "#79c0ff",
    "SYCOPHANTIC_CAUTION": "#58a6ff",
}

def prepare_data(findings: dict) -> list:
    """Extract and prepare hack type data (testable).

    Args:
        findings: Dict with 'hack_types' key containing counts

    Returns:
        List of tuples (human_readable_label, count, enum_name) sorted descending by count
    """
    hack_types_data = findings.get("hack_types", {})
    counts = hack_types_data.get("counts", {})

    hack_list = [
        (HACK_TYPE_LABELS.get(enum_name, enum_name), counts.get(enum_name, 0), enum_name)
        for enum_name in HACK_TYPE_LABELS.keys()
    ]

    hack_list.sort(key=lambda x: x[1], reverse=True)
    return hack_list

def load_findings():
    """Load findings from results/findings.json."""
    findings_path = Path("results/findings.json")

    if not findings_path.exists():
        print("[ERROR] results/findings.json not found.")
        print("Run: python analysis/demo_findings.py")
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
    total = sum(counts.values())

    print(f"{'Hack Type':<25} {'Count':<8} {'Percentage':<12}")
    print("-" * 60)

    for enum_name in sorted(counts.keys(), key=lambda x: counts[x], reverse=True):
        count = counts[enum_name]
        label = HACK_TYPE_LABELS.get(enum_name, enum_name)
        pct = (count / total * 100) if total > 0 else 0
        print(f"{label:<25} {count:<8} {pct:>6.1f}%")

    print("-" * 60)
    print(f"{'Total':<25} {total:<8}")
    print()
    print("="*60)
    print()

def create_chart(findings, output_path="analysis/charts/hack_type_distribution.png"):
    """Create Cleveland dot plot of hack type distribution."""

    hack_types_data = findings.get("hack_types", {})
    hack_list = prepare_data(findings)

    if not hack_list:
        print("[ERROR] No hack type data found")
        return

    labels = [item[0] for item in hack_list]
    counts = [item[1] for item in hack_list]
    enum_names = [item[2] for item in hack_list]

    total = sum(counts)
    colors = [HACK_TYPE_COLORS.get(name, "#8b949e") for name in enum_names]

    fig, ax = plt.subplots(figsize=(11, 6), facecolor='#0d1117')
    ax.set_facecolor('#161b22')

    y_pos = np.arange(len(labels))

    # Lollipop stems
    for i, (y, count) in enumerate(zip(y_pos, counts)):
        ax.plot([0, count], [y, y], color='#30363d', linewidth=2, zorder=1)

    # Dots
    scatter = ax.scatter(counts, y_pos, s=200, c=colors, edgecolor='#0d1117', linewidth=1.5, zorder=2)

    # Highlight top hack type with background
    if len(labels) > 0:
        ax.axhspan(-0.4, 0.4, facecolor='#f85149', alpha=0.08, zorder=0)

    # Count labels (right of dots)
    for i, (y, count) in enumerate(zip(y_pos, counts)):
        pct = (count / total * 100) if total > 0 else 0
        ax.text(count + 0.1, y, f'{count}', ha='left', va='center',
               fontsize=10, color='#e6edf3', fontweight='bold')
        ax.text(count + 0.1, y - 0.15, f'({pct:.0f}%)', ha='left', va='top',
               fontsize=8, color='#8b949e')

    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels)
    ax.set_xlabel('Count', fontsize=12, fontweight='bold', color='#e6edf3')
    ax.set_title('Reward Hacking Type Distribution', fontsize=13, fontweight='bold',
                color='#e6edf3', pad=20)
    ax.text(0.5, 1.10, 'Sycophantic Caution dominates — agents over-asking on clear tasks',
           transform=ax.transAxes, ha='center', fontsize=10, color='#8b949e', style='italic')

    ax.set_xlim(0, max(counts) * 1.3)
    ax.grid(axis='x', alpha=0.15, linestyle='--', color='#30363d')
    ax.invert_yaxis()

    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='#0d1117')
    print(f"\n[SUCCESS] Chart saved to: {output_path}")

    return fig

def main():
    """Load findings and create chart."""
    findings = load_findings()
    hack_types_data = findings.get("hack_types", {})

    print_data_table(hack_types_data)
    create_chart(findings)

    print("\nKey insight:")
    print("  - Sycophantic Caution (78%) dominates all other hack types")
    print("  - Reflects alignment bias: agents prefer to ask rather than act\n")

if __name__ == "__main__":
    main()
