"""Chart error bars and computed labels, from an aggregate with known values. No API, no server."""

from pathlib import Path

import pytest

from analysis.charts import chart_aggregate_ci as ch
from hacking.detector import CHECKS


def _block(point, lo, hi, **extra):
    d = {"point": point, "ci95": [lo, hi], "defined_episodes": 40, "na_episodes": 0, "na_tasks": 0}
    d.update(extra)
    return d


def _agg():
    level = {
        "hack_rate": _block(0.5, 0.35, 0.65),
        **{f"check_{c}": _block(0.25, 0.1, 0.4) for c in CHECKS},
        "naive": _block(0.8, 0.7, 0.9),
        "robust": _block(0.6, 0.5, 0.7),
        "divergence": _block(0.2, 0.1, 0.3),
    }
    return {
        "runs": [f"run_{i:02d}" for i in range(1, 11)],
        "tasks": 30,
        "settings": {"bootstrap_resamples": 10000},
        "levels": {"low": level, "medium": level, "high": level},
    }


def test_error_bar_lengths_are_distances_to_the_interval():
    point, yerr = ch._err(_block(0.5, 0.35, 0.65))
    assert point == 0.5
    assert yerr == pytest.approx([0.15, 0.15])


def test_undefined_entries_have_no_error_bar():
    assert ch._err(None) is None
    assert ch._err({"point": None, "ci95": None}) is None


def test_subtitle_is_computed_from_the_file():
    labels = ch.build_labels(_agg())
    assert labels["subtitle"] == \
        "10 runs x 30 tasks. Error bars: 95% task-cluster bootstrap CI (10,000 resamples)."


def test_charts_are_written_with_error_bars(tmp_path):
    agg = _agg()
    hack = ch.create_hack_rate_chart(agg, output_path=str(tmp_path / "h.png"))
    metrics = ch.create_metrics_chart(agg, output_path=str(tmp_path / "m.png"))
    assert Path(hack).exists() and Path(hack).stat().st_size > 0
    assert Path(metrics).exists() and Path(metrics).stat().st_size > 0
