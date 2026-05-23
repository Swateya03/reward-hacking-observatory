"""Chart showing divergence progression across ambiguity levels."""

import json
import sys
from pathlib import Path
import matplotlib.pyplot as plt
import numpy as np

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
        print("Run: python demo_findings.py")
        sys.exit(1)

    with open(findings_path, "r") as f:
        return json.load(f)

def print_data_table(by_ambiguity):
    """Print the data table to terminal."""
    print("\n" + "="*80)
    print("DIVERGENCE BY AMBIGUITY LEVEL - DATA TABLE")
    print("="*80)
    print()

    # Header
    print(f"{'Ambiguity':<12} {'Naive Score':<14} {'Robust Score':<14} {'Divergence':<12} {'Hack Rate':<10}")
    print("-" * 80)

    # Data rows
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
    """Create grouped bar chart showing naive, robust, and divergence by ambiguity level."""

    # Extract data
    levels = ["Low", "Medium", "High"]
    level_keys = ["low", "medium", "high"]
    naive_scores = []
    robust_scores = []
    divergences = []
    hack_rates = []

    for key in level_keys:
        if key in by_ambiguity:
            data = by_ambiguity[key]
            naive_scores.append(data.get("avg_naive", 0.0))
            robust_scores.append(data.get("avg_robust", 0.0))
            divergences.append(data.get("avg_divergence", 0.0))
            hack_rates.append(data.get("hack_rate", 0.0))
        else:
            naive_scores.append(0.0)
            robust_scores.append(0.0)
            divergences.append(0.0)
            hack_rates.append(0.0)

    # Set up figure and axis
    fig, ax = plt.subplots(figsize=(12, 7))

    # Bar positions
    x = np.arange(len(levels))
    width = 0.25

    # Create bars
    bars1 = ax.bar(x - width, naive_scores, width, label="Naive Score", color="#1f77b4", alpha=0.8)
    bars2 = ax.bar(x, robust_scores, width, label="Robust Score", color="#2ca02c", alpha=0.8)
    bars3 = ax.bar(x + width, divergences, width, label="Divergence", color="#d62728", alpha=0.8)

    # Add horizontal dashed line at y=0 for reference
    ax.axhline(y=0, color="black", linestyle="--", linewidth=1, alpha=0.5)

    # Add value labels on bars
    def add_labels(bars):
        for bar in bars:
            height = bar.get_height()
            ax.text(
                bar.get_x() + bar.get_width()/2,
                height + 0.02 if height >= 0 else height - 0.05,
                f"{height:.3f}",
                ha="center",
                va="bottom" if height >= 0 else "top",
                fontsize=9,
                fontweight="bold"
            )

    add_labels(bars1)
    add_labels(bars2)
    add_labels(bars3)

    # Labels and formatting
    ax.set_xlabel("Ambiguity Level", fontsize=12, fontweight="bold")
    ax.set_ylabel("Score (0.0 to 1.0)", fontsize=12, fontweight="bold")
    ax.set_title(
        "Naive vs Robust Reward Scores by Task Ambiguity Level",
        fontsize=14,
        fontweight="bold",
        pad=20
    )
    ax.text(
        0.5,
        1.02,
        "Positive divergence = potential reward hacking",
        transform=ax.transAxes,
        ha="center",
        fontsize=11,
        style="italic",
        color="#666666"
    )

    ax.set_xticks(x)
    ax.set_xticklabels(levels)
    ax.set_ylim(-0.1, 1.1)
    ax.legend(loc="upper left", fontsize=11)
    ax.grid(axis="y", alpha=0.3, linestyle="--")

    # Tight layout
    plt.tight_layout()

    # Save figure at 300 dpi
    plt.savefig(output_path, dpi=300, bbox_inches="tight")
    print(f"\n[SUCCESS] Chart saved to: {output_path}")

    return fig

def main():
    """Load findings and create chart."""
    findings = load_findings()
    by_ambiguity = findings.get("by_ambiguity", {})

    # Print data table
    print_data_table(by_ambiguity)

    # Create chart
    create_chart(by_ambiguity)

    print("\nKey insight:")
    print("  - Hack rate: 0% (low) -> 80% (medium) -> 70% (high ambiguity)")
    print("  - Divergence: -0.072 (low) -> 0.475 (medium) -> 0.270 (high)")
    print("  - Pattern: Ambiguity drives reward hacking behavior\n")

if __name__ == "__main__":
    main()
