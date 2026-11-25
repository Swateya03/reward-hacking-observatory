"""Print every headline number quoted in README.md, computed from source data.

Sources:
  results/legacy/findings_partial_run.json  legacy aggregates, source run unknown
  tasks/task_bank.json       task counts and expected_state
  workspace/tool_registry.py tool counts
  pytest --collect-only      unit/integration test counts (not experiment runs)

Run from the repo root:
  python analysis/readme_numbers.py
"""

import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

FINDINGS_PATH = REPO / "results" / "legacy" / "findings_partial_run.json"  # legacy, source run unknown
TASK_BANK_PATH = REPO / "tasks" / "task_bank.json"
MODEL_DEFAULT = "claude-sonnet-4-20250514"  # from agent/clients/anthropic_client.py


def pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def collect_values() -> list[tuple[str, str, str]]:
    """Return (key, value, source) rows."""
    rows = []

    # ---- experiment aggregates: results/legacy findings_partial_run.json ----
    f = json.loads(FINDINGS_PATH.read_text())
    o = f["overall"]
    completed, total = o["completed_tasks"], o["total_tasks"]
    rows += [
        ("completed", f"{completed} of {total}", "legacy findings_partial_run.json overall"),
        ("completion_rate", pct(o["completion_rate"]), "legacy findings_partial_run.json overall"),
        ("avg_naive", f"{o['avg_naive']:.3f}", "legacy findings_partial_run.json overall"),
        ("avg_robust", f"{o['avg_robust']:.3f}", "legacy findings_partial_run.json overall"),
        ("avg_divergence", f"{o['avg_divergence']:+.3f}", "legacy findings_partial_run.json overall"),
        ("hack_rate_divergence_gt_0.1", pct(o["hack_rate"]), "legacy findings_partial_run.json overall (divergence > 0.1)"),
        ("naive_gt_robust", f"{round(o['naive_greater_than_robust_pct'] * completed)} of {completed} ({pct(o['naive_greater_than_robust_pct'])})",
         "legacy findings_partial_run.json overall"),
    ]
    for level in ["low", "medium", "high"]:
        b = f["by_ambiguity"][level]
        rows += [
            (f"{level}.n", str(b["count"]), "legacy findings_partial_run.json by_ambiguity"),
            (f"{level}.hack_rate", pct(b["hack_rate"]), "legacy findings_partial_run.json by_ambiguity (divergence > 0.1)"),
            (f"{level}.avg_divergence", f"{b['avg_divergence']:+.3f}", "legacy findings_partial_run.json by_ambiguity"),
            (f"{level}.avg_naive", f"{b['avg_naive']:.3f}", "legacy findings_partial_run.json by_ambiguity"),
            (f"{level}.avg_robust", f"{b['avg_robust']:.3f}", "legacy findings_partial_run.json by_ambiguity"),
        ]

    counts = f["hack_types"]["counts"]
    total_events = sum(counts.values())
    rows.append(("hack_events_total", str(total_events), "legacy findings_partial_run.json hack_types"))
    for name, c in sorted(counts.items(), key=lambda x: -x[1]):
        share = f"{c} of {total_events} ({100 * c / total_events:.0f}%)" if total_events else "0"
        rows.append((f"hack_type.{name}", share, "legacy findings_partial_run.json hack_types"))

    nc = f["notable_cases"]
    h, lo = nc["highest_divergence"], nc["lowest_divergence"]
    rows += [
        ("highest_divergence", f"{h['task_id']} naive={h['naive']} robust={h['robust']} div={h['divergence']}", "legacy findings_partial_run.json notable_cases"),
        ("lowest_divergence", f"{lo['task_id']} naive={lo['naive']} robust={lo['robust']} div={lo['divergence']}", "legacy findings_partial_run.json notable_cases"),
        ("perfect_scores", ", ".join(nc["perfect_scores"]), "legacy findings_partial_run.json notable_cases"),
    ]

    # ---- task bank: results/task bank, not run output ----
    tasks = json.loads(TASK_BANK_PATH.read_text())["tasks"]
    for level in ["low", "medium", "high"]:
        n = sum(1 for t in tasks if t["ambiguity_level"] == level)
        rows.append((f"bank.{level}", str(n), "tasks/task_bank.json"))
    rows.append(("bank.total", str(len(tasks)), "tasks/task_bank.json"))
    empty = sum(1 for t in tasks if not t["expected_state"])
    rows.append(("bank.empty_expected_state", str(empty), "tasks/task_bank.json"))

    # ---- tools: workspace/tool_registry.py ----
    from workspace.tool_registry import TOOL_REGISTRY

    tools = TOOL_REGISTRY.values()
    email = [t.name for t in tools if "email" in t.description.lower()]
    event = [t.name for t in tools if "event" in t.description.lower()]
    files = [t.name for t in tools if t.name not in email and t.name not in event]
    rows += [
        ("tools.total", str(len(TOOL_REGISTRY)), "workspace/tool_registry.py"),
        ("tools.file", f"{len(files)}: {', '.join(files)}", "workspace/tool_registry.py"),
        ("tools.email", f"{len(email)}: {', '.join(email)}", "workspace/tool_registry.py (description mentions 'email')"),
        ("tools.calendar", f"{len(event)}: {', '.join(event)}", "workspace/tool_registry.py (description mentions 'event')"),
    ]

    # ---- tests: pytest collection (no tests are executed) ----
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "--collect-only", "-q", "-p", "no:cacheprovider"],
        cwd=REPO, capture_output=True, text=True,
    ).stdout
    per_file: dict[str, int] = {}
    for line in out.splitlines():
        m = re.match(r"(tests/[\w.]+\.py)::", line)
        if m:
            per_file[m.group(1)] = per_file.get(m.group(1), 0) + 1
    for name in sorted(per_file):
        rows.append((f"tests.{Path(name).stem}", str(per_file[name]), "pytest --collect-only"))
    rows.append(("tests.total", str(sum(per_file.values())), "pytest --collect-only (unit/integration tests, not experiment runs)"))

    # ---- provenance ----
    rows += [
        ("run.date", "unknown", "legacy findings_partial_run.json has no timestamp; no run_summary.json in repo"),
        ("run.model", f"{MODEL_DEFAULT} (per code; not recorded in legacy findings_partial_run.json)", "agent/clients/anthropic_client.py"),
        ("run.step_limit", "unknown (code default is 20)", "agent/loop.py, run_experiment.py"),
    ]
    return rows


def main() -> None:
    rows = collect_values()
    print("| key | value | source |")
    print("|---|---|---|")
    for key, value, source in rows:
        print(f"| {key} | {value} | {source} |")


if __name__ == "__main__":
    main()
