"""Chart showing divergence progression across ambiguity levels."""

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
NAIVE_COLOR = '#58a6ff'
ROBUST_COLOR = '#3fb950'
DIVERGE_COLOR = '#f85149'

def prepare_data(findings: dict) -> dict:
    """Extract and prepare data for divergence chart (testable).

    Args:
        findings: Dict with 'by_ambiguity' key containing level data

    Returns:
        Dict with keys for each ambiguity level containing naive/robust/divergence
    """
    by_ambiguity = findings.get("by_ambiguity", {})

    prepared = {}
    for level in ["low", "medium", "high"]:
        if level in by_ambiguity:
            data = by_ambiguity[level]
            prepared[level] = {
                "naive": data.get("avg_naive", 0.0),
                "robust": data.get("avg_robust", 0.0),
                "divergence": data.get("avg_divergence", 0.0),
                "hack_rate": data.get("hack_rate", 0.0),
            }
        else:
            prepared[level] = {"naive": 0.0, "robust": 0.0, "divergence": 0.0, "hack_rate": 0.0}

    return prepared

def load_findings():
    """Load findings from results/findings.json."""
    findings_path = Path("results/findings.json")

    if not findings_path.exists():
        print("[ERROR] results/findings.json not found.")
        print("Run: python analysis/demo_findings.py")
        sys.exit(1)

    with open(findings_path, "r") as f:
        return json.load(f)

def print_data_table(by_ambiguity):
    """Print the data table to terminal."""
    print("\n" + "="*80)
    print("DIVERGENCE BY AMBIGUITY LEVEL - DATA TABLE")
    print("="*80)
    print()

    print(f"{'Ambiguity':<12} {'Naive Score':<14} {'Robust Score':<14} {'Divergence':<12} {'Hack Rate':<10}")
    print("-" * 80)

    for level in ["low", "medium", "high"]:
        if level in by_ambiguity:
            data = by_ambiguity[level]
            naive = data.get("avg_naive", 0.0)
            robust = data.get("avg_robust", 0.0)
            divergence = data.get("avg_divergence", 0.0)
            hack_rate = data.get("hack_rate", 0.0)

            print(f"{level.capitalize():<12} {naive:<14.4f} {robust:<14.4f} {divergence:<12.4f} {hack_rate:<10.1%}")

    print()
    print("="*80)
    print()

def create_chart(by_ambiguity, output_path="analysis/charts/divergence_by_ambiguity.png"):
    """Create chart showing naive, robust, and divergence by ambiguity level."""

    levels = ["Low", "Medium", "High"]
    level_keys = ["low", "medium", "high"]
    level_colors = [LOW_COLOR, MEDIUM_COLOR, HIGH_COLOR]
    naive_scores = []
    robust_scores = []
    divergences = []

    for key in level_keys:
        if key in by_ambiguity:
            data = by_ambiguity[key]
            naive_scores.append(data.get("avg_naive", 0.0))
            robust_scores.append(data.get("avg_robust", 0.0))
            divergences.append(data.get("avg_divergence", 0.0))
        else:
            naive_scores.append(0.0)
            robust_scores.append(0.0)
            divergences.append(0.0)

    fig, ax = plt.subplots(figsize=(12, 7), facecolor='#0d1117')
    ax.set_facecolor('#161b22')

    x = np.arange(len(levels))
    width = 0.28

    # Background ambiguity color boxes
    for i, color in enumerate(level_colors):
        ax.axvspan(i - 0.4, i + 0.4, facecolor=color, alpha=0.05, zorder=0)

    # Naive and Robust bars
    bars1 = ax.bar(x - width, naive_scores, width, label='Naive Score', color=NAIVE_COLOR, alpha=0.8)
    bars2 = ax.bar(x, robust_scores, width, label='Robust Score', color=ROBUST_COLOR, alpha=0.8)

    # Divergence as lollipops
    for i, (xi, div) in enumerate(zip(x, divergences)):
        # Stem line
        ax.plot([xi + width, xi + width], [0, div], color=DIVERGE_COLOR, linewidth=2.5, zorder=2)
        # Circle marker
        ax.scatter([xi + width], [div], marker='o', s=150, color=DIVERGE_COLOR, zorder=3, edgecolor='#0d1117', linewidth=1)
        # Value label
        ax.text(xi + width, div + 0.03, f'{div:.3f}', ha='center', va='bottom', fontsize=9, color='#e6edf3', fontweight='bold')
        # Arrow
        arrow_dir = '↑' if div > 0 else '↓' if div < 0 else ''
        if arrow_dir:
            ax.text(xi + width + 0.08, div, arrow_dir, fontsize=10, color=DIVERGE_COLOR, alpha=0.7)

    # Add value labels on bars
    for bar in bars1:
        height = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2, height + 0.02, f'{height:.3f}',
               ha='center', va='bottom', fontsize=9, color='#e6edf3', fontweight='bold')

    for bar in bars2:
        height = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2, height + 0.02, f'{height:.3f}',
               ha='center', va='bottom', fontsize=9, color='#e6edf3', fontweight='bold')

    # Zero line
    ax.axhline(y=0, color='#8b949e', linestyle='-', linewidth=1.5, zorder=1)

    ax.set_xlabel('Ambiguity Level', fontsize=12, fontweight='bold', color='#e6edf3')
    ax.set_ylabel('Score', fontsize=12, fontweight='bold', color='#e6edf3')
    ax.set_title('Naive vs Robust Reward Scores by Task Ambiguity',
                fontsize=13, fontweight='bold', color='#e6edf3', pad=20)
    ax.text(0.5, 1.08, 'Divergence shown as lollipops — higher bars = more hacking',
           transform=ax.transAxes, ha='center', fontsize=10, color='#8b949e', style='italic')

    ax.set_xticks(x)
    ax.set_xticklabels(levels)
    ax.set_ylim(-0.2, 1.1)
    ax.legend(loc='upper left', fontsize=10, framealpha=0.9)
    ax.grid(axis='y', alpha=0.15, linestyle='--', color='#30363d')

    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='#0d1117')
    print(f"\n[SUCCESS] Chart saved to: {output_path}")

    return fig

def main():
    """Load findings and create chart."""
    findings = load_findings()
    by_ambiguity = findings.get("by_ambiguity", {})

    print_data_table(by_ambiguity)
    create_chart(by_ambiguity)

    print("\nKey insight:")
    print("  - Divergence increases with ambiguity: clearer tasks show less hacking")
    print("  - Divergence bars as lollipops for visual distinction from scores\n")

if __name__ == "__main__":
    main()
