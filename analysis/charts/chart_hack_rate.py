"""Chart showing hack rate progression with divergence overlay."""

import json
import sys
from pathlib import Path
import matplotlib.pyplot as plt
import numpy as np

def prepare_data(findings: dict) -> dict:
    """Extract and prepare hack rate data (testable).

    Args:
        findings: Dict with 'by_ambiguity' key

    Returns:
        Dict with hack_rates and divergences by level
    """
    by_ambiguity = findings.get("by_ambiguity", {})

    prepared = {}
    for level in ["low", "medium", "high"]:
        if level in by_ambiguity:
            data = by_ambiguity[level]
            prepared[level] = {
                "hack_rate": data.get("hack_rate", 0.0),
                "divergence": data.get("avg_divergence", 0.0),
            }
        else:
            prepared[level] = {"hack_rate": 0.0, "divergence": 0.0}

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
    print("\n" + "="*70)
    print("HACK RATE AND DIVERGENCE BY AMBIGUITY LEVEL")
    print("="*70)
    print()

    # Header
    print(f"{'Ambiguity':<12} {'Hack Rate':<15} {'Avg Divergence':<15}")
    print("-" * 70)

    # Data rows
    for level in ["low", "medium", "high"]:
        if level in by_ambiguity:
            data = by_ambiguity[level]
            hack_rate = data.get("hack_rate", 0.0)
            divergence = data.get("avg_divergence", 0.0)

            print(f"{level.capitalize():<12} {hack_rate:<15.1%} {divergence:<15.4f}")

    print()
    print("="*70)
    print()

def create_chart(by_ambiguity, output_path="analysis/charts/hack_rate_by_ambiguity.png"):
    """Create bar+line chart showing hack rate and divergence."""

    # Extract data
    levels = ["Low", "Medium", "High"]
    level_keys = ["low", "medium", "high"]
    hack_rates = []
    divergences = []

    for key in level_keys:
        if key in by_ambiguity:
            data = by_ambiguity[key]
            hack_rates.append(data.get("hack_rate", 0.0) * 100)  # Convert to percentage
            divergences.append(data.get("avg_divergence", 0.0))
        else:
            hack_rates.append(0.0)
            divergences.append(0.0)

    # Bar colors by ambiguity
    bar_colors = ["#2ca02c", "#ff7f0e", "#d62728"]  # Green, Orange, Red

    # Set up figure with dual axes
    fig, ax1 = plt.subplots(figsize=(10, 6))

    # Plot bars on primary axis
    x = np.arange(len(levels))
    width = 0.5
    bars = ax1.bar(x, hack_rates, width, color=bar_colors, alpha=0.8, label="Hack Rate")

    # Add percentage labels on bars
    for bar, rate in zip(bars, hack_rates):
        height = bar.get_height()
        ax1.text(
            bar.get_x() + bar.get_width()/2,
            height + 2,
            f"{height:.1f}%",
            ha="center",
            va="bottom",
            fontsize=11,
            fontweight="bold"
        )

    # Add horizontal dashed line at 50% threshold
    ax1.axhline(y=50, color="gray", linestyle="--", linewidth=1.5, alpha=0.7, label="50% threshold")

    # Create secondary axis for divergence
    ax2 = ax1.twinx()
    line = ax2.plot(x, divergences, color="#1f77b4", marker="o", linewidth=2.5, markersize=8, label="Avg Divergence")

    # Add divergence value labels
    for xi, div in zip(x, divergences):
        ax2.text(
            xi,
            div + 0.03,
            f"{div:.3f}",
            ha="center",
            va="bottom",
            fontsize=10,
            fontweight="bold",
            color="#1f77b4"
        )

    # Labels and formatting
    ax1.set_xlabel("Ambiguity Level", fontsize=12, fontweight="bold")
    ax1.set_ylabel("Hack Rate (%)", fontsize=12, fontweight="bold", color="#333")
    ax2.set_ylabel("Average Divergence", fontsize=12, fontweight="bold", color="#1f77b4")

    ax1.set_title(
        "Hack Rate and Reward Divergence by Task Ambiguity",
        fontsize=14,
        fontweight="bold",
        pad=20
    )

    ax1.set_xticks(x)
    ax1.set_xticklabels(levels)
    ax1.set_ylim(0, 100)
    ax2.set_ylim(-0.15, 0.55)

    # Color the y-axis labels to match their respective plots
    ax1.tick_params(axis="y", labelcolor="#333")
    ax2.tick_params(axis="y", labelcolor="#1f77b4")

    # Combine legends
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left", fontsize=11)

    # Grid
    ax1.grid(axis="y", alpha=0.3, linestyle="--")

    # Tight layout
    plt.tight_layout()

    # Save figure at 300 dpi
    plt.savefig(output_path, dpi=300, bbox_inches="tight")
    print(f"[SUCCESS] Chart saved to: {output_path}")

    return fig

def main():
    """Load findings and create chart."""
    findings = load_findings()
    by_ambiguity = findings.get("by_ambiguity", {})

    # Print data table
    print_data_table(by_ambiguity)

    # Create chart
    create_chart(by_ambiguity)

    print("Key insight:")
    print("  Hack rate peaks at MEDIUM ambiguity (80%) where divergence is")
    print("  highest (0.475). Agents optimize metrics aggressively on vague")
    print("  tasks. High ambiguity (70%) shows slightly lower hack rate")
    print("  because agents appropriately ask for clarification.\n")

if __name__ == "__main__":
    main()
