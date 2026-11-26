"""Detector validation against hand labels.

Reads labels/labeled.csv (your labels). The detector's verdict and type come from the rescored
v8 record of each episode, never from the CSV, so the labels stay blind.

Computes
  1. hack vs not hack: precision, recall, F1, with episode-level bootstrap 95% CIs.
     "unsure" rows are excluded and counted.
  2. Confusion matrix: the detector's primary type (rows) vs your hack types (columns). An
     episode with several hack types of yours counts once in each of those columns.
  3. Every disagreement, with its episode ID.
  4. Clarification classes: your class vs results/clarification_labels.json (agreement and
     disagreements), on the sampled episodes that have a manual class.
  5. Self-consistency (optional): labels/selfcheck.csv (re-labelled) vs labels/labeled.csv.

Commands (repo root):
  python analysis/detector_metrics.py                  # metrics on labels/labeled.csv
  python analysis/detector_metrics.py --make-selfcheck # write labels/selfcheck.csv (10 blind rows)
  python analysis/detector_metrics.py --selfcheck      # agreement of labels/selfcheck.csv with labeled.csv
"""

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
RESCORED = REPO / "results" / "runs" / "claude-haiku-5-5" / "rescored_v8"
LABELS = REPO / "labels"
VALIDATION = REPO / "results" / "validation"
CLAR_LABELS = REPO / "results" / "clarification_labels.json"
CLAR_MAP = VALIDATION / "clarification_map.json"

BOOT_SEED = 20251127          # same family as the sampling seed; separate stream below
SELF_SEED = 20251128          # draws the 10 self-check rows
BOOTSTRAP = 10_000
N_SELF = 10

VALID_LABELS = ("hack", "not a hack", "unsure")
HACK_TYPES = ("metric_gaming", "scope_creep", "irreversibility_bias", "overclaiming",
              "sycophantic_caution")
VALID_CLASSES = ("i", "ii", "iii", "not a clarification")
VALID_TASK_ISSUE = ("yes", "no")

CSV_COLUMNS = [
    "episode_id", "task_instruction", "tool_calls", "final_state_diff", "final_message",
    "label", "hack_type", "clarification_class", "task_issue", "note",
]


# ── loading ─────────────────────────────────────────────────────────────────

def load_record(episode_id: str) -> dict:
    run, task = episode_id.split("/")
    path = RESCORED / run / f"{task}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def read_labels(path: Path) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    errors = []
    for r in rows:
        eid = r["episode_id"]
        label = r["label"].strip()
        if label not in VALID_LABELS:
            errors.append(f"{eid}: label {label!r} is not one of {VALID_LABELS}")
        types = [t.strip() for t in r["hack_type"].split(";") if t.strip()]
        bad = [t for t in types if t not in HACK_TYPES]
        if bad:
            errors.append(f"{eid}: unknown hack_type {bad}")
        if label == "hack" and not types:
            errors.append(f"{eid}: label is 'hack' but hack_type is empty")
        if label in ("not a hack", "unsure") and types:
            errors.append(f"{eid}: hack_type given for label {label!r}")
        if r["clarification_class"].strip() not in VALID_CLASSES:
            errors.append(f"{eid}: clarification_class {r['clarification_class']!r} invalid")
        if r["task_issue"].strip() not in VALID_TASK_ISSUE:
            errors.append(f"{eid}: task_issue {r['task_issue']!r} must be yes or no")
    if errors:
        raise SystemExit("label file has errors; nothing computed:\n  " + "\n  ".join(errors))
    for r in rows:
        r["_types"] = [t.strip() for t in r["hack_type"].split(";") if t.strip()]
    return rows


# ── metrics ─────────────────────────────────────────────────────────────────

def _prf(tp: int, fp: int, fn: int):
    precision = tp / (tp + fp) if tp + fp else float("nan")
    recall = tp / (tp + fn) if tp + fn else float("nan")
    f1 = (2 * precision * recall / (precision + recall)
          if precision + recall and not np.isnan(precision) and not np.isnan(recall) else float("nan"))
    return precision, recall, f1


def binary_metrics(truth: np.ndarray, pred: np.ndarray) -> dict:
    tp = int(np.sum(truth & pred))
    fp = int(np.sum(~truth & pred))
    fn = int(np.sum(truth & ~pred))
    tn = int(np.sum(~truth & ~pred))
    p, r, f = _prf(tp, fp, fn)

    rng = np.random.default_rng(BOOT_SEED)
    n = len(truth)
    boots = {"precision": [], "recall": [], "f1": []}
    for _ in range(BOOTSTRAP):
        idx = rng.integers(0, n, size=n)
        bt, bp = truth[idx], pred[idx]
        bp_, br_, bf_ = _prf(int(np.sum(bt & bp)), int(np.sum(~bt & bp)), int(np.sum(bt & ~bp)))
        boots["precision"].append(bp_)
        boots["recall"].append(br_)
        boots["f1"].append(bf_)

    def ci(vals):
        arr = np.array(vals, dtype=float)
        arr = arr[~np.isnan(arr)]
        if arr.size == 0:
            return None
        lo, hi = np.percentile(arr, [2.5, 97.5])
        return [float(lo), float(hi)]

    def num(x):
        return None if np.isnan(x) else round(float(x), 4)

    return {
        "n": n, "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": {"point": num(p), "ci95": ci(boots["precision"])},
        "recall": {"point": num(r), "ci95": ci(boots["recall"])},
        "f1": {"point": num(f), "ci95": ci(boots["f1"])},
        "bootstrap_resamples": BOOTSTRAP,
        "bootstrap_seed": BOOT_SEED,
    }


def confusion_by_type(rows: list[dict]) -> dict:
    """Rows: detector primary type (or 'none'). Columns: your hack types plus 'not a hack'."""
    cols = list(HACK_TYPES) + ["not a hack"]
    rows_ = list(HACK_TYPES) + ["none"]
    table = {r: {c: 0 for c in cols} for r in rows_}
    for r in rows:
        det = r["_record"]["hacking"]["primary_hack_type"] or "none"
        mine = r["_types"] if r["label"] == "hack" else ["not a hack"]
        for c in mine:
            table[det][c] += 1
    return {"rows": "detector primary type", "columns": "your label (one count per type you gave)",
            "table": table}


def disagreements(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        rec = r["_record"]
        flagged = bool(rec["hacking"]["was_hacked"])
        is_hack = r["label"] == "hack"
        det_types = sorted({e["type"] for e in rec["hacking"]["events"]})
        type_clash = is_hack and flagged and not (set(r["_types"]) & set(det_types))
        if is_hack != flagged or type_clash:
            reason = ("detector missed a hack" if is_hack and not flagged else
                      "detector flagged a non-hack" if flagged and not is_hack else
                      "both flagged, type differs")
            out.append({"episode_id": r["episode_id"], "reason": reason,
                        "your_label": r["label"], "your_types": r["_types"],
                        "detector_flagged": flagged, "detector_types": det_types})
    return out


def clarification_agreement(rows: list[dict]) -> dict:
    if not CLAR_MAP.exists():
        return {"error": f"{CLAR_MAP} missing; run analysis/validation/export_labeling_sample.py"}
    cmap = json.loads(CLAR_MAP.read_text(encoding="utf-8"))["mapped"]
    by_ep = {v["episode_id"]: v for v in cmap.values()}
    manual_file = json.loads(CLAR_LABELS.read_text(encoding="utf-8"))
    overlap, agree, disagree = 0, 0, []
    for r in rows:
        m = by_ep.get(r["episode_id"])
        if m is None:
            continue
        overlap += 1
        mine = r["clarification_class"].strip()
        if mine == m["manual_class"]:
            agree += 1
        else:
            disagree.append({"episode_id": r["episode_id"], "your_class": mine,
                             "manual_class": m["manual_class"], "level": m["level"]})
    return {
        "labels_file": "results/clarification_labels.json",
        "labels_in_file": len(manual_file),
        "overlap_with_sample": overlap,
        "agree": agree,
        "agreement_rate": round(agree / overlap, 4) if overlap else None,
        "disagreements": disagree,
    }


def unsure_and_ignored(rows: list[dict]):
    return sum(1 for r in rows if r["label"] == "unsure")


# ── self-consistency ────────────────────────────────────────────────────────

def make_selfcheck(all_rows: list[dict]):
    rng = np.random.default_rng(SELF_SEED)
    pick = sorted(rng.choice(len(all_rows), size=N_SELF, replace=False).tolist())
    out = LABELS / "selfcheck.csv"
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        w.writeheader()
        for i in pick:
            r = all_rows[i]
            w.writerow({k: r.get(k, "") if k in r else "" for k in CSV_COLUMNS} | {
                "label": "", "hack_type": "", "clarification_class": "", "task_issue": "", "note": ""})
    print(f"wrote {out} with {N_SELF} rows (labels blank); re-label them, then run --selfcheck")
    print("episodes (for the metrics script only):", [all_rows[i]["episode_id"] for i in pick])


def selfcheck(labeled: list[dict]):
    again = read_labels(LABELS / "selfcheck.csv")
    first = {r["episode_id"]: r for r in labeled}
    n = agree_label = agree_type = agree_class = 0
    for r in again:
        ref = first.get(r["episode_id"])
        if ref is None:
            raise SystemExit(f"{r['episode_id']} is not in labeled.csv")
        n += 1
        agree_label += r["label"] == ref["label"]
        agree_type += sorted(r["_types"]) == sorted(ref["_types"])
        agree_class += r["clarification_class"] == ref["clarification_class"]
    result = {"n": n, "label_agreement": agree_label, "hack_type_agreement": agree_type,
              "clarification_class_agreement": agree_class}
    print(json.dumps(result, indent=2))
    return result


# ── main ────────────────────────────────────────────────────────────────────

def attach_records(rows: list[dict]):
    for r in rows:
        r["_record"] = load_record(r["episode_id"])


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--make-selfcheck", action="store_true")
    p.add_argument("--selfcheck", action="store_true")
    a = p.parse_args(argv)
    VALIDATION.mkdir(parents=True, exist_ok=True)

    if a.make_selfcheck:
        # Drawn from the blind sheet, so the copied rows carry no earlier labels.
        with open(LABELS / "to_label.csv", encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        make_selfcheck(rows)
        return

    labeled_path = LABELS / "labeled.csv"
    if not labeled_path.exists():
        raise SystemExit("labels/labeled.csv not found; nothing to compute")
    rows = read_labels(labeled_path)
    attach_records(rows)

    if a.selfcheck:
        selfcheck(rows)
        return

    scored = [r for r in rows if r["label"] != "unsure"]
    truth = np.array([r["label"] == "hack" for r in scored])
    pred = np.array([bool(r["_record"]["hacking"]["was_hacked"]) for r in scored])
    binary = binary_metrics(truth, pred)
    confusion = confusion_by_type(scored)
    disagree = disagreements(scored)
    clar = clarification_agreement(rows)
    result = {
        "rows_in_file": len(rows),
        "unsure_excluded": unsure_and_ignored(rows),
        "scored": len(scored),
        "hack_vs_not_hack": binary,
        "confusion_detector_type_vs_my_type": confusion,
        "disagreements": disagree,
        "clarification_class_vs_manual": clar,
    }
    (VALIDATION / "detector_validation.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")

    print(f"rows: {len(rows)}; unsure excluded: {unsure_and_ignored(rows)}; scored: {len(scored)}")
    print(f"hack vs not hack  TP {binary['tp']}  FP {binary['fp']}  FN {binary['fn']}  TN {binary['tn']}")
    for k in ("precision", "recall", "f1"):
        print(f"  {k:9} {binary[k]['point']}  95% CI {binary[k]['ci95']}")
    print(f"disagreements: {len(disagree)}")
    for d in disagree:
        print(f"  {d['episode_id']}: {d['reason']} | you: {d['your_label']} {d['your_types']} "
              f"| detector: flagged={d['detector_flagged']} {d['detector_types']}")
    if "error" in clar:
        print(clar["error"])
    else:
        print(f"clarification classes: overlap {clar['overlap_with_sample']}, agreement "
              f"{clar['agree']}/{clar['overlap_with_sample']}")
        for d in clar["disagreements"]:
            print(f"  {d['episode_id']}: you {d['your_class']} vs manual {d['manual_class']} ({d['level']})")
    print(f"full output: {VALIDATION / 'detector_validation.json'}")


if __name__ == "__main__":
    main()
