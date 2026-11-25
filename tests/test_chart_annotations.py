"""Chart annotations come from the data, not from fixed text.

The tests spy on Axes.text while create_chart runs, so they check the text the
chart actually draws. savefig is patched, so no PNG is written. No API calls,
no workspace server.
"""

from unittest.mock import patch

import matplotlib
matplotlib.use("Agg")
import matplotlib.axes
import matplotlib.pyplot as plt
import pytest

from analysis.charts import chart_hack_rate, chart_hack_types


def drawn_text(create, data) -> list[str]:
    """Every string the chart draws via Axes.text, with savefig patched out."""
    recorded = []
    original = matplotlib.axes.Axes.text

    def spy(self, x, y, s, *args, **kwargs):
        recorded.append(str(s))
        return original(self, x, y, s, *args, **kwargs)

    with patch.object(matplotlib.axes.Axes, "text", spy), patch.object(plt, "savefig"):
        create(data, output_path="unused.png")
    plt.close("all")
    return recorded


def rate_data(low, medium, high):
    return {
        "by_ambiguity": {
            "low": {"hack_rate": low, "avg_divergence": 0.1},
            "medium": {"hack_rate": medium, "avg_divergence": 0.2},
            "high": {"hack_rate": high, "avg_divergence": 0.3},
        }
    }


def types_data(counts):
    return {"hack_types": {"counts": counts}}


# ── hack-rate chart ─────────────────────────────────────────────────────────

def test_hack_rate_insight_follows_the_data():
    before = drawn_text(lambda d, output_path: chart_hack_rate.create_chart(d["by_ambiguity"], output_path),
                        rate_data(0.0, 0.8, 0.7))
    after = drawn_text(lambda d, output_path: chart_hack_rate.create_chart(d["by_ambiguity"], output_path),
                       rate_data(0.1, 0.2, 0.9))
    assert "Highest hack rate: Medium ambiguity (80%)." in before
    assert "Highest hack rate: High ambiguity (90%)." in after
    assert before != after


def test_hack_rate_bar_labels_follow_the_data():
    text = drawn_text(lambda d, output_path: chart_hack_rate.create_chart(d["by_ambiguity"], output_path),
                      rate_data(0.25, 0.5, 1.0))
    assert {"25%", "50%", "100%"} <= set(text)


def test_hack_rate_no_fixed_result_text_is_drawn():
    for data in (rate_data(0.0, 0.8, 0.7), rate_data(0.1, 0.2, 0.9), rate_data(0.0, 0.0, 0.0)):
        text = drawn_text(lambda d, output_path: chart_hack_rate.create_chart(d["by_ambiguity"], output_path), data)
        assert "0%→100%" not in text
        assert not any("→" in s for s in text)


def test_hack_rate_threshold_is_labelled_as_a_threshold_and_is_constant():
    text_a = drawn_text(lambda d, output_path: chart_hack_rate.create_chart(d["by_ambiguity"], output_path),
                        rate_data(0.0, 0.8, 0.7))
    text_b = drawn_text(lambda d, output_path: chart_hack_rate.create_chart(d["by_ambiguity"], output_path),
                        rate_data(0.1, 0.2, 0.9))
    label = "Threshold 50% (design line)"
    assert label in text_a and label in text_b
    assert "50% threshold" not in text_a  # old wording: a bare number that reads like a result


def test_hack_rate_no_hacks_says_so():
    assert chart_hack_rate.build_annotations(rate_data(0.0, 0.0, 0.0)["by_ambiguity"])["insight"] == \
        "No hacks recorded at any ambiguity level."


def test_hack_rate_tie_names_both_levels():
    insight = chart_hack_rate.build_annotations(rate_data(0.0, 0.5, 0.5)["by_ambiguity"])["insight"]
    assert insight == "Highest hack rate: Medium and High ambiguity (50%)."


# ── hack-type chart ─────────────────────────────────────────────────────────

def test_hack_types_subtitle_follows_the_data():
    a = types_data({"SYCOPHANTIC_CAUTION": 7, "METRIC_GAMING": 2})
    b = types_data({"METRIC_GAMING": 9, "SYCOPHANTIC_CAUTION": 1})
    text_a = drawn_text(lambda d, output_path: chart_hack_types.create_chart(d, output_path), a)
    text_b = drawn_text(lambda d, output_path: chart_hack_types.create_chart(d, output_path), b)
    assert "Sycophantic Caution is the most frequent: 7 of 9 events (78%)." in text_a
    assert "Metric Gaming is the most frequent: 9 of 10 events (90%)." in text_b
    assert text_a != text_b


def test_hack_types_no_fixed_claim_is_drawn():
    for data in (types_data({"SYCOPHANTIC_CAUTION": 7, "METRIC_GAMING": 2}),
                 types_data({"METRIC_GAMING": 9})):
        text = drawn_text(lambda d, output_path: chart_hack_types.create_chart(d, output_path), data)
        assert not any("dominates" in s for s in text)


def test_hack_types_tie_is_named_as_a_tie():
    assert chart_hack_types.build_subtitle(types_data({"METRIC_GAMING": 3, "SCOPE_CREEP": 3})) == \
        "Tie for most frequent: Metric Gaming and Scope Creep, 3 of 6 events each (50%)."


def test_hack_types_no_events_says_so():
    assert chart_hack_types.build_subtitle(types_data({})) == "No hack events recorded."
