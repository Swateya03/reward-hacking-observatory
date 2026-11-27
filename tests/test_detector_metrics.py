"""analysis/detector_metrics.py: stratum-weighted estimates."""

import numpy as np
import pytest

from analysis.detector_metrics import CELLS, load_pool, weighted_estimates


def _uniform(value=1):
    return {c: value for c in CELLS}


def test_weighted_estimates_match_a_hand_calculation():
    pool = _uniform(1)
    pool[("high", True)] = 10          # flagged stratum: 10 episodes, half are hacks in the sample
    pool[("low", False)] = 30          # not flagged stratum: 30 episodes, none are hacks in the sample
    labels = {c: np.array([0]) for c in CELLS}
    labels[("high", True)] = np.array([1, 0])
    labels[("low", False)] = np.array([0, 0, 0])
    est = weighted_estimates(labels, pool)
    # hacks in pool = 10 * 0.5 = 5 of 44 episodes; flagged pool = 10 + 1 + 1 = 12
    assert est["hack_rate"]["point"] == pytest.approx(5 / 44, abs=1e-4)
    assert est["precision"]["point"] == pytest.approx(5 / 12, abs=1e-4)
    assert est["recall"]["point"] == pytest.approx(1.0, abs=1e-4)
    assert est["pool_episodes"] == 44


def test_confidence_interval_brackets_the_point_estimate():
    pool = _uniform(20)
    labels = {c: np.array([1, 0, 0, 0]) for c in CELLS}
    est = weighted_estimates(labels, pool)
    for key in ("hack_rate", "precision", "recall"):
        lo, hi = est[key]["ci95"]
        assert lo <= est[key]["point"] <= hi, key


def test_pool_is_the_295_episodes_without_the_guide_examples():
    pool = load_pool()
    assert len(pool) == 295
    assert "run_06/task_008" not in pool and "run_01/task_004" not in pool


def test_missing_stratum_is_an_error():
    labels = {c: np.array([1]) for c in CELLS}
    labels[("low", True)] = np.array([], dtype=float)
    with pytest.raises(SystemExit):
        weighted_estimates(labels, _uniform(5))
