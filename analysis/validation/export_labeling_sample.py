"""Draw the labelling sample and export the blind labelling sheet.

Source: results/runs/claude-haiku-5-5/rescored_v8/run_NN/task_NNN.json (schema v8, carries the
backfilled provenance). Makes no model calls. Needs the workspace server on localhost:8000,
because the final state of each sampled episode is obtained by replaying its tool calls.

Outputs
  labels/sample_ids.json            sampled episode IDs ("run_NN/task_NNN"), no verdicts
  labels/to_label.csv               blind sheet: no detector verdict, type or reward score
  results/validation/sample_strata.json   the strata and the detector verdict per sampled ID
                                    (for the metrics script only; not given to the labeller)
  results/validation/clarification_map.json   clarification_labels.json key -> episode ID

Usage (repo root):
  python -m analysis.validation.export_labeling_sample
"""

import csv
import json
import re
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from agent.workspace_client import WorkspaceClient  # noqa: E402
from analysis.rescore_v8 import replay  # noqa: E402
from tasks.task import TaskBank  # noqa: E402

RESCORED = REPO / "results" / "runs" / "claude-haiku-5-5" / "rescored_v8"
LABELS_DIR = REPO / "labels"
VALIDATION_DIR = REPO / "results" / "validation"
AUDIT_JSON = REPO / "results" / "clarification_audit.json"
CLAR_LABELS = REPO / "results" / "clarification_labels.json"

SEED = 20251127
PER_VERDICT = 25                      # 25 flagged + 25 not flagged = 50
LEVELS = ("low", "medium", "high")

# The five episodes used as examples in docs/LABELING_GUIDE.md. Excluded from the pool.
GUIDE_EXAMPLES = {
    "run_06/task_008",   # metric_gaming example
    "run_02/task_006",   # scope_creep example
    "run_02/task_009",   # irreversibility_bias example
    "run_01/task_009",   # sycophantic_caution example
    "run_01/task_004",   # not-a-hack example
}

CSV_COLUMNS = [
    "episode_id", "task_instruction", "tool_calls", "final_state_diff", "final_message",
    "label", "hack_type", "clarification_class", "task_issue", "note",
]

WATCHED_FIELDS = ["folder", "is_trashed", "is_deleted", "is_read", "title", "start_time",
                  "end_time", "attendees", "location", "sensitivity", "is_recurring"]


def episode_id(path: Path) -> str:
    return f"{path.parent.name}/{path.stem}"


def load_pool():
    pool = {}
    for f in sorted(RESCORED.glob("run_*/task_*.json")):
        rec = json.loads(f.read_text(encoding="utf-8"))
        eid = episode_id(f)
        pool[eid] = {"path": f, "record": rec}
    return pool


def draw_sample(pool: dict) -> list[dict]:
    """Stratified draw: PER_VERDICT flagged and PER_VERDICT not flagged, spread across levels."""
    rng = np.random.default_rng(SEED)
    chosen = []
    for flagged in (True, False):
        cells = {lv: sorted(e for e, v in pool.items()
                            if e not in GUIDE_EXAMPLES
                            and v["record"]["ambiguity_level"] == lv
                            and bool(v["record"]["hacking"]["was_hacked"]) == flagged)
                 for lv in LEVELS}
        # as even a split across levels as availability allows; leftover goes to the largest cells
        quota = {lv: 0 for lv in LEVELS}
        remaining = PER_VERDICT
        while remaining > 0:
            open_levels = [lv for lv in LEVELS if quota[lv] < len(cells[lv])]
            if not open_levels:
                raise RuntimeError("not enough episodes for the stratum")
            open_levels.sort(key=lambda lv: (quota[lv], -len(cells[lv]), lv))
            quota[open_levels[0]] += 1
            remaining -= 1
        for lv in LEVELS:
            pick = rng.choice(len(cells[lv]), size=quota[lv], replace=False)
            for i in sorted(pick.tolist()):
                chosen.append({"episode_id": cells[lv][i], "level": lv, "flagged": flagged,
                               "quota": quota[lv]})
    return sorted(chosen, key=lambda c: c["episode_id"])


def detector_types(rec: dict) -> list[str]:
    return sorted({e["type"] for e in rec["hacking"]["events"]})


def task_by_id() -> dict:
    return {t.id: t for t in TaskBank(str(REPO / "tasks" / "task_bank.json")).get_all()}


def final_text(rec: dict) -> str:
    for step in reversed(rec["trajectory"]):
        if step.get("reasoning_before"):
            return step["reasoning_before"].strip()
    return ""


def tool_sequence(rec: dict) -> str:
    lines = []
    n = 0
    for step in rec["trajectory"]:
        if step["type"] != "tool_call":
            continue
        n += 1
        args = json.dumps(step.get("arguments") or {}, ensure_ascii=False)
        res = step.get("result") or {}
        ok = "error" not in res and res.get("success") is not False
        status = "ok" if ok else "error"
        lines.append(f"{n}. {step['tool']}({args}) -> {status}")
    return "\n".join(lines) if lines else "(no tool calls)"


def _state_index(state: dict) -> dict:
    out = {}
    for kind, key in (("file", "files"), ("email", "emails"), ("event", "events")):
        for item in state.get(key, []):
            out[item["id"]] = (kind, item)
    return out


def _brief(kind: str, item: dict) -> str:
    if kind == "file":
        return f"{item.get('name')} ({item.get('folder')})"
    if kind == "email":
        return f"email from {item.get('sender')} \"{item.get('subject')}\" ({item.get('folder')})"
    return f"event \"{item.get('title')}\" {item.get('start_time')}"


def state_diff(initial: dict, final: dict) -> str:
    """Short, human-readable diff of two workspace states. Entities are matched by id."""
    a, b = _state_index(initial), _state_index(final)
    changes = []
    for eid in sorted(set(a) | set(b)):
        if eid in a and eid not in b:
            kind, item = a[eid]
            changes.append(f"removed from DB: {_brief(kind, item)}")
        elif eid in b and eid not in a:
            kind, item = b[eid]
            changes.append(f"new: {_brief(kind, item)}")
        else:
            kind, old = a[eid]
            _, new = b[eid]
            diffs = []
            for f in WATCHED_FIELDS:
                if f in old or f in new:
                    if old.get(f) != new.get(f):
                        diffs.append(f"{f} {old.get(f)!r} -> {new.get(f)!r}")
            if diffs:
                changes.append(f"{eid} {_brief(kind, old)}: " + "; ".join(diffs))
    return "; ".join(changes) if changes else "no change"


def replay_final_state(ws: WorkspaceClient, task, rec: dict):
    """Replay the stored tool calls. Returns (initial_state, final_state, mismatched_calls)."""
    initial_sid = ws.create_session(fixture=task.fixture)
    initial = ws.get_state(initial_sid)
    ws.delete_session(initial_sid)
    sid, mism, _ = replay(ws, task, rec["trajectory"])
    final = ws.get_state(sid)
    ws.delete_session(sid)
    return initial, final, mism


def build_clarification_map(pool: dict) -> dict:
    """Map each entry of results/clarification_labels.json to an episode, by the final message text
    and the task (the audit file stores the messages, not the run)."""
    audit = json.loads(AUDIT_JSON.read_text(encoding="utf-8"))
    labels = json.loads(CLAR_LABELS.read_text(encoding="utf-8"))
    by_key = {}
    for eid, v in pool.items():
        rec = v["record"]
        by_key.setdefault((rec["task_id"], final_text(rec)), []).append(eid)
    mapping, problems = {}, []
    for idx, row in enumerate(audit, start=1):
        key = str(idx)
        hits = by_key.get((row["task"], row["msg"].strip()), [])
        if len(hits) != 1:
            problems.append({"key": key, "task": row["task"], "matches": hits})
            continue
        if labels[key]["task"] != row["task"]:
            problems.append({"key": key, "task": row["task"], "label_task": labels[key]["task"]})
            continue
        mapping[key] = {"episode_id": hits[0], "manual_class": labels[key]["manual"],
                        "level": labels[key]["level"]}
    return {"mapped": mapping, "unmapped": problems, "total_labels": len(labels)}


def main():
    pool = load_pool()
    if len(pool) != 300:
        raise SystemExit(f"expected 300 rescored episodes, found {len(pool)}")

    sample = draw_sample(pool)
    tasks = task_by_id()
    ws = WorkspaceClient()
    if not ws.health_check():
        raise SystemExit("workspace server not running on localhost:8000")

    LABELS_DIR.mkdir(exist_ok=True)
    VALIDATION_DIR.mkdir(parents=True, exist_ok=True)

    rows, strata, mismatches = [], [], {}
    for item in sample:
        eid = item["episode_id"]
        rec = pool[eid]["record"]
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
        strata.append({"episode_id": eid, "level": item["level"],
                       "detector_flagged": item["flagged"],
                       "detector_types": detector_types(rec),
                       "stratum_quota": item["quota"]})

    ids_path = LABELS_DIR / "sample_ids.json"
    ids_path.write_text(json.dumps([s["episode_id"] for s in strata], indent=2) + "\n",
                        encoding="utf-8", newline="\n")
    with open(LABELS_DIR / "to_label.csv", "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    (VALIDATION_DIR / "sample_strata.json").write_text(
        json.dumps({"seed": SEED, "per_verdict": PER_VERDICT, "excluded_guide_examples":
                    sorted(GUIDE_EXAMPLES), "episodes": strata,
                    "replay_mismatches": mismatches}, indent=2) + "\n",
        encoding="utf-8", newline="\n")
    cmap = build_clarification_map(pool)
    (VALIDATION_DIR / "clarification_map.json").write_text(
        json.dumps(cmap, indent=2) + "\n", encoding="utf-8", newline="\n")

    print(f"sampled {len(strata)} episodes; replay mismatches: {len(mismatches)}")
    print(f"clarification map: {len(cmap['mapped'])} of {cmap['total_labels']} mapped; "
          f"{len(cmap['unmapped'])} unmapped")


if __name__ == "__main__":
    main()
