"""Chart showing distribution of reward hacking types."""

import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root, so `hacking` imports work when run directly
import matplotlib.pyplot as plt
from matplotlib import rcParams
import numpy as np
from hacking.taxonomy import canonical_hack_type

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

# Canonical keys: lowercase enum values (see hacking.taxonomy.canonical_hack_type).
HACK_TYPE_LABELS = {
    "metric_gaming": "Metric Gaming",
    "scope_creep": "Scope Creep",
    "irreversibility_bias": "Irreversibility Bias",
    "overclaiming": "Overclaiming",
    "sycophantic_caution": "Sycophantic Caution",
}

HACK_TYPE_COLORS = {
    "metric_gaming": "#f85149",
    "scope_creep": "#d29922",
    "irreversibility_bias": "#bc8cff",
    "overclaiming": "#79c0ff",
    "sycophantic_caution": "#58a6ff",
}


def canonical_counts(findings: dict) -> dict:
    """Hack-type counts keyed by the canonical lowercase name. Input keys may be
    any casing (the legacy file uses uppercase)."""
    raw = (findings.get("hack_types") or {}).get("counts") or {}
    out = {}
    for name, count in raw.items():
        key = canonical_hack_type(name)
        out[key] = out.get(key, 0) + count
    return out


def prepare_data(findings: dict) -> list:
    """Extract and prepare hack type data (testable).

    Returns:
        List of tuples (human_readable_label, count, canonical_name) sorted descending by count
    """
    counts = canonical_counts(findings)

    hack_list = [
        (HACK_TYPE_LABELS[name], counts.get(name, 0), name)
        for name in HACK_TYPE_LABELS
    ]

    hack_list.sort(key=lambda x: x[1], reverse=True)
    return hack_list

def build_subtitle(findings: dict) -> str:
    """The subtitle, computed from the hack-type counts (testable).

    Names the most frequent type and its share. Ties are named as a tie.
    """
    rows = prepare_data(findings)
    total = sum(count for _, count, _ in rows)
    if total == 0:
        return "No hack events recorded."
    top_count = rows[0][1]
    tied = [label for label, count, _ in rows if count == top_count]
    share = top_count / total * 100
    if len(tied) == 1:
        return f"{tied[0]} is the most frequent: {top_count} of {total} events ({share:.0f}%)."
    return f"Tie for most frequent: {' and '.join(tied)}, {top_count} of {total} events each ({share:.0f}%)."

def load_findings():
    """Load the legacy findings file (see results/legacy/NOTE.md)."""
    findings_path = Path("results/legacy/findings_partial_run.json")

    if not findings_path.exists():
        print("[ERROR] results/legacy/findings_partial_run.json not found.")
        print("This chart reads only the legacy file; see results/legacy/NOTE.md.")
        sys.exit(1)

    with open(findings_path, "r") as f:
        return json.load(f)

def print_data_table(findings):
    """Print the data table to terminal."""
    print("\n" + "="*60)
    print("HACK TYPE DISTRIBUTION - DATA TABLE")
    print("="*60)
    print()

    rows = prepare_data(findings)
    total = sum(count for _, count, _ in rows)

    print(f"{'Hack Type':<25} {'Count':<8} {'Percentage':<12}")
    print("-" * 60)

    for label, count, _ in sorted(rows, key=lambda r: r[1], reverse=True):
        pct = (count / total * 100) if total > 0 else 0
        print(f"{label:<25} {count:<8} {pct:>6.1f}%")

    print("-" * 60)
    print(f"{'Total':<25} {total:<8}")
    print()
    print("="*60)
    print()

def create_chart(findings, output_path="analysis/charts/hack_type_distribution.png"):
    """Create Cleveland dot plot of hack type distribution."""

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
    ax.text(0.5, 1.10, build_subtitle(findings),
           transform=ax.transAxes, ha='center', fontsize=10, color='#8b949e', style='italic')

    ax.set_xlim(0, max(max(counts), 1) * 1.3)
    ax.grid(axis='x', alpha=0.15, linestyle='--', color='#30363d')
    ax.invert_yaxis()

    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='#0d1117')
    print(f"\n[SUCCESS] Chart saved to: {output_path}")

    return fig

def main():
    """Load findings and create chart."""
    findings = load_findings()

    print_data_table(findings)
    create_chart(findings)

    print("\nComputed summary:")
    print("  - " + build_subtitle(findings) + "\n")

if __name__ == "__main__":
    main()
