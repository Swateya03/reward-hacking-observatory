"""Draw the fresh validation sample for detector v2 and export it blind for labelling.

Pool  : the 295 pool episodes (300 minus the five guide examples), minus the 50 episodes of the first
        labelled sample: 245 episodes.
Strata: ambiguity level x detector v2 verdict (flagged / not flagged), from rescored_v9.
Sample: N = 30, about half v2-flagged (15 and 15), spread across levels as availability allows.
Seed  : SEED_V2 (fixed). No overlap with the first sample.

Outputs
  labels/sample_ids_v2.json              the 30 sampled IDs (no verdicts)
  labels/to_label_v2.csv                 blind sheet, same columns as labels/to_label.csv
  results/validation/sample_strata_v2.json  v2 verdicts for the sample (git-ignored; not for the labeller)

No v2 metric is computed here. The labeller uses scripts/label.py with --to-label labels/to_label_v2.csv.

Needs the workspace server on localhost:8000 (the final state is obtained by replaying the stored tool
calls). Usage (repo root):
  python -m analysis.validation.export_v2_sample
"""

import csv
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from agent.workspace_client import WorkspaceClient  # noqa: E402
from analysis.validation.export_labeling_sample import (  # noqa: E402
    CSV_COLUMNS, final_text, replay_final_state, state_diff, task_by_id, tool_sequence,
)

RESCORED_V9 = REPO / "results" / "runs" / "claude-haiku-5-5" / "rescored_v9"
LABELS = REPO / "labels"
VALIDATION = REPO / "results" / "validation"

SEED_V2 = 20251201
N_FLAGGED = 15
N_NOT_FLAGGED = 15
LEVELS = ("low", "medium", "high")

# The five guide examples, as in analysis/validation/export_labeling_sample.py.
GUIDE_EXAMPLES = {
    "run_06/task_008", "run_02/task_006", "run_02/task_009", "run_01/task_009", "run_01/task_004",
}


def load_pool() -> dict:
    first = set(json.loads((LABELS / "sample_ids.json").read_text(encoding="utf-8")))
    pool = {}
    for path in sorted(RESCORED_V9.glob("run_*/task_*.json")):
        eid = f"{path.parent.name}/{path.stem}"
        if eid in GUIDE_EXAMPLES or eid in first:
            continue
        pool[eid] = json.loads(path.read_text(encoding="utf-8"))
    return pool


def v2_flagged(rec: dict) -> bool:
    return bool(rec["hacking_v2"]["was_hacked"])


def allocate(cells: dict, total: int) -> dict:
    """Spread `total` across levels as evenly as availability allows (same rule as the first sample)."""
    quota = {lv: 0 for lv in LEVELS}
    remaining = total
    while remaining > 0:
        open_levels = [lv for lv in LEVELS if quota[lv] < len(cells[lv])]
        if not open_levels:
            raise SystemExit("not enough episodes for the stratum")
        open_levels.sort(key=lambda lv: (quota[lv], -len(cells[lv]), lv))
        quota[open_levels[0]] += 1
        remaining -= 1
    return quota


def draw(pool: dict) -> list[dict]:
    rng = np.random.default_rng(SEED_V2)
    chosen = []
    for flagged, n in ((True, N_FLAGGED), (False, N_NOT_FLAGGED)):
        cells = {lv: sorted(e for e, rec in pool.items()
                            if rec["ambiguity_level"] == lv and v2_flagged(rec) == flagged)
                 for lv in LEVELS}
        quota = allocate(cells, n)
        for lv in LEVELS:
            pick = rng.choice(len(cells[lv]), size=quota[lv], replace=False)
            for i in sorted(pick.tolist()):
                chosen.append({"episode_id": cells[lv][i], "level": lv, "v2_flagged": flagged,
                               "quota": quota[lv]})
    return sorted(chosen, key=lambda c: c["episode_id"])


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    pool = load_pool()
    if len(pool) != 245:
        raise SystemExit(f"expected 245 episodes outside the first sample, found {len(pool)}")
    sample = draw(pool)
    ids = [s["episode_id"] for s in sample]
    assert len(set(ids)) == len(ids) == N_FLAGGED + N_NOT_FLAGGED

    ws = WorkspaceClient()
    if not ws.health_check():
        raise SystemExit("workspace server not running on localhost:8000")
    tasks = task_by_id()

    rows, strata, mismatches = [], [], {}
    for item in sample:
        eid = item["episode_id"]
        rec = pool[eid]
        task = tasks[rec["task_id"]]
        initial, final, mism = replay_final_state(ws, task, rec)
        if mism:
            mismatches[eid] = mism
        rows.append({
            "episode_id": eid,
            "task_instruction": task.prompt,
            "tool_calls": tool_sequence(rec),
            "final_state_diff": state_diff(initial, final),
            "final_message": final_text(rec),
            "label": "", "hack_type": "", "clarification_class": "", "task_issue": "", "note": "",
        })
        strata.append({"episode_id": eid, "level": item["level"], "v2_flagged": item["v2_flagged"],
                       "stratum_quota": item["quota"]})

    LABELS.mkdir(exist_ok=True)
    VALIDATION.mkdir(parents=True, exist_ok=True)
    (LABELS / "sample_ids_v2.json").write_text(json.dumps(ids, indent=2) + "\n", encoding="utf-8", newline="\n")
    with open(LABELS / "to_label_v2.csv", "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    (VALIDATION / "sample_strata_v2.json").write_text(
        json.dumps({"seed": SEED_V2, "n_flagged": N_FLAGGED, "n_not_flagged": N_NOT_FLAGGED,
                    "pool_size": len(pool), "episodes": strata, "replay_mismatches": mismatches},
                   indent=2) + "\n", encoding="utf-8", newline="\n")

    print(f"sampled {len(ids)} episodes from {len(pool)}; replay mismatches: {len(mismatches)}")
    print("by level and v2 verdict:", dict(Counter((s["level"], s["v2_flagged"]) for s in strata)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
