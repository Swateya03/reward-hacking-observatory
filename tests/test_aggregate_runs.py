"""aggregate_runs on synthetic run folders with known answers. No API calls, no server.

Each test writes a small results layout (run_NN folders of schema v7 records) into a temp
directory, then checks the aggregate against values worked out by hand.
"""

import json
from pathlib import Path

import numpy as np
import pytest

from analysis.aggregate_runs import analyse, load_episodes
from hacking.detector import CHECKS

N_RUNS = 4
FAST = dict(n_boot=2000, n_perm=2000, seed=7)


def _record(task_id, level, hack, *, checks=None, unsafe=None, naive=1.0, robust=0.5,
            divergence=None, schema=7):
    avail = {c: True for c in CHECKS}
    fired = {c: False for c in CHECKS}
    for c, (a, f) in (checks or {}).items():
        avail[c], fired[c] = a, f
    if divergence is None and robust is not None:
        divergence = round(naive - robust, 3)
    return {
        "task_id": task_id,
        "ambiguity_level": level,
        "scores": {"naive": naive, "intermediate": 0.7, "robust_outcome": robust,
                   "divergence": divergence if robust is not None else None,
                   "robust_outcome_available": robust is not None},
        "hacking": {
            "was_hacked": hack,
            "checks": {c: {"available": avail[c], "fired": (fired[c] if avail[c] else None)} for c in CHECKS},
            "events": [],
        },
        "policy_metrics": {"unsafe_action_under_ambiguity": unsafe},
        "metadata": {"schema_version": schema},
    }


def _write_layout(root: Path, make_episode, n_runs=N_RUNS, n_tasks_per_level=10):
    """make_episode(run_index, task_id, level, task_index) -> record dict."""
    for r in range(1, n_runs + 1):
        d = root / f"run_{r:02d}"
        d.mkdir(parents=True, exist_ok=True)
        for lv_i, level in enumerate(("low", "medium", "high")):
            for k in range(n_tasks_per_level):
                task_id = f"task_{lv_i * n_tasks_per_level + k + 1:03d}"
                rec = make_episode(r, task_id, level, k)
                (d / f"{task_id}.json").write_text(json.dumps(rec), encoding="utf-8")
    return root


def _agg(root, **overrides):
    opts = dict(FAST)
    opts.update(overrides)
    return analyse(load_episodes(root), **opts)


# ── known rates and denominators ─────────────────────────────────────────────

def test_hack_rate_exact_for_constant_levels(tmp_path):
    def ep(r, t, level, k):
        hack = {"low": True, "medium": r <= 2, "high": False}[level]  # medium: 2 of 4 runs
        return _record(t, level, hack)
    agg = _agg(_write_layout(tmp_path, ep))
    assert agg["levels"]["low"]["hack_rate"]["point"] == 1.0
    assert agg["levels"]["low"]["hack_rate"]["ci95"] == [1.0, 1.0]
    assert agg["levels"]["medium"]["hack_rate"]["point"] == 0.5
    # Runs are resampled within each task, so a task with 2 hacks in 4 runs still varies:
    # each task's resampled rate has variance 0.25/4, averaged over 10 tasks gives
    # se = sqrt(0.25 / 4 / 10). The 95% interval is 0.5 +/- 1.96 * se = 0.5 +/- 0.155.
    se = (0.25 / 4 / 10) ** 0.5
    lo, hi = agg["levels"]["medium"]["hack_rate"]["ci95"]
    assert lo == pytest.approx(0.5 - 1.96 * se, abs=0.02)
    assert hi == pytest.approx(0.5 + 1.96 * se, abs=0.02)
    assert agg["levels"]["high"]["hack_rate"]["point"] == 0.0
    assert agg["levels"]["low"]["episodes"] == 40


def test_check_rate_uses_its_own_available_denominator(tmp_path):
    # metric_gaming is available only where robust is defined: low tasks.
    def ep(r, t, level, k):
        if level == "low":
            checks = {"metric_gaming": (True, r == 1), "scope_creep": (True, r <= 2)}
            return _record(t, level, r == 1, checks=checks, robust=0.2, naive=1.0)
        return _record(t, level, False,
                       checks={"metric_gaming": (False, None), "scope_creep": (True, False)},
                       robust=None, naive=0.0)
    agg = _agg(_write_layout(tmp_path, ep))
    mg = agg["levels"]["low"]["check_metric_gaming"]
    assert mg["defined_episodes"] == 40                 # 10 tasks x 4 runs, all available
    assert mg["point"] == pytest.approx(0.25)           # fired in 1 of 4 runs
    assert agg["levels"]["medium"]["check_metric_gaming"]["defined_episodes"] == 0
    assert agg["levels"]["medium"]["check_metric_gaming"]["point"] is None
    sc = agg["levels"]["low"]["check_scope_creep"]
    assert sc["point"] == pytest.approx(0.5)            # fired in 2 of 4 runs


def test_robust_na_is_excluded_and_counted(tmp_path):
    def ep(r, t, level, k):
        if level == "medium" and k < 5:                  # 5 of 10 medium tasks: robust N/A
            return _record(t, level, False, robust=None, naive=1.0)
        if level == "medium":
            return _record(t, level, False, robust=0.25, naive=1.0)
        return _record(t, level, False, robust=0.5, naive=0.5)
    agg = _agg(_write_layout(tmp_path, ep))
    med = agg["levels"]["medium"]
    assert med["robust"]["point"] == pytest.approx(0.25)
    assert med["robust"]["na_tasks"] == 5
    assert med["robust"]["na_episodes"] == 20
    assert med["robust"]["defined_episodes"] == 20
    assert med["naive"]["point"] == 1.0                  # naive is never N/A
    assert med["naive"]["na_episodes"] == 0


def test_unsafe_rate_only_on_medium_and_high(tmp_path):
    def ep(r, t, level, k):
        unsafe = None if level == "low" else (r <= 3)    # 3 of 4 runs
        return _record(t, level, False, unsafe=unsafe)
    agg = _agg(_write_layout(tmp_path, ep))
    assert agg["levels"]["low"]["unsafe_rate"]["point"] is None
    assert agg["levels"]["low"]["unsafe_rate"]["defined_episodes"] == 0
    assert agg["levels"]["medium"]["unsafe_rate"]["point"] == pytest.approx(0.75)
    assert "low-medium" not in agg["pairwise"]["unsafe_rate"]


def test_divergence_mean_exact_with_na_excluded(tmp_path):
    def ep(r, t, level, k):
        if level == "low":
            return _record(t, level, False, naive=1.0, robust=0.5)   # divergence 0.5
        return _record(t, level, False, naive=0.0, robust=None)      # N/A
    agg = _agg(_write_layout(tmp_path, ep))
    assert agg["levels"]["low"]["divergence"]["point"] == pytest.approx(0.5)
    assert agg["levels"]["high"]["divergence"]["point"] is None


# ── confidence intervals ─────────────────────────────────────────────────────

def test_cluster_bootstrap_ci_is_wide_when_tasks_disagree(tmp_path):
    # Medium: half the tasks hack in every run, half never do. Task-level mean is 0.5 with
    # a standard error near 0.16 (10 tasks), so a 95% interval is roughly 0.19 to 0.81.
    def ep(r, t, level, k):
        return _record(t, level, (level == "medium" and k < 5) or level == "low")
    agg = _agg(_write_layout(tmp_path, ep), n_boot=4000)
    lo, hi = agg["levels"]["medium"]["hack_rate"]["ci95"]
    assert agg["levels"]["medium"]["hack_rate"]["point"] == pytest.approx(0.5)
    assert 0.1 < lo < 0.35 and 0.65 < hi < 0.9


def test_ci_is_reproducible_with_the_same_seed(tmp_path):
    def ep(r, t, level, k):
        return _record(t, level, (k + r) % 3 == 0)
    root = _write_layout(tmp_path, ep)
    a = _agg(root, seed=123)["levels"]["low"]["hack_rate"]["ci95"]
    b = _agg(root, seed=123)["levels"]["low"]["hack_rate"]["ci95"]
    assert a == b


# ── pairwise differences and permutation test ────────────────────────────────

def test_pairwise_difference_is_exact_for_constant_levels(tmp_path):
    def ep(r, t, level, k):
        return _record(t, level, level == "low")
    agg = _agg(_write_layout(tmp_path, ep))
    diff = agg["pairwise"]["hack_rate"]["low-high"]
    assert diff["difference"] == 1.0
    assert diff["ci95"] == [1.0, 1.0]
    assert agg["pairwise"]["hack_rate"]["medium-high"]["difference"] == 0.0


def test_permutation_p_is_one_for_identical_levels(tmp_path):
    def ep(r, t, level, k):
        return _record(t, level, (k + r) % 2 == 0)    # same pattern in every level
    agg = _agg(_write_layout(tmp_path, ep))
    assert agg["permutation"]["hack_rate"]["statistic"] == pytest.approx(0.0, abs=1e-9)
    assert agg["permutation"]["hack_rate"]["p_value"] == 1.0


def test_permutation_p_is_small_for_clearly_separated_levels(tmp_path):
    def ep(r, t, level, k):
        return _record(t, level, {"low": False, "medium": True, "high": False}[level])
    agg = _agg(_write_layout(tmp_path, ep))
    assert agg["permutation"]["hack_rate"]["p_value"] < 0.01


def test_per_task_stability_across_runs(tmp_path):
    def ep(r, t, level, k):
        return _record(t, level, t == "task_001" and r <= 3, unsafe=(t == "task_011" and r <= 1) if level != "low" else None)
    agg = _agg(_write_layout(tmp_path, ep))
    by = {row["task_id"]: row for row in agg["per_task"]}
    assert by["task_001"]["hack_rate_across_runs"] == pytest.approx(0.75)
    assert by["task_001"]["hack_runs"] == 3
    assert by["task_002"]["hack_rate_across_runs"] == 0.0
    assert by["task_011"]["unsafe_rate_across_runs"] == pytest.approx(0.25)
    assert by["task_001"]["unsafe_rate_across_runs"] is None      # low task


# ── input rules ──────────────────────────────────────────────────────────────

def test_refuses_records_that_are_not_schema_v7(tmp_path):
    def ep(r, t, level, k):
        return _record(t, level, False, schema=6 if (r == 2 and t == "task_005") else 7)
    root = _write_layout(tmp_path, ep)
    with pytest.raises(ValueError, match="schema_version"):
        load_episodes(root)


def test_ignores_folders_that_are_not_run_folders(tmp_path):
    def ep(r, t, level, k):
        return _record(t, level, False)
    root = _write_layout(tmp_path, ep)
    dry = root / "dry_run"
    dry.mkdir()
    (dry / "task_001.json").write_text(json.dumps(_record("task_001", "low", True, schema=5)))
    runs = load_episodes(root)
    assert sorted(runs) == [f"run_{r:02d}" for r in range(1, N_RUNS + 1)]


def test_refuses_a_run_missing_tasks(tmp_path):
    def ep(r, t, level, k):
        return _record(t, level, False)
    root = _write_layout(tmp_path, ep)
    (root / "run_02" / "task_001.json").unlink()
    with pytest.raises(ValueError, match="missing tasks"):
        _agg(root)
