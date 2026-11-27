"""analysis/detector_fresh.py: the exact upper bound and the stratified estimator."""

import pytest

from analysis.detector_fresh import CELLS, _cp_upper, stratified


def test_clopper_pearson_upper_bound_for_zero_of_five():
    # 1 - 0.025 ** (1/5), the exact one-sided bound for 0 successes in 5 trials
    assert _cp_upper(0, 5) == pytest.approx(1 - 0.025 ** 0.2, abs=1e-6)


def test_clopper_pearson_upper_bound_is_one_when_all_succeed():
    assert _cp_upper(5, 5) == 1.0


def test_stratified_totals_match_a_hand_calculation():
    # two design cells as the only ones with rows; the others get one row each (not hacks, not flagged)
    pool = {c: 1 for c in CELLS}
    pool[("high", True)] = 10
    pool[("low", False)] = 30
    rows = []
    for c in CELLS:
        rows.append({"level": c[0], "v2_flag": c[1], "is_hack": False, "f": False})
    rows[CELLS.index(("high", True))] = {"level": "high", "v2_flag": True, "is_hack": True, "f": True}
    rows.append({"level": "high", "v2_flag": True, "is_hack": False, "f": True})
    rows.append({"level": "low", "v2_flag": False, "is_hack": False, "f": False})
    # cell (high, True): sample 2 rows, 1 hack, both flagged -> p=0.5, pool share 10
    # cell (low, False): sample 2 rows, 0 hacks -> p=0, pool share 30
    # other cells: 1 row each, no hacks, not flagged
    est = stratified(rows, "f", pool)
    assert est["hacks_in_pool"]["point"] == pytest.approx(10 * 0.5, abs=1e-4)
    assert est["flagged_in_pool"]["point"] == pytest.approx(10 * 1.0, abs=1e-4)
    assert est["precision"]["point"] == pytest.approx(5 / 10, abs=1e-4)
    assert est["pool_episodes"] == 10 + 30 + 4
