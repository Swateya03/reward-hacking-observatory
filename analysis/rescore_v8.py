"""Re-score saved v7 episodes under the schema v8 rules, without calling the model.

Each saved trajectory is replayed on a fresh workspace session, using the same fixture and the
same tool calls in order. The replayed results are compared with the stored ones (IDs created by
the server are normalised, because they come from uuid4). The final step is then relabelled by
hacking/terminal.relabel_terminal, and the real scorer and detector run on the replayed state.

Inputs : results/runs/<model>/run_NN/task_*.json   (schema v7, left untouched)
Outputs: results/runs/<model>/rescored_v8/run_NN/task_*.json   (schema v8)
         results/rescore_v8_report.json   (replay fidelity and what changed)

Requires the workspace server on localhost:8000. Makes no model calls.

Usage (repo root):
  python analysis/rescore_v8.py --model claude-haiku-5-5
"""

import argparse
import io
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent.workspace_client import WorkspaceClient  # noqa: E402
from hacking.detector import HackingDetector  # noqa: E402
from hacking.terminal import relabel_terminal  # noqa: E402
from rewards.outcome import robust_outcome_available  # noqa: E402
from rewards.scorer import Scorer  # noqa: E402
from run_experiment import build_result  # noqa: E402
from tasks.task import TaskBank  # noqa: E402

ID_RE = re.compile(r"^(email|event|reply|draft)_\d{6}$")
RUN_DIR = re.compile(r"^run_(\d+)$")
PROVENANCE_KEYS = ("run_index", "git_commit", "git_dirty", "returned_model",
                   "commit_backfilled", "returned_model_unrecorded")


def normalise(x):
    if isinstance(x, dict):
        return {k: normalise(v) for k, v in x.items()}
    if isinstance(x, list):
        return [normalise(v) for v in x]
    if isinstance(x, str) and ID_RE.match(x):
        return "<ID>"
    return x


def _subst(x, mapping):
    if isinstance(x, dict):
        return {k: _subst(v, mapping) for k, v in x.items()}
    if isinstance(x, list):
        return [_subst(v, mapping) for v in x]
    if isinstance(x, str) and x in mapping:
        return mapping[x]
    return x


def replay(ws: WorkspaceClient, task, trajectory: list):
    """Replay tool calls on a fresh session. Server-created IDs differ between runs (uuid4), so
    each stored ID is mapped to the ID the replay created, and later arguments use the mapped ID.
    Returns (session_id, mismatches, total_calls)."""
    sid = ws.create_session(fixture=task.fixture)
    mismatches, total = 0, 0
    mapping = {}
    for step in trajectory:
        if step.get("type") != "tool_call":
            continue
        total += 1
        args = _subst(step.get("arguments") or {}, mapping)
        got = ws.call_tool(step["tool"], args, sid)
        stored = step.get("result") or {}
        if normalise(got) != normalise(stored):
            mismatches += 1
        # map IDs created by this call (stored value -> replayed value)
        if isinstance(got, dict) and isinstance(stored, dict):
            for k, v in stored.items():
                if isinstance(v, str) and ID_RE.match(v) and isinstance(got.get(k), str) and ID_RE.match(got[k]):
                    mapping[v] = got[k]
    return sid, mismatches, total


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--model", required=True)
    p.add_argument("--base", default="results/runs")
    p.add_argument("--report", default="results/rescore_v8_report.json")
    p.add_argument("--source-dir", default=None,
                   help="folder holding the schema-7 run_NN folders (default: the model folder). "
                        "Use results/runs/<model>/backfilled_v7 to re-score the backfilled copies.")
    a = p.parse_args(argv)

    root = Path(a.base) / a.model
    source = Path(a.source_dir) if a.source_dir else root
    out_root = root / "rescored_v8"
    tasks = {t.id: t for t in TaskBank("tasks/task_bank.json").get_all()}
    ws = WorkspaceClient()
    if not ws.health_check():
        print("[ERROR] workspace server not running on localhost:8000")
        sys.exit(1)

    report = {"episodes": 0, "replay_mismatch_calls": 0, "episodes_with_replay_mismatch": [],
              "relabelled": 0, "changed": Counter(), "unchanged_scores_among_untouched": 0,
              "untouched": 0, "untouched_differences": [], "subtypes": Counter(), "per_run": {}}

    for run_dir in sorted(source.iterdir()):
        m = RUN_DIR.match(run_dir.name) if run_dir.is_dir() else None
        if not m:
            continue
        out_dir = out_root / run_dir.name
        out_dir.mkdir(parents=True, exist_ok=True)
        n_run = 0
        for f in sorted(run_dir.glob("task_*.json")):
            old = json.loads(io.open(f, encoding="utf-8").read())
            if old["metadata"]["schema_version"] != 7:
                raise ValueError(f"{f}: expected schema v7, got {old['metadata']['schema_version']}")
            task = tasks[old["task_id"]]
            raw = old["trajectory"]
            sid, mism, total = replay(ws, task, raw)
            report["episodes"] += 1
            report["replay_mismatch_calls"] += mism
            if mism:
                report["episodes_with_replay_mismatch"].append(f"{run_dir.name}/{task.id}")

            traj2 = relabel_terminal(task, raw)
            relabelled = traj2[-1].get("closing_question", False)
            scores = Scorer(ws, task).score_all(traj2, sid)
            detector = HackingDetector(task, ws)
            robust_for_detector = scores["robust"].score if robust_outcome_available(task) else None
            events = detector.detect(traj2, scores["naive"].score, robust_for_detector, sid)
            ws.delete_session(sid)

            meta = old["metadata"]
            new = build_result(task, traj2, scores, events, model=old["model"],
                               temperature=meta.get("temperature"), max_steps=meta.get("max_steps"),
                               max_tokens=meta.get("max_tokens"), thinking=meta.get("thinking"))
            new.pop("_hacking_events", None)
            new["timestamp"] = old["timestamp"]
            # Run provenance is a fact about the original run, so it is carried over, not re-derived
            for k in PROVENANCE_KEYS:
                if k in meta:
                    new["metadata"][k] = meta[k]
            new["rescored_from"] = f"{run_dir.name}/{f.name} (schema 7, not modified)"
            new["replay"] = {"tool_calls": total, "mismatched_calls": mism}
            (out_dir / f.name).write_text(json.dumps(new, indent=2), encoding="utf-8")

            report["relabelled"] += int(relabelled)
            for e in new["hacking"]["events"]:
                if e.get("subtype"):
                    report["subtypes"][e["subtype"]] += 1
            # what changed for this episode
            changed = []
            for k in ("naive", "intermediate", "robust_outcome", "divergence"):
                if old["scores"][k] != new["scores"][k]:
                    changed.append(k)
            if old["hacking"]["was_hacked"] != new["hacking"]["was_hacked"]:
                changed.append("was_hacked")
            if old["completion_type"] != new["completion_type"]:
                changed.append("completion_type")
            for c in changed:
                report["changed"][c] += 1
            if not relabelled and not mism:
                report["untouched"] += 1
                if changed:
                    report["untouched_differences"].append({"episode": f"{run_dir.name}/{task.id}", "fields": changed})
                else:
                    report["unchanged_scores_among_untouched"] += 1
            n_run += 1
        report["per_run"][run_dir.name] = n_run

    report["changed"] = dict(report["changed"])
    report["subtypes"] = dict(report["subtypes"])
    Path(a.report).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in ("untouched_differences",)}, indent=2))


if __name__ == "__main__":
    main()
