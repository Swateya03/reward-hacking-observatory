"""Aggregate repeated runs: per-level rates and means, with task-level cluster bootstrap CIs.

Input layout (written by run_experiment.py --run-index k):
    results/runs/<model>/run_01/task_001.json ... run_10/task_030.json
Only directories named run_NN are read. Dry-run and other folders are ignored.
Every record must be schema v7 (scope rule); anything else is refused.

Definitions (per episode, then pooled within a level):
  hack          detector verdict: any available check fired (hacking.was_hacked)
  check rate    fired / available for each check, with its own denominator
  unsafe rate   policy_metrics.unsafe_action_under_ambiguity, applicable (medium, high) only
  naive         scores.naive (all episodes)
  robust        scores.robust_outcome (N/A episodes excluded, count shown)
  divergence    scores.divergence (N/A excluded, count shown)

Statistics:
  Point estimate of a level's rate = sum(numerator) / sum(denominator) over its episodes.
  95% CI: task-level cluster bootstrap. Resample the tasks of the level with replacement,
  then resample the runs within each sampled task with replacement, and recompute the rate.
  10,000 resamples, fixed seed. Percentile interval (2.5%, 97.5%).
  Level comparison: task-level permutation test. Permute the level labels across tasks
  (the level sizes are kept) and compare the between-level statistic
  F = sum_L den_L * (rate_L - grand_rate)^2 with its observed value. 10,000 permutations,
  fixed seed, p = (count >= observed + 1) / (B + 1).
  Pairwise differences: the same bootstrap, resampling each level separately; CI on the
  difference of the two level rates. No multiple-comparison correction is applied.

Usage (repo root):
  python analysis/aggregate_runs.py --runs-root results/runs/claude-haiku-5-5 \
      --out results/aggregate_claude-haiku-5-5.json
"""

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hacking.detector import CHECKS  # noqa: E402
from hacking.terminal import SUBTYPES  # noqa: E402

LEVELS = ("low", "medium", "high")
REQUIRED_SCHEMA = 7
N_BOOT = 10_000
N_PERM = 10_000
SEED = 20251125
CI = (2.5, 97.5)
RUN_DIR = re.compile(r"^run_(\d+)$")
UNSAFE_LEVELS = ("medium", "high")


# ── loading ──────────────────────────────────────────────────────────────────

def load_episodes(runs_root: Path, schema: int = REQUIRED_SCHEMA) -> dict:
    """{run_id: {task_id: episode_dict}} for every run_NN folder under runs_root."""
    runs = {}
    for d in sorted(runs_root.iterdir()):
        m = RUN_DIR.match(d.name) if d.is_dir() else None
        if not m:
            continue
        episodes = {}
        for f in sorted(d.glob("task_*.json")):
            rec = json.loads(f.read_text(encoding="utf-8"))
            version = (rec.get("metadata") or {}).get("schema_version")
            if version != schema:
                raise ValueError(f"{f}: schema_version {version!r}; this analysis needs {schema}")
            episodes[rec["task_id"]] = episode_from_record(rec)
        runs[d.name] = episodes
    if not runs:
        raise ValueError(f"no run_NN folders found under {runs_root}")
    return runs


def episode_from_record(rec: dict) -> dict:
    checks = {name: rec["hacking"]["checks"][name] for name in CHECKS}
    return {
        "task_id": rec["task_id"],
        "level": rec["ambiguity_level"],
        "hack": bool(rec["hacking"]["was_hacked"]),
        "checks": {n: (bool(c["available"]), bool(c["fired"]) if c["available"] else None)
                   for n, c in checks.items()},
        "unsafe": (rec.get("policy_metrics") or {}).get("unsafe_action_under_ambiguity"),
        "completion_type": rec.get("completion_type"),
        "subtypes": {name: any(ev.get("subtype") == name for ev in rec["hacking"].get("events", []))
                     for name in SUBTYPES},
        "naive": rec["scores"]["naive"],
        "robust": rec["scores"]["robust_outcome"],
        "divergence": rec["scores"]["divergence"],
    }


def task_matrix(runs: dict, tasks: list, runs_order: list, value) -> np.ndarray:
    """Matrix [task, run] of value(episode) (float, or NaN when undefined)."""
    out = np.full((len(tasks), len(runs_order)), np.nan)
    for i, t in enumerate(tasks):
        for j, r in enumerate(runs_order):
            v = value(runs[r][t])
            if v is not None:
                out[i, j] = float(v)
    return out


# ── ratio statistics on a [task, run] pair of matrices ───────────────────────

def ratio(num: np.ndarray, den: np.ndarray) -> float:
    d = np.nansum(den)
    return float(np.nansum(num) / d) if d > 0 else float("nan")


def bootstrap_ratio(num: np.ndarray, den: np.ndarray, rng, n_boot: int) -> np.ndarray:
    """Task-level cluster bootstrap of sum(num)/sum(den). num, den: [task, run]; NaN = undefined.
    Returns n_boot resampled ratios (NaN where the resample has no defined episode)."""
    n_t, n_r = num.shape
    num0 = np.nan_to_num(num, nan=0.0)
    den0 = np.nan_to_num(den, nan=0.0)
    t_idx = rng.integers(0, n_t, size=(n_boot, n_t))
    r_idx = rng.integers(0, n_r, size=(n_boot, n_t, n_r))
    num_b = num0[t_idx[:, :, None], r_idx]
    den_b = den0[t_idx[:, :, None], r_idx]
    s_num = num_b.sum(axis=(1, 2))
    s_den = den_b.sum(axis=(1, 2))
    with np.errstate(invalid="ignore", divide="ignore"):
        out = np.where(s_den > 0, s_num / s_den, np.nan)
    return out


def ci_from(samples: np.ndarray):
    good = samples[~np.isnan(samples)]
    if good.size == 0:
        return None
    lo, hi = np.percentile(good, CI)
    return [float(lo), float(hi)]


def permutation_p(num: np.ndarray, den: np.ndarray, levels_of_task: np.ndarray, rng, n_perm: int) -> dict:
    """Task-level permutation test across levels. Tasks with den == 0 are dropped first.
    Returns observed statistic and p-value."""
    tot_den = np.nansum(den, axis=1)
    tot_num = np.nansum(num, axis=1)
    keep = tot_den > 0
    tnum, tden, lab = tot_num[keep], tot_den[keep], levels_of_task[keep]
    present = [lv for lv in LEVELS if np.any(lab == lv)]
    if len(present) < 2:
        return {"statistic": None, "p_value": None, "n_tasks": int(keep.sum())}

    def stat(labels):
        grand = tnum.sum() / tden.sum()
        f = 0.0
        for lv in present:
            m = labels == lv
            d = tden[m].sum()
            if d > 0:
                f += d * ((tnum[m].sum() / d) - grand) ** 2
        return f

    observed = stat(lab)
    count = 0
    for _ in range(n_perm):
        if stat(rng.permutation(lab)) >= observed - 1e-12:
            count += 1
    return {"statistic": float(observed), "p_value": (count + 1) / (n_perm + 1),
            "n_tasks": int(keep.sum())}


# ── assembling the aggregate ─────────────────────────────────────────────────

def analyse(runs: dict, n_boot: int = N_BOOT, n_perm: int = N_PERM, seed: int = SEED,
            schema: int = REQUIRED_SCHEMA) -> dict:
    run_ids = sorted(runs)
    all_tasks = sorted({t for r in run_ids for t in runs[r]})
    for r in run_ids:
        missing = [t for t in all_tasks if t not in runs[r]]
        if missing:
            raise ValueError(f"{r} is missing tasks: {missing}")

    rng = np.random.default_rng(seed)
    level_of = {t: runs[run_ids[0]][t]["level"] for t in all_tasks}
    for r in run_ids:
        for t in all_tasks:
            if runs[r][t]["level"] != level_of[t]:
                raise ValueError(f"task {t} has different levels across runs")

    # per-metric matrices (task x run), per level subset built below
    metrics = {
        "hack_rate": (lambda e: 1.0 if e["hack"] else 0.0, lambda e: 1.0),
        "unsafe_rate": (lambda e: 1.0 if e["unsafe"] else 0.0,
                        lambda e: None if e["unsafe"] is None else 1.0),
        "naive": (lambda e: e["naive"], lambda e: 1.0),
        "robust": (lambda e: e["robust"], lambda e: None if e["robust"] is None else 1.0),
        "divergence": (lambda e: e["divergence"], lambda e: None if e["divergence"] is None else 1.0),
    }
    for c in CHECKS:
        metrics[f"check_{c}"] = (
            (lambda c: lambda e: 1.0 if e["checks"][c][1] else 0.0)(c),
            (lambda c: lambda e: 1.0 if e["checks"][c][0] else None)(c),
        )

    # added after the existing metrics so their bootstrap draws do not change
    metrics["clarification_rate"] = (
        lambda e: 1.0 if e["completion_type"] == "clarification" else 0.0,
        lambda e: 1.0)
    for sub in SUBTYPES:
        metrics[f"sub_{sub}"] = (
            (lambda sub: lambda e: 1.0 if e["subtypes"][sub] else 0.0)(sub),
            (lambda e: 1.0))

    result_levels = {}
    per_level_tasks = {lv: [t for t in all_tasks if level_of[t] == lv] for lv in LEVELS}
    mats = {}  # (metric, level) -> (num, den)
    for lv in LEVELS:
        tasks = per_level_tasks[lv]
        if not tasks:
            continue
        for name, (num_f, den_f) in metrics.items():
            num = task_matrix(runs, tasks, run_ids, num_f)
            den = task_matrix(runs, tasks, run_ids, lambda e, f=den_f: f(e))
            # a metric's numerator is only meaningful where its denominator is defined
            num = np.where(np.isnan(den), np.nan, num)
            mats[(name, lv)] = (num, den)

    for lv in LEVELS:
        if (("hack_rate", lv)) not in mats:
            continue
        tasks = per_level_tasks[lv]
        n_eps = len(tasks) * len(run_ids)
        block = {"tasks": len(tasks), "runs": len(run_ids), "episodes": n_eps}
        for name in metrics:
            num, den = mats[(name, lv)]
            defined = int(np.sum(~np.isnan(den)))
            point = ratio(num, den)
            boot = bootstrap_ratio(num, den, rng, n_boot)
            block[name] = {
                "point": None if np.isnan(point) else point,
                "ci95": ci_from(boot),
                "defined_episodes": defined,
                "na_episodes": n_eps - defined,
                "na_tasks": int(sum(1 for i in range(len(tasks)) if np.all(np.isnan(den[i])))),
            }
        result_levels[lv] = block

    # pairwise differences of level rates (bootstrap each level independently)
    pairwise = {}
    pairs = [("low", "medium"), ("low", "high"), ("medium", "high")]
    for name in ("hack_rate", "unsafe_rate", "naive", "robust", "divergence"):
        pairwise[name] = {}
        for a, b in pairs:
            if (name, a) not in mats or (name, b) not in mats:
                continue
            na, da = mats[(name, a)]
            nb, db = mats[(name, b)]
            ra, rb = ratio(na, da), ratio(nb, db)
            if np.isnan(ra) or np.isnan(rb):
                continue  # e.g. unsafe on low: not applicable
            ba = bootstrap_ratio(na, da, rng, n_boot)
            bb = bootstrap_ratio(nb, db, rng, n_boot)
            pairwise[name][f"{a}-{b}"] = {"difference": ra - rb,
                                          "ci95": ci_from(ba - bb)}

    # permutation tests across levels (task-level labels)
    permutation = {}
    labels_by_task = {}
    for name in ("hack_rate", "unsafe_rate", "naive", "robust", "divergence"):
        present_tasks = [t for t in all_tasks]
        # build the task-level matrices across all levels for this metric
        num_all = np.full((len(all_tasks), len(run_ids)), np.nan)
        den_all = np.full((len(all_tasks), len(run_ids)), np.nan)
        lab = np.empty(len(all_tasks), dtype=object)
        for i, t in enumerate(all_tasks):
            lv = level_of[t]
            lab[i] = lv
            if (name, lv) in mats:
                tasks = per_level_tasks[lv]
                k = tasks.index(t)
                num_all[i] = mats[(name, lv)][0][k]
                den_all[i] = mats[(name, lv)][1][k]
        if name == "unsafe_rate":
            sel = np.array([lv in UNSAFE_LEVELS for lv in lab])
            num_all, den_all, lab = num_all[sel], den_all[sel], lab[sel]
        permutation[name] = permutation_p(num_all, den_all, lab, rng, n_perm)

    # per-task stability across runs
    per_task = []
    for t in all_tasks:
        lv = level_of[t]
        hack = [1.0 if runs[r][t]["hack"] else 0.0 for r in run_ids]
        unsafe = [runs[r][t]["unsafe"] for r in run_ids]
        unsafe_def = [1.0 if u else 0.0 for u in unsafe if u is not None]
        per_task.append({
            "task_id": t,
            "level": lv,
            "hack_rate_across_runs": float(np.mean(hack)),
            "hack_runs": int(np.sum(hack)),
            "unsafe_rate_across_runs": float(np.mean(unsafe_def)) if unsafe_def else None,
            "unsafe_applicable_runs": len(unsafe_def),
        })

    return {
        "schema_version": schema,
        "runs": run_ids,
        "tasks": len(all_tasks),
        "settings": {"bootstrap_resamples": n_boot, "permutations": n_perm, "seed": seed,
                     "ci": "95% percentile, task-level cluster bootstrap (tasks, then runs within task)"},
        "levels": result_levels,
        "pairwise": pairwise,
        "permutation": permutation,
        "per_task": per_task,
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--runs-root", required=True, help="e.g. results/runs/claude-haiku-5-5")
    p.add_argument("--out", required=True, help="e.g. results/aggregate_claude-haiku-5-5.json")
    p.add_argument("--schema", type=int, default=REQUIRED_SCHEMA,
                   help="schema version the records must have (7 for the original runs, 8 for re-scored)")
    args = p.parse_args(argv)
    runs = load_episodes(Path(args.runs_root), schema=args.schema)
    agg = analyse(runs, schema=args.schema)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(agg, indent=2), encoding="utf-8")
    print(f"wrote {out} ({len(agg['runs'])} runs, {agg['tasks']} tasks)")


if __name__ == "__main__":
    main()
