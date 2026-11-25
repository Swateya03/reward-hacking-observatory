"""Charts with 95% CI error bars, read from the aggregate file (analysis/aggregate_runs.py).

Reads results/aggregate_<model>.json. Draws:
  hack_rate_ci.png   hack rate and each check's rate, by ambiguity level
  metrics_ci.png     mean naive, mean robust outcome, mean divergence, by level
Error bars are the task-cluster bootstrap 95% CI. Text on the charts is computed from the
file (titles, counts, the interval note). No conclusion sentences are written here.
"""

import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib import rcParams

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hacking.detector import CHECKS  # noqa: E402

rcParams["font.family"] = "DejaVu Sans"
rcParams["font.size"] = 11
rcParams["axes.spines.top"] = False
rcParams["axes.spines.right"] = False
rcParams["figure.facecolor"] = "#0d1117"
rcParams["axes.facecolor"] = "#161b22"
rcParams["axes.labelcolor"] = "#e6edf3"
rcParams["xtick.color"] = "#8b949e"
rcParams["ytick.color"] = "#8b949e"
rcParams["text.color"] = "#e6edf3"
rcParams["grid.color"] = "#30363d"
rcParams["axes.edgecolor"] = "#30363d"

LEVELS = ("low", "medium", "high")
LEVEL_COLORS = {"low": "#3fb950", "medium": "#d29922", "high": "#f85149"}
DEFAULT_AGG = Path("results/aggregate_claude-haiku-5-5.json")


def load_aggregate(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _err(entry: dict):
    """(point, [lower_err, upper_err]) for matplotlib errorbar, or None if undefined."""
    if entry is None or entry.get("point") is None or entry.get("ci95") is None:
        return None
    p = entry["point"]
    lo, hi = entry["ci95"]
    return p, [max(0.0, p - lo), max(0.0, hi - p)]


def build_labels(agg: dict) -> dict:
    """Text computed from the aggregate (testable)."""
    n_runs = len(agg["runs"])
    return {
        "subtitle": (f"{n_runs} runs x {agg['tasks']} tasks. Error bars: 95% task-cluster bootstrap CI "
                     f"({agg['settings']['bootstrap_resamples']:,} resamples)."),
    }


def _errorbar_panel(ax, labels, entries_by_level, title, ylabel, ylim=None):
    x = np.arange(len(labels))
    for i, lv in enumerate(LEVELS):
        pts = []
        for j, lab in enumerate(labels):
            e = _err(entries_by_level.get(lv, {}).get(lab))
            if e is None:
                continue
            p, yerr = e
            ax.errorbar(j + (i - 1) * 0.22, p, yerr=np.array(yerr).reshape(2, 1), fmt="o",
                        color=LEVEL_COLORS[lv], ecolor=LEVEL_COLORS[lv], capsize=4, markersize=7,
                        label=lv.capitalize() if j == 0 else None)
    ax.set_xticks(x)
    ax.set_xticklabels([lab.replace("_", " ") for lab in labels])
    ax.set_title(title, fontsize=12, fontweight="bold", color="#e6edf3", pad=12)
    ax.set_ylabel(ylabel)
    if ylim:
        ax.set_ylim(*ylim)
    ax.grid(axis="y", alpha=0.15, linestyle="--", color="#30363d")
    ax.legend(loc="upper right", fontsize=9, framealpha=0.9)


def create_hack_rate_chart(agg: dict, output_path="analysis/charts/hack_rate_ci.png"):
    labels = ["hack_rate"] + [f"check_{c}" for c in CHECKS]
    entries = {lv: agg["levels"][lv] for lv in LEVELS if lv in agg["levels"]}
    fig, ax = plt.subplots(figsize=(12, 6.5), facecolor="#0d1117")
    ax.set_facecolor("#161b22")
    _errorbar_panel(ax, labels, entries, "Hack rate and per-check rates by ambiguity level",
                    "Rate (fired / available episodes)", ylim=(-0.05, 1.05))
    fig.text(0.5, 0.01, build_labels(agg)["subtitle"], ha="center", fontsize=9, color="#8b949e", style="italic")
    plt.tight_layout(rect=(0, 0.03, 1, 1))
    plt.savefig(output_path, dpi=200, facecolor="#0d1117")
    plt.close(fig)
    return output_path


def create_metrics_chart(agg: dict, output_path="analysis/charts/metrics_ci.png"):
    labels = ["naive", "robust", "divergence"]
    entries = {lv: agg["levels"][lv] for lv in LEVELS if lv in agg["levels"]}
    fig, ax = plt.subplots(figsize=(11, 6), facecolor="#0d1117")
    ax.set_facecolor("#161b22")
    _errorbar_panel(ax, labels, entries, "Mean naive, robust outcome and divergence by ambiguity level",
                    "Mean score", ylim=(-1.1, 1.2))
    ax.axhline(0.0, color="#8b949e", linewidth=1)
    fig.text(0.5, 0.01, build_labels(agg)["subtitle"], ha="center", fontsize=9, color="#8b949e", style="italic")
    plt.tight_layout(rect=(0, 0.03, 1, 1))
    plt.savefig(output_path, dpi=200, facecolor="#0d1117")
    plt.close(fig)
    return output_path


def main(argv=None):
    path = Path(argv[0]) if argv else DEFAULT_AGG
    if not path.exists():
        print(f"[ERROR] {path} not found. Run analysis/aggregate_runs.py first.")
        sys.exit(1)
    agg = load_aggregate(path)
    print(create_hack_rate_chart(agg))
    print(create_metrics_chart(agg))


if __name__ == "__main__":
    main(sys.argv[1:])
