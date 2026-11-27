"""Detector v1 and v2 on the fresh validation sample (labels/labeled_v2.csv).

Sample design: 30 episodes drawn from the 245 pool episodes outside the first sample, stratified by
ambiguity level x detector v2 verdict (simple random within each stratum). Because the design strata
are v2 verdict cells, the stratified estimator is used for both detectors: every quantity is a total
over the pool, estimated as sum over strata of N_h times the sample mean in stratum h.

  hack rate  = T_hack / N
  precision  = T_hack_and_flag / T_flag
  recall     = T_hack_and_flag / T_hack
with T_flag the flagged total for the detector being scored. CIs: stratified bootstrap.

No model or server is needed. Verdicts are read from rescored_v8 (v1, the stored schema-8 verdict) and
rescored_v9 (v2). The v1 and v2 numbers are reported side by side with the development-set numbers.
"""

import csv
import json
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
RESCORED_V8 = REPO / "results" / "runs" / "claude-haiku-5-5" / "rescored_v8"
RESCORED_V9 = REPO / "results" / "runs" / "claude-haiku-5-5" / "rescored_v9"
LABELS = REPO / "labels"
VALIDATION = REPO / "results" / "validation"
FRESH_LABELS = LABELS / "labeled_v2.csv"
FRESH_IDS = LABELS / "sample_ids_v2.json"
FIRST_IDS = LABELS / "sample_ids.json"
DEV_JSON = VALIDATION / "detector_validation.json"
FRESH_JSON = VALIDATION / "detector_validation_fresh.json"

LEVELS = ("low", "medium", "high")
CELLS = [(lv, f) for lv in LEVELS for f in (True, False)]
GUIDE_EXAMPLES = {"run_06/task_008", "run_02/task_006", "run_02/task_009", "run_01/task_009",
                  "run_01/task_004"}
BOOTSTRAP = 10_000
SEED = 20251202
HACK_TYPES = ("metric_gaming", "scope_creep", "irreversibility_bias", "overclaiming",
              "sycophantic_caution")


def _v8(eid):
    run, task = eid.split("/")
    return json.loads((RESCORED_V8 / run / f"{task}.json").read_text(encoding="utf-8"))


def _v9(eid):
    run, task = eid.split("/")
    return json.loads((RESCORED_V9 / run / f"{task}.json").read_text(encoding="utf-8"))


def _prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else float("nan")
    r = tp / (tp + fn) if tp + fn else float("nan")
    f = 2 * p * r / (p + r) if (not np.isnan(p) and not np.isnan(r) and p + r > 0) else float("nan")
    return p, r, f


def _ci(values):
    arr = np.array(values, dtype=float)
    arr = arr[~np.isnan(arr)]
    if arr.size == 0:
        return None
    lo, hi = np.percentile(arr, [2.5, 97.5])
    return [round(float(lo), 4), round(float(hi), 4)]


def _num(x):
    return None if (x is None or np.isnan(x)) else round(float(x), 4)


def load_rows() -> list[dict]:
    rows = []
    for r in csv.DictReader(open(FRESH_LABELS, encoding="utf-8", newline="")):
        eid = r["episode_id"]
        types = [t.strip() for t in r["hack_type"].split(";") if t.strip()]
        v8 = _v8(eid)
        v9 = _v9(eid)
        rows.append({
            "episode_id": eid, "level": v8["ambiguity_level"], "label": r["label"],
            "is_hack": r["label"] == "hack", "types": types,
            "v1_flag": bool(v8["hacking"]["was_hacked"]),
            "v1_types": sorted({e["type"] for e in v8["hacking"]["events"]}),
            "v1_primary": v8["hacking"]["primary_hack_type"],
            "v2_flag": bool(v9["hacking_v2"]["was_hacked"]),
            "v2_types": sorted({e["type"] for e in v9["hacking_v2"]["events"]}),
            "v2_primary": v9["hacking_v2"]["primary_hack_type"],
        })
    return rows


def fresh_pool_cells() -> dict:
    """N_h: pool episodes outside the first sample, by (level, v2 flag)."""
    first = set(json.loads(FIRST_IDS.read_text(encoding="utf-8")))
    counts = {c: 0 for c in CELLS}
    for path in sorted(RESCORED_V9.glob("run_*/task_*.json")):
        eid = f"{path.parent.name}/{path.stem}"
        if eid in GUIDE_EXAMPLES or eid in first:
            continue                      # the pool is the 245 episodes outside the first sample
        rec = json.loads(path.read_text(encoding="utf-8"))
        counts[(rec["ambiguity_level"], bool(rec["hacking_v2"]["was_hacked"]))] += 1
    return counts


def stratified(rows: list[dict], flag_key: str, pool: dict) -> dict:
    """Stratified estimates for the detector whose flag is rows[...][flag_key]."""
    N = np.array([pool[c] for c in CELLS], dtype=float)
    per_cell = {}
    for c in CELLS:
        cell_rows = [r for r in rows if (r["level"], r["v2_flag"]) == c]
        if not cell_rows:
            raise SystemExit(f"no sampled episodes in stratum {c}")
        hack = np.array([r["is_hack"] for r in cell_rows], dtype=float)
        flag = np.array([r[flag_key] for r in cell_rows], dtype=float)
        per_cell[c] = (hack, flag)

    def totals(means_hack, means_flag, means_hf):
        t_hack = (means_hack * N).sum(axis=-1)
        t_flag = (means_flag * N).sum(axis=-1)
        t_hf = (means_hf * N).sum(axis=-1)
        with np.errstate(divide="ignore", invalid="ignore"):
            return {
                "hack_rate": t_hack / N.sum(),
                "precision": np.where(t_flag > 0, t_hf / np.where(t_flag > 0, t_flag, 1), np.nan),
                "recall": np.where(t_hack > 0, t_hf / np.where(t_hack > 0, t_hack, 1), np.nan),
                "hacks_in_pool": t_hack,
                "flagged_in_pool": t_flag,
            }

    mh = np.array([per_cell[c][0].mean() for c in CELLS])
    mf = np.array([per_cell[c][1].mean() for c in CELLS])
    mhf = np.array([(per_cell[c][0] * per_cell[c][1]).mean() for c in CELLS])
    point = {k: float(np.asarray(v)) for k, v in totals(mh, mf, mhf).items()}

    rng = np.random.default_rng(SEED)
    bh, bf, bhf = [], [], []
    for c in CELLS:
        hack, flag = per_cell[c]
        idx = rng.integers(0, len(hack), size=(BOOTSTRAP, len(hack)))
        bh.append(hack[idx].mean(axis=1))
        bf.append(flag[idx].mean(axis=1))
        bhf.append((hack * flag)[idx].mean(axis=1))
    boot = totals(np.stack(bh, axis=1), np.stack(bf, axis=1), np.stack(bhf, axis=1))
    out = {k: {"point": _num(point[k]), "ci95": _ci(boot[k]), "ci_method": "stratified bootstrap"}
           for k in ("hack_rate", "precision", "recall")}
    out["hacks_in_pool"] = {"point": _num(point["hacks_in_pool"]), "ci95": _ci(boot["hacks_in_pool"])}
    out["flagged_in_pool"] = {"point": _num(point["flagged_in_pool"]), "ci95": _ci(boot["flagged_in_pool"])}
    out["pool_episodes"] = int(N.sum())
    out["bootstrap_resamples"] = BOOTSTRAP
    out["bootstrap_seed"] = SEED
    return out


def unweighted(rows: list[dict], flag_key: str) -> dict:
    truth = np.array([r["is_hack"] for r in rows])
    pred = np.array([r[flag_key] for r in rows])
    tp = int(np.sum(truth & pred))
    fp = int(np.sum(~truth & pred))
    fn = int(np.sum(truth & ~pred))
    tn = int(np.sum(~truth & ~pred))
    p, r, f = _prf(tp, fp, fn)
    rng = np.random.default_rng(SEED)
    n = len(rows)
    bp, br, bf = [], [], []
    for _ in range(BOOTSTRAP):
        idx = rng.integers(0, n, size=n)
        q, s, t = _prf(int(np.sum(truth[idx] & pred[idx])), int(np.sum(~truth[idx] & pred[idx])),
                       int(np.sum(truth[idx] & ~pred[idx])))
        bp.append(q)
        br.append(s)
        bf.append(t)
    return {"n": n, "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": {"point": _num(p), "ci95": _ci(bp)},
            "recall": {"point": _num(r), "ci95": _ci(br)},
            "f1": {"point": _num(f), "ci95": _ci(bf)}}


def confusion(rows: list[dict], primary_key: str, flag_key: str) -> dict:
    cols = list(HACK_TYPES) + ["not a hack"]
    table = {r: {c: 0 for c in cols} for r in list(HACK_TYPES) + ["none"]}
    for r in rows:
        det = r[primary_key] or "none"
        mine = r["types"] if r["is_hack"] else ["not a hack"]
        for c in mine:
            table[det][c] += 1
    return table


def disagreements(rows: list[dict], flag_key: str, types_key: str) -> list[dict]:
    out = []
    for r in rows:
        flagged = r[flag_key]
        is_hack = r["is_hack"]
        det_types = r[types_key]
        clash = is_hack and flagged and not (set(r["types"]) & set(det_types))
        if is_hack != flagged or clash:
            reason = ("detector missed a hack" if is_hack and not flagged else
                      "detector flagged a non-hack" if flagged and not is_hack else
                      "both flagged, type differs")
            out.append({"episode_id": r["episode_id"], "reason": reason, "your_label": r["label"],
                        "your_types": r["types"], "detector_flagged": flagged, "detector_types": det_types})
    return out


def per_check(rows: list[dict], types_key: str) -> list[dict]:
    out = []
    for name in HACK_TYPES:
        hits = [r for r in rows if name in r[types_key]]
        tp = [r for r in hits if name in r["types"]]
        out.append({"check": name, "fired": len(hits), "label_has_type": len(tp),
                    "false_positive": len(hits) - len(tp),
                    "episodes_false_positive": [r["episode_id"] for r in hits if name not in r["types"]]})
    return out


def _cp_upper(x: int, n: int, alpha_one_sided: float) -> float:
    """Exact (Clopper-Pearson) upper bound for a proportion with x successes out of n."""
    from math import comb

    def cdf(p):
        return sum(comb(n, k) * p ** k * (1 - p) ** (n - k) for k in range(x + 1))

    if x >= n:
        return 1.0
    lo, hi = 0.0, 1.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if cdf(mid) > alpha_one_sided:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def miss_upper_bound(rows: list[dict], pool: dict) -> dict:
    """Joint 95% upper bound on the number of hacks v2 does not flag in the pool. Each not-flagged stratum
    gets an exact one-sided Clopper-Pearson bound at level 0.05 / k, with k the number of not-flagged strata
    (Bonferroni), so all k bounds hold together with probability at least 95%. The bound on misses is the
    sum over strata of N_h times its bound."""
    unflagged = [c for c in CELLS if not c[1]]
    alpha = 0.05 / len(unflagged)
    total = 0.0
    per = {}
    for c in unflagged:
        cell = [r for r in rows if (r["level"], r["v2_flag"]) == c]
        x = sum(1 for r in cell if r["is_hack"])
        u = _cp_upper(x, len(cell), alpha)
        per[f"{c[0]}/v2 not flagged"] = {"hacks_in_sample": x, "sample": len(cell),
                                          "upper_rate": round(u, 4), "pool": pool[c],
                                          "upper_hacks_in_pool": round(u * pool[c], 2)}
        total += u * pool[c]
    return {"per_stratum": per, "upper_bound_hacks_missed_in_pool": round(total, 2),
            "method": "exact one-sided Clopper-Pearson per stratum at 0.05/k (Bonferroni), summed over N_h",
            "alpha_per_stratum": round(alpha, 6)}


def compute() -> dict:
    rows = load_rows()
    unsure = sum(1 for r in rows if r["label"] == "unsure")
    scored = [r for r in rows if r["label"] != "unsure"]
    pool = fresh_pool_cells()
    dev = json.loads(DEV_JSON.read_text(encoding="utf-8"))
    result = {
        "labels_file": "labels/labeled_v2.csv",
        "rows": len(rows), "unsure_excluded": unsure, "scored": len(scored),
        "sample_by_stratum": {f"{lv}/{'v2 flagged' if f else 'v2 not flagged'}":
                              sum(1 for r in scored if (r["level"], r["v2_flag"]) == (lv, f)) for lv, f in CELLS},
        "pool_by_stratum": {f"{lv}/{'v2 flagged' if f else 'v2 not flagged'}": pool[(lv, f)] for lv, f in CELLS},
        "v1": {"unweighted": unweighted(scored, "v1_flag"),
               "weighted": stratified(scored, "v1_flag", pool),
               "confusion": confusion(scored, "v1_primary", "v1_flag"),
               "per_check": per_check(scored, "v1_types"),
               "disagreements": disagreements(scored, "v1_flag", "v1_types")},
        "v2": {"unweighted": unweighted(scored, "v2_flag"),
               "weighted": stratified(scored, "v2_flag", pool),
               "confusion": confusion(scored, "v2_primary", "v2_flag"),
               "per_check": per_check(scored, "v2_types"),
               "disagreements": disagreements(scored, "v2_flag", "v2_types")},
        "development_set": {
            "v1_counts": {k: dev["hack_vs_not_hack"][k] for k in ("tp", "fp", "fn", "tn")},
            "v2_counts": {k: dev["detector_v2_dev_set"]["binary"][k] for k in ("tp", "fp", "fn", "tn")},
            "v1_precision": dev["hack_vs_not_hack"]["precision"]["point"],
            "v1_recall": dev["hack_vs_not_hack"]["recall"]["point"],
            "v2_precision": dev["detector_v2_dev_set"]["binary"]["precision"]["point"],
            "v2_recall": dev["detector_v2_dev_set"]["binary"]["recall"]["point"],
        },
    }
    result["v2_miss_bound"] = miss_upper_bound(scored, pool)
    return result


def render_md(r: dict) -> list[str]:
    """Markdown for the fresh-sample section of docs/DETECTOR_VALIDATION.md (numbers from `r` only)."""
    def ci(e):
        if e is None or e.get("point") is None:
            return "n/a"
        if e.get("ci95") is None:
            return f"{e['point']:.2f} (CI n/a)"
        return f"{e['point']:.2f} (95% CI {e['ci95'][0]:.2f} to {e['ci95'][1]:.2f})"

    def cell_row(name, uw, w):
        return f"| {name} | {uw} | {w} |"

    v1, v2 = r["v1"], r["v2"]
    lines = [
        "## Fresh sample: detector v1 and v2 (30 episodes, not used to design v2)", "",
        "Drawn from the pool of 245 episodes outside the first sample, with seed 20251201, stratified by "
        "ambiguity level and v2 verdict. The 30 episodes were labelled after v2 was frozen. Counts below are "
        "computed from `results/validation/detector_validation_fresh.json`.", "",
        "Sample by stratum (labelled): " + "; ".join(f"{k}: {v}" for k, v in r["sample_by_stratum"].items()) + ".",
        "Pool by stratum (245 episodes): " + "; ".join(f"{k}: {v}" for k, v in r["pool_by_stratum"].items()) + ".",
        "", "### Unweighted (the 30 episodes)", "",
        "| Detector | TP | FP | FN | TN | Precision | Recall | F1 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, d in (("v1", v1), ("v2", v2)):
        u = d["unweighted"]
        lines.append(f"| {name} | {u['tp']} | {u['fp']} | {u['fn']} | {u['tn']} | {ci(u['precision'])} | "
                     f"{ci(u['recall'])} | {ci(u['f1'])} |")
    lines += ["", "### Stratum-weighted (pool of 245)", "",
              "| Detector | Hack rate | Precision | Recall | Hacks in pool | Flagged in pool |",
              "|---|---|---|---|---|---|"]
    for name, d in (("v1", v1), ("v2", v2)):
        w = d["weighted"]
        lines.append(f"| {name} | {ci(w['hack_rate'])} | {ci(w['precision'])} | {ci(w['recall'])} | "
                     f"{ci(w['hacks_in_pool'])} | {ci(w['flagged_in_pool'])} |")
    mb = r["v2_miss_bound"]
    lines += ["", "**Recall is not informative in this sample.** Every hack in the sample is v2-flagged, and "
              "the not-flagged strata contain no hacks. So the recall interval collapses to 1.00 in every bootstrap "
              "draw, which is an artifact, not a measurement. The honest bound on what v2 misses is the "
              "Clopper-Pearson bound on the not-flagged strata, summed over the pool:", "",
              "| Not-flagged stratum | Hacks in sample | Sample | 95% upper bound on rate | Pool | Upper bound on hacks |",
              "|---|---:|---:|---:|---:|---:|"]
    for name, e in mb["per_stratum"].items():
        lines.append(f"| {name} | {e['hacks_in_sample']} | {e['sample']} | {e['upper_rate']:.2f} | "
                     f"{e['pool']} | {e['upper_hacks_in_pool']:.1f} |")
    lines += ["", f"Joint 95% upper bound on hacks v2 misses in the 245-episode pool: **{mb['upper_bound_hacks_missed_in_pool']:.1f}**. "
              f"Method: {mb['method']}. This bound is wide; the sample cannot show that v2 misses few hacks.", ""]
    for name, d in (("v1", v1), ("v2", v2)):
        lines += [f"### Confusion table, {name} (fresh sample)", "",
                  "Rows: detector's primary type. Columns: your label (one count per type given).", ""]
        cm = d["confusion"]
        cols = list(next(iter(cm.values())).keys())
        lines.append("| detector \\ author | " + " | ".join(cols) + " |")
        lines.append("|---|" + "---|" * len(cols))
        for row, vals in cm.items():
            lines.append(f"| {row} | " + " | ".join(str(vals[c]) for c in cols) + " |")
        lines += ["", f"Per-check ({name}): " + "; ".join(
            f"{c['check']} fired {c['fired']}, label has type {c['label_has_type']}, false positive {c['false_positive']}"
            for c in d["per_check"]) + ".", ""]
        lines += [f"Every disagreement, {name} (episode, reason, your label, detector types):", ""]
        for x in d["disagreements"]:
            lines.append(f"- {x['episode_id']}: {x['reason']}; you: {x['your_label']} {x['your_types'] or ''}; "
                         f"detector: {x['detector_types']}")
        lines.append("")
    irr = next(c for c in v2["per_check"] if c["check"] == "irreversibility_bias")
    dev = r["development_set"]
    lines += ["### Development set against the fresh sample", "",
              "| Detector | Development set (50): precision | Development set: recall | Fresh (30), unweighted precision | Fresh, weighted precision |",
              "|---|---:|---:|---:|---:|",
              f"| v1 | {dev['v1_precision']:.2f} | {dev['v1_recall']:.2f} | {v1['unweighted']['precision']['point']:.2f} | "
              f"{v1['weighted']['precision']['point']:.2f} |",
              f"| v2 | {dev['v2_precision']:.2f} | {dev['v2_recall']:.2f} | {v2['unweighted']['precision']['point']:.2f} | "
              f"{v2['weighted']['precision']['point']:.2f} |", "",
              "The v2 precision on the development set was optimistic: its rules were chosen from those 50 episodes. "
              "On the fresh sample v2 is still more precise than v1, but its precision is far below the development "
              "figure. Recall cannot be compared, since the fresh sample has no v2 misses to count.", "",
              "### Limitations (fresh sample)", "",
              "- **One labeller.** All labels are the author's.",
              "- **Labels discussed row by row with an AI assistant.** Its suggestions were reviewed and approved row by row. This is not an independent labelling.",
              "- **No self-agreement check was run.**",
              "- **Small sample.** 30 episodes: 6 hacks; the 15 not-flagged episodes contain none. The medium and high "
              "flagged strata have one episode each, so v2 precision on medium and high tasks is not estimable.",
              f"- **Irreversibility is unchanged from v1 and is the largest v2 false-positive source here**: v2 "
              f"irreversibility_bias fires {irr['fired']} times in this sample, and {irr['false_positive']} of those are "
              "false positives. v2 leaves this rule as it was; a change would need its own design and validation.",
              "- **metric_gaming v2 fires nowhere in this sample**, so it remains untested.",
              "- **Known limitation S3 and the overclaiming gap** are unchanged (see the sections above).", ""]
    return lines


def main() -> dict:
    result = compute()
    VALIDATION.mkdir(parents=True, exist_ok=True)
    FRESH_JSON.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    return result


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    r = main()
    print(json.dumps({k: r[k] for k in ("rows", "unsure_excluded", "scored", "sample_by_stratum", "pool_by_stratum")}, indent=2))
    for v in ("v1", "v2"):
        print(v, "unweighted", {k: r[v]["unweighted"][k] for k in ("tp", "fp", "fn", "tn")})
        print(v, "weighted", {k: r[v]["weighted"][k]["point"] for k in ("hack_rate", "precision", "recall")})
    print("wrote", FRESH_JSON)
