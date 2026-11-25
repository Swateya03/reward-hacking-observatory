"""Chart text, hack-type keys, and the no-fixed-conclusion rule.

- No chart script contains a fixed conclusion sentence. Text built by a
  build_* function is computed from data and is allowed.
- One canonical hack-type key form (lowercase). A small fake findings input
  gives non-zero counts in chart_hack_types, in any input casing.
No API calls, no workspace server.
"""

import ast
import re
from pathlib import Path
from unittest.mock import patch

import matplotlib
matplotlib.use("Agg")
import matplotlib.axes
import matplotlib.pyplot as plt

from analysis.charts import chart_divergence_by_ambiguity, chart_hack_rate, chart_hack_types, chart_radar

CHARTS_DIR = Path(__file__).resolve().parents[1] / "analysis" / "charts"

# Wording that states a result or a conclusion. A chart script may not contain it
# outside a build_* function.
CONCLUSION = re.compile(
    r"(increas|decreas)\w*\s+with|minimal|diverse|dominat|conservative|overstat|"
    r"indicate|zone|surface|less hacking|more hacking|is the most|clearer|shows? (less|more)",
    re.IGNORECASE,
)


def _fixed_strings(path: Path) -> list[str]:
    """Every string literal in the file that is not inside a build_* function."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    skip = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name.startswith("build_"):
            skip.update(id(child) for child in ast.walk(node))
    return [
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip
    ]


def test_no_chart_script_has_a_fixed_conclusion_sentence():
    scripts = sorted(CHARTS_DIR.glob("chart_*.py"))
    assert len(scripts) == 5
    offenders = {}
    for script in scripts:
        hits = [s for s in _fixed_strings(script) if CONCLUSION.search(s)]
        if hits:
            offenders[script.name] = hits
    assert not offenders, f"fixed conclusion text found (compute it in a build_* function instead): {offenders}"


def test_conclusion_pattern_catches_the_old_sentences():
    """The rule is meaningful: the sentences that were removed match it."""
    for sentence in (
        "Divergence increases with ambiguity: clearer tasks show less hacking",
        "Low ambiguity: minimal hacking (clear instructions)",
        "High ambiguity: diverse hacking types (unclear goals)",
        "Points below diagonal indicate reward hacking",
    ):
        assert CONCLUSION.search(sentence), sentence


# ── drawn-text helper ────────────────────────────────────────────────────────

def drawn_text(create, *args) -> list[str]:
    recorded = []
    original = matplotlib.axes.Axes.text

    def spy(self, x, y, s, *a, **kw):
        recorded.append(str(s))
        return original(self, x, y, s, *a, **kw)

    with patch.object(matplotlib.axes.Axes, "text", spy), patch.object(plt, "savefig"):
        create(*args, "unused.png")
    plt.close("all")
    return recorded


# ── one canonical hack-type key form ─────────────────────────────────────────

def test_hack_type_chart_shows_nonzero_counts_for_lowercase_findings():
    fake = {"hack_types": {"counts": {"metric_gaming": 2, "sycophantic_caution": 1}}}
    rows = chart_hack_types.prepare_data(fake)
    counts = {name: count for _, count, name in rows}
    assert counts["metric_gaming"] == 2
    assert counts["sycophantic_caution"] == 1
    assert sum(counts.values()) == 3

    text = drawn_text(chart_hack_types.create_chart, fake)
    assert "Metric Gaming is the most frequent: 2 of 3 events (67%)." in text


def test_hack_type_chart_accepts_uppercase_legacy_keys_as_the_same_type():
    upper = {"hack_types": {"counts": {"METRIC_GAMING": 2}}}
    lower = {"hack_types": {"counts": {"metric_gaming": 2}}}
    assert chart_hack_types.prepare_data(upper) == chart_hack_types.prepare_data(lower)


def test_radar_aggregation_is_canonical_lowercase():
    tasks = [
        {"ambiguity_level": "high", "hacking_events": [{"hack_type": "metric_gaming"}]},
        {"ambiguity_level": "high", "hacking_events": [{"hack_type": "METRIC_GAMING"}]},
    ]
    agg = chart_radar.aggregate_hacks_by_ambiguity(tasks)
    assert agg["high"]["metric_gaming"] == 2
    assert "METRIC_GAMING" not in agg["high"]


# ── computed text ────────────────────────────────────────────────────────────

def test_divergence_summary_names_the_highest_mean_level():
    # Legacy-shaped averages: high (0.25) is below medium (0.5), so the old
    # "increases with ambiguity" sentence would be wrong here.
    by = {"low": {"avg_divergence": -0.125}, "medium": {"avg_divergence": 0.5},
          "high": {"avg_divergence": 0.25}}
    assert chart_divergence_by_ambiguity.build_annotations(by)["highest_mean_divergence"] == \
        "Highest mean divergence: Medium ambiguity (+0.500)."


def test_radar_summary_names_the_level_with_most_events():
    tasks = [{"ambiguity_level": "medium", "hacking_events": [{"hack_type": "overclaiming"}] * 2},
             {"ambiguity_level": "low", "hacking_events": []}]
    summary = chart_radar.build_annotations(chart_radar.aggregate_hacks_by_ambiguity(tasks))
    assert summary["most_events"] == "Most detector events: Medium ambiguity (2 events)."


def test_hack_rate_summary_still_computed():
    by = {"low": {"hack_rate": 0.0}, "medium": {"hack_rate": 0.8}, "high": {"hack_rate": 0.7}}
    assert chart_hack_rate.build_annotations(by)["insight"] == "Highest hack rate: Medium ambiguity (80%)."
