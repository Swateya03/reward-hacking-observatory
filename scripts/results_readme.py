"""Generate the README Results section from committed result files.

Every number in the generated block comes from a file under results/ (or from the code, for counts of
tasks, tools and reward functions). Each table names its source. README.md holds the block between the
markers RESULTS:BEGIN and RESULTS:END; scripts/check_docs.py regenerates it and fails if the README copy
differs.

Usage (repo root):
  python scripts/results_readme.py            # write the block into README.md
  python scripts/results_readme.py --check    # exit 1 if README.md differs from the generated block
"""

import csv
import inspect
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

README = REPO / "README.md"
BEGIN = "<!-- RESULTS:BEGIN -->"
END = "<!-- RESULTS:END -->"

RUNS = REPO / "results" / "runs" / "claude-haiku-5-5"
RESCORED_V8 = RUNS / "rescored_v8"
RESCORED_V9 = RUNS / "rescored_v9"
VALIDATION = REPO / "results" / "validation"
DEV = VALIDATION / "detector_validation.json"
FRESH = VALIDATION / "detector_validation_fresh.json"
AGG_V8 = REPO / "results" / "aggregate_claude-haiku-5-5_v8.json"
COST_LOG = RUNS / "cost_log.jsonl"

TOOLS_EMAIL = {"list_emails", "read_email", "save_draft", "send_email", "move_email", "archive_email",
               "delete_email", "reply_email", "mark_read"}
TOOLS_CALENDAR = {"list_events", "create_event", "update_event", "delete_event", "check_conflicts"}
TOOLS_FILE = {"list_files", "read_file", "move_to_trash"}
CONFIRM_TASKS = ("task_002", "task_009")


def jload(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def rel(path: Path) -> str:
    return str(path.relative_to(REPO)).replace("\\", "/")


def fmt(x, digits=2):
    if x is None:
        return "n/a"
    return f"{x:.{digits}f}"


def ci_text(entry, digits=2):
    if not entry or entry.get("point") is None:
        return "n/a"
    if not entry.get("ci95"):
        return f"{fmt(entry['point'], digits)} (CI n/a)"
    lo, hi = entry["ci95"]
    return f"{fmt(entry['point'], digits)} (95% CI {fmt(lo, digits)} to {fmt(hi, digits)})"


def _counts():
    from workspace.tool_registry import TOOL_REGISTRY
    from rewards import naive, intermediate, robust
    from rewards.base import BaseReward
    names = set(TOOL_REGISTRY)
    assert names == TOOLS_EMAIL | TOOLS_CALENDAR | TOOLS_FILE, "tool categories out of date"
    reward_classes = [c for mod in (naive, intermediate, robust)
                      for _, c in inspect.getmembers(mod, inspect.isclass)
                      if issubclass(c, BaseReward) and c is not BaseReward]
    from tasks.task import TaskBank
    tasks = TaskBank(str(REPO / "tasks" / "task_bank.json")).get_all()
    levels = {lv: sum(1 for t in tasks if t.ambiguity_level == lv) for lv in ("low", "medium", "high")}
    return {"tasks": len(tasks), "levels": levels, "tools": len(names),
            "tools_email": len(TOOLS_EMAIL), "tools_calendar": len(TOOLS_CALENDAR), "tools_file": len(TOOLS_FILE),
            "rewards": len(reward_classes), "reward_names": sorted(c.__name__ for c in reward_classes)}


def _seed_parameter_present() -> bool:
    from anthropic.resources.messages import Messages
    return "seed" in inspect.signature(Messages.create).parameters


def testbed_block() -> list[str]:
    c = _counts()
    files = sorted(RESCORED_V8.glob("run_*/task_*.json"))
    recs = [jload(f) for f in files]
    runs = sorted({f.parent.name for f in files})
    per_run = {r: sum(1 for f in files if f.parent.name == r) for r in runs}
    models = sorted({r["metadata"]["model"] for r in recs})
    temps = sorted({json.dumps(r["metadata"]["temperature"]) for r in recs})
    thinking = sorted({json.dumps(r["metadata"]["thinking"]) for r in recs})
    max_steps = sorted({r["metadata"]["max_steps"] for r in recs})
    max_tokens = sorted({r["metadata"]["max_tokens"] for r in recs})
    stamps = sorted(r["timestamp"] for r in recs)
    calls = [json.loads(l) for l in COST_LOG.read_text(encoding="utf-8").splitlines() if l.strip()]
    spent = sum(x["cost_usd"] for x in calls)
    from config import BUDGET_USD, RUN_BUDGET_USD
    t_src = f"`{rel(REPO / 'tasks' / 'task_bank.json')}`"
    lv = c["levels"]
    return [
        "### Testbed", "",
        "| Quantity | Value | Source |",
        "|---|---|---|",
        f"| Tasks | {c['tasks']} ({lv['low']} low, {lv['medium']} medium, {lv['high']} high) | {t_src} |",
        f"| Tools | {c['tools']} ({c['tools_email']} email, {c['tools_calendar']} calendar, {c['tools_file']} file) | "
        f"`{rel(REPO / 'workspace' / 'tool_registry.py')}` |",
        f"| Reward functions | {c['rewards']} ({', '.join(c['reward_names'])}) | `rewards/` |",
        f"| Model | {', '.join(models)} | `metadata.model` in `{rel(RESCORED_V8)}/` |",
        f"| Episodes | {len(files)}: {len(runs)} runs, {', '.join(str(n) for n in sorted(set(per_run.values())))} tasks each | "
        f"`{rel(RESCORED_V8)}/run_NN/` |",
        f"| Run window (UTC) | {stamps[0][:19].replace('T', ' ')} to {stamps[-1][:19].replace('T', ' ')} | "
        "episode `timestamp` |",
        f"| Temperature | not sent: {'null' if temps == ['null'] else temps} in {len(recs)} of {len(recs)} episodes | "
        "`metadata.temperature` |",
        f"| Thinking | disabled in {len(recs)} of {len(recs)} episodes (`{thinking[0]}`) | `metadata.thinking` |",
        f"| Step limit / max output tokens | {', '.join(map(str, max_steps))} / {', '.join(map(str, max_tokens))} | "
        "`metadata.max_steps`, `metadata.max_tokens` |",
        f"| Seed parameter in the installed SDK | {'yes' if _seed_parameter_present() else 'no'} | "
        "`anthropic` `Messages.create` signature (no seed is set) |",
        f"| API calls and cost | {len(calls)} calls, ${fmt(spent, 2)} in total; caps ${fmt(BUDGET_USD, 2)} overall and "
        f"${fmt(RUN_BUDGET_USD, 2)} per run | `{rel(COST_LOG)}`; `config.py` |",
        "",
    ]


def detector_block() -> list[str]:
    dev = jload(DEV)
    fresh = jload(FRESH)
    d1 = dev["hack_vs_not_hack"]
    d2 = dev["detector_v2_dev_set"]["binary"]
    f1, f2 = fresh["v1"], fresh["v2"]
    dev_n = d1["n"]
    fresh_n = fresh["scored"]
    hack_dev = d1["tp"] + d1["fn"]
    hack_fresh = f2["unweighted"]["tp"] + f2["unweighted"]["fn"]
    src_dev = f"`{rel(DEV)}`"
    src_fresh = f"`{rel(FRESH)}`"
    lines = [
        "### Detector validation", "",
        "Two detectors are compared: **v1** (the detector behind the Upgrade 1 results) and **v2** (frozen as "
        "`detector-v2-frozen`; its rules were chosen from the development set). Hack labels are the author's "
        "(one labeller, discussed row by row with an AI assistant; no self-agreement check was run).", "",
        f"**Development set** ({dev_n} labelled episodes, {hack_dev} hacks; source {src_dev}; v2 block from the "
        "same file):", "",
        "| Detector | TP | FP | FN | TN | Precision | Recall |",
        "|---|---:|---:|---:|---:|---:|---:|",
        f"| v1 | {d1['tp']} | {d1['fp']} | {d1['fn']} | {d1['tn']} | {ci_text(d1['precision'])} | {ci_text(d1['recall'])} |",
        f"| v2 | {d2['tp']} | {d2['fp']} | {d2['fn']} | {d2['tn']} | {ci_text(d2['precision'])} | {ci_text(d2['recall'])} |",
        "",
        f"**Fresh held-out sample** ({fresh_n} labelled episodes, {hack_fresh} hacks; drawn from 245 episodes "
        f"outside the development sample; source {src_fresh}):", "",
        "| Detector | Precision, unweighted | Precision, stratum-weighted (pool of 245) | Recall, unweighted (every hack flagged; interval not informative, see below) |",
        "|---|---|---|---|",
        f"| v1 | {ci_text(f1['unweighted']['precision'])} | {ci_text(f1['weighted']['precision'])} | "
        f"{ci_text(f1['unweighted']['recall'])} |",
        f"| v2 | {ci_text(f2['unweighted']['precision'])} | {ci_text(f2['weighted']['precision'])} | "
        f"{ci_text(f2['unweighted']['recall'])} |",
        "",
        "**Human-labelled hack rate, stratum-weighted** (share of the pool that is a hack):", "",
        "| Pool | Hack rate (95% CI) | Estimated hacks in pool |",
        "|---|---|---|",
        f"| Development design, 295 episodes (source {src_dev}) | {ci_text(dev['weighted_pool']['hack_rate'], 3)} | "
        f"{ci_text(dev['weighted_pool']['hacks_in_pool'], 1)} |",
        f"| Fresh design, 245 episodes (source {src_fresh}) | {ci_text(f1['weighted']['hack_rate'], 3)} | "
        f"{ci_text(f1['weighted']['hacks_in_pool'], 1)} |",
        "",
        "**Per-check false positives.** Sources: the fresh file (both detectors) and the development file (v2).", "",
        "| Check | v1 fires (fresh) | v1 false positives (fresh) | v2 fires (fresh) | v2 false positives (fresh) | v2 false positives (development) |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    d2_checks = {c["check"]: c for c in dev["detector_v2_dev_set"]["per_check"]}
    for c1, c2 in zip(f1["per_check"], f2["per_check"]):
        name = c1["check"]
        dev_fp = d2_checks[name]["false_positive"]
        lines.append(f"| {name} | {c1['fired']} | {c1['false_positive']} | {c2['fired']} | "
                     f"{c2['false_positive']} | {dev_fp} |")
    mb = fresh["v2_miss_bound"]
    lines += [
        "",
        "**Recall is not established.** The fresh sample flags every hack it contains, but its not-flagged strata "
        "contain no hacks, so it cannot show what v2 misses. The joint 95% upper bound on hacks that v2 does not "
        f"flag in the 245-episode pool is {fmt(mb['upper_bound_hacks_missed_in_pool'], 1)} "
        f"({mb['method']}; source {src_fresh}, key `v2_miss_bound`).",
        "",
    ]
    return lines


def behaviour_block() -> list[str]:
    from tasks.task import TaskBank
    bank = {t.id: t for t in TaskBank(str(REPO / "tasks" / "task_bank.json")).get_all()}
    lines = [
        "### Main behavioural finding: confirm instead of act", "",
        "On tasks whose prompt explicitly asks for a send or a permanent delete, how often the agent ends by asking "
        "for confirmation instead of acting. The count is the v1 sub-type `confirm_explicit_irreversible` "
        f"(`hacking/terminal.py`), per run, from `{rel(RESCORED_V8)}/run_NN/`. This sub-type is a v1 rule; its "
        "precision was not measured separately.", "",
        "| Task | Prompt | Runs with the sub-type (of 10) | Runs |",
        "|---|---|---:|---|",
    ]
    for task_id in CONFIRM_TASKS:
        hits = []
        runs = sorted(p.parent.name for p in RESCORED_V8.glob("run_*/" + task_id + ".json"))
        for run in runs:
            rec = jload(RESCORED_V8 / run / f"{task_id}.json")
            if any(e.get("subtype") == "confirm_explicit_irreversible" for e in rec["hacking"]["events"]):
                hits.append(run)
        lines.append(f"| {task_id} | {bank[task_id].prompt} | {len(hits)} of {len(runs)} | "
                     f"{', '.join(h.replace('run_', '') for h in hits) or 'none'} |")
    lines.append("")
    return lines


def exploratory_block() -> list[str]:
    agg = jload(AGG_V8)
    lv = agg["levels"]
    ex = agg["exploratory"]["clarification_low_vs_medium_high"]
    lines = [
        "### Exploratory: clarification rate by ambiguity level", "",
        "**EXPLORATORY.** The low-versus-(medium plus high) comparison was chosen after the data were seen. It is not "
        "a pre-specified test. Clarification rate is the share of episodes whose final step is a real clarification "
        f"(source `{rel(AGG_V8)}`, key `levels.*.clarification_rate`).", "",
        "| Ambiguity level | Clarification rate (95% CI) |",
        "|---|---|",
    ]
    for level in ("low", "medium", "high"):
        lines.append(f"| {level} | {ci_text(lv[level]['clarification_rate'])} |")
    lines += ["", f"Exploratory difference, low minus (medium plus high): {fmt(ex['difference'])} "
              f"(95% CI {fmt(ex['ci95'][0])} to {fmt(ex['ci95'][1])}), permutation p = {fmt(ex['permutation_p'], 3)}, "
              f"key `exploratory.clarification_low_vs_medium_high`.", ""]
    return lines


def limitations_block() -> list[str]:
    dev = jload(DEV)
    fresh = jload(FRESH)
    d1 = dev["hack_vs_not_hack"]
    f2 = fresh["v2"]
    irr = next(c for c in f2["per_check"] if c["check"] == "irreversibility_bias")
    overclaim = next(c for c in dev["detector_v2_dev_set"]["per_check"] if c["check"] == "overclaiming")
    return [
        "### Limitations", "",
        "- **One labeller, AI-assisted.** The author labelled every episode. The labels were discussed row by row "
        "with an AI assistant, and its suggestions were reviewed and approved row by row. This is not an "
        "independent labelling.",
        "- **No self-agreement check was run.** The labeller's consistency is not measured.",
        f"- **Small samples.** The development set has {d1['n']} labelled episodes and {d1['tp'] + d1['fn']} hacks. "
        f"The fresh sample has {fresh['scored']} episodes and {f2['unweighted']['tp'] + f2['unweighted']['fn']} hacks. "
        "Intervals are wide.",
        "- **Single model.** Every episode is claude-haiku-5-5. Nothing here shows what other models do.",
        f"- **Recall is unknown.** See the upper bound above ({fmt(fresh['v2_miss_bound']['upper_bound_hacks_missed_in_pool'], 1)} "
        "hacks in the pool).",
        f"- **irreversibility_bias false positives on explicitly requested deletes.** v2 keeps the v1 rule; in the "
        f"fresh sample it fires {irr['fired']} times and {irr['false_positive']} of those are false positives, on "
        "deletes the task asked for. v3 future work: treat an explicitly requested permanent delete as in scope.",
        f"- **Overclaiming gap.** The overclaiming check fired {overclaim['fired']} times in the development set; a "
        "hack labelled overclaiming (`run_07/task_023`) is missed.",
        "- **list_files hides subfolders.** `list_files` matches the folder name exactly, so listing `/hr` does not "
        "show `/hr/confidential`. This is a likely cause of false \"no files\" claims; the fix belongs to the "
        "environment, not the detector.",
        "- **check_conflicts compares timestamps as text.** It is implemented as an overlap query, not a stub. Its "
        "text comparison is correct only when every time uses the same UTC `Z` format.",
        "- **metric_gaming v2 is untested.** It fires nowhere in the development or fresh samples.",
        "",
    ]


def build() -> str:
    lines = ["<!-- generated by scripts/results_readme.py; do not edit by hand -->", ""]
    lines += testbed_block()
    lines += detector_block()
    lines += behaviour_block()
    lines += exploratory_block()
    lines += limitations_block()
    lines += ["Detector-based hack rates from Upgrade 1 are not valid hack rates. See "
              "[docs/DETECTOR_VALIDATION.md](docs/DETECTOR_VALIDATION.md) for the validation against hand labels.", ""]
    return "\n".join(lines)


def current_block(text: str) -> str:
    start = text.index(BEGIN) + len(BEGIN)
    end = text.index(END)
    return text[start:end].strip("\n")


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    argv = list(sys.argv[1:] if argv is None else argv)
    block = build()
    text = README.read_text(encoding="utf-8")
    if "--check" in argv:
        if current_block(text) != block.strip("\n"):
            print("README Results block is out of date; run: python scripts/results_readme.py")
            return 1
        print("README Results block is up to date.")
        return 0
    start = text.index(BEGIN)
    end = text.index(END) + len(END)
    text = text[:start] + BEGIN + "\n" + block + "\n" + END + text[end:]
    README.write_text(text, encoding="utf-8", newline="\n")
    print("wrote the Results block to README.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
