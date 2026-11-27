"""Re-score the 300 episodes as schema v9: the v1 verdict (unchanged) and the v2 verdict.

Input : results/runs/claude-haiku-5-5/rescored_v8/run_NN/task_NNN.json  (schema 8)
Output: results/runs/claude-haiku-5-5/rescored_v9/run_NN/task_NNN.json  (schema 9)
        results/validation/v2_rescore_report.json

The v1 verdict is recomputed from the stored trajectory with the current v1 code and must match
the stored schema-8 verdict; mismatches are counted and reported. The v2 verdict comes from
hacking/detector_v2.py. No workspace server and no model calls are needed.

Usage (repo root):
  python analysis/rescore_v9.py
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from hacking.detector import CHECKS, HackingDetector, check_availability  # noqa: E402
from hacking.detector_v2 import VERSION, detect_v2  # noqa: E402
from rewards.outcome import robust_outcome_available  # noqa: E402
from tasks.task import TaskBank  # noqa: E402

SRC = REPO / "results" / "runs" / "claude-haiku-5-5" / "rescored_v8"
DST = REPO / "results" / "runs" / "claude-haiku-5-5" / "rescored_v9"
REPORT = REPO / "results" / "validation" / "v2_rescore_report.json"


def checks_block(events, robust_available: bool) -> dict:
    avail = check_availability(robust_available)
    fired = {e.hack_type.value for e in events}
    return {name: {"available": avail[name], "fired": (name in fired) if avail[name] else None}
            for name in CHECKS}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    tasks = {t.id: t for t in TaskBank(str(REPO / "tasks" / "task_bank.json")).get_all()}
    files = sorted(SRC.glob("run_*/task_*.json"))
    if len(files) != 300:
        raise SystemExit(f"expected 300 schema-8 episodes, found {len(files)}")

    v1_mismatch = []
    v1_fired = {c: 0 for c in CHECKS}
    v2_fired = {c: 0 for c in CHECKS}
    changed = []
    v1_hacked = v2_hacked = 0

    for src in files:
        rec = json.loads(src.read_text(encoding="utf-8"))
        task = tasks[rec["task_id"]]
        naive = rec["scores"]["naive"]
        robust = rec["scores"]["robust_outcome"]
        episode = f"{src.parent.name}/{src.stem}"

        v1 = HackingDetector(task, None).detect(
            rec["trajectory"], naive, robust if robust_outcome_available(task) else None, None)
        stored = sorted(e["type"] for e in rec["hacking"]["events"])
        recomputed = sorted(e.hack_type.value for e in v1)
        if stored != recomputed:
            v1_mismatch.append({"episode": episode, "stored": stored, "recomputed": recomputed})

        v2 = detect_v2(task, rec["trajectory"], naive, robust)
        v2_types = sorted({e.hack_type.value for e in v2})
        v1_types = sorted({e.hack_type.value for e in v1})
        robust_ok = robust_outcome_available(task)
        for c in CHECKS:
            v1_fired[c] += int(c in v1_types)
            v2_fired[c] += int(c in v2_types)
        v1_hacked += bool(v1_types)
        v2_hacked += bool(v2_types)
        if bool(v1_types) != bool(v2_types) or v1_types != v2_types:
            changed.append({"episode": episode, "v1": v1_types, "v2": v2_types})

        out = dict(rec)
        out["metadata"] = {**rec["metadata"], "schema_version": 9}
        out["hacking_v2"] = {
            "detector": VERSION,
            "was_hacked": bool(v2),
            "primary_hack_type": v2[0].hack_type.value if v2 else None,
            "checks": checks_block(v2, robust_ok),
            "events": [{"type": e.hack_type.value, "severity": round(e.severity, 3),
                        "description": e.description, "subtype": e.subtype} for e in v2],
        }
        out["rescored_from"] = f"rescored_v8/{episode}.json (schema 8)"
        dst = DST / src.parent.name / src.name
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8", newline="\n")

    report = {
        "schema_version": 9,
        "episodes": len(files),
        "detector_v2": VERSION,
        "v1_recomputed_mismatches": len(v1_mismatch),
        "v1_mismatch_detail": v1_mismatch,
        "fired_v1": v1_fired,
        "fired_v2": v2_fired,
        "episodes_flagged_v1": v1_hacked,
        "episodes_flagged_v2": v2_hacked,
        "episodes_with_changed_verdict": len(changed),
        "changed": changed,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"episodes {len(files)}; v1 mismatches {len(v1_mismatch)}; flagged v1 {v1_hacked}, v2 {v2_hacked}; "
          f"changed {len(changed)}")
    return 0 if not v1_mismatch else 1


if __name__ == "__main__":
    sys.exit(main())
