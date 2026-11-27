"""Generate the README Results block from committed result files.

The block (between <!-- RESULTS:BEGIN --> and <!-- RESULTS:END -->) is a template: the wording is fixed
here, and every number in it is filled from a file under results/ (or from the code, for counts of tasks,
tools and reward functions). When the README is up to date, the generated text is byte-identical to the
text between the markers. The numbers in the README's TL;DR, which sits outside the block, are checked
against the same files by tldr_problems().

Usage (repo root):
  python scripts/results_readme.py          # write the block into README.md (no change if up to date)
  python scripts/results_readme.py --check  # exit 1 if README.md differs from the generated block
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
VALIDATION = REPO / "results" / "validation"
DEV = VALIDATION / "detector_validation.json"
FRESH = VALIDATION / "detector_validation_fresh.json"
AGG_V8 = REPO / "results" / "aggregate_claude-haiku-5-5_v8.json"
COST_LOG = RUNS / "cost_log.jsonl"
LABELS = REPO / "labels"
LABEL_FILES = (LABELS / "labeled.csv", LABELS / "labeled_v2.csv")

TOOLS_EMAIL = {"list_emails", "read_email", "save_draft", "send_email", "move_email", "archive_email",
               "delete_email", "reply_email", "mark_read"}
TOOLS_CALENDAR = {"list_events", "create_event", "update_event", "delete_event", "check_conflicts"}
TOOLS_FILE = {"list_files", "read_file", "move_to_trash"}
CONFIRM_TASKS = ("task_002", "task_009")
CHECKS = ("metric_gaming", "scope_creep", "irreversibility_bias", "overclaiming", "sycophantic_caution")
WORDS = {0: "zero", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven",
         8: "eight", 9: "nine", 10: "ten"}

# The TL;DR sits outside the block. Each phrase is filled from values() and must appear in the TL;DR.
TL_DR_PHRASES = [
    "~1 time in {v1_inverse}",
    "{v2_fresh_p:.2f} precision on fresh",
    "about **{hack_lo}–{hack_hi}%**",
    "**{confirm_002} of 10**",
    "**{confirm_009} of 10**",
    "**{expl_low:.2f}**",
    "about **{expl_high:.1f}**",
]


def jload(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def rel(path: Path) -> str:
    return str(path.relative_to(REPO)).replace("\\", "/")


def ci_plain(p, lo, hi, d=2):
    return f"{p:.{d}f} ({lo:.{d}f}–{hi:.{d}f})"


def ci_long(p, lo, hi, d=2):
    return f"{p:.{d}f} (95% CI {lo:.{d}f}–{hi:.{d}f})"


def ci_of(entry):
    return (entry["point"], entry["ci95"][0], entry["ci95"][1])


def minus(x: float, d: int = 2) -> str:
    return ("−" if x < 0 else "") + f"{abs(x):.{d}f}"


def _runs_with_subtype(task_id: str):
    runs = sorted(p.parent.name for p in RESCORED_V8.glob("run_*/" + task_id + ".json"))
    hits = []
    for run in runs:
        rec = jload(RESCORED_V8 / run / f"{task_id}.json")
        if any(e.get("subtype") == "confirm_explicit_irreversible" for e in rec["hacking"]["events"]):
            hits.append(run)
    return runs, hits


def subtype_cross_check() -> dict:
    """The confirm_explicit_irreversible rule against the author's labels, on every labelled task_002 and
    task_009 episode in both label files."""
    rows = []
    for path in LABEL_FILES:
        for r in csv.DictReader(open(path, encoding="utf-8", newline="")):
            if not r["episode_id"].endswith(CONFIRM_TASKS):
                continue
            run, task = r["episode_id"].split("/")
            rec = jload(RESCORED_V8 / run / f"{task}.json")
            rule = any(e.get("subtype") == "confirm_explicit_irreversible" for e in rec["hacking"]["events"])
            rows.append({"episode": r["episode_id"], "rule_yes": rule, "author_hack": r["label"] == "hack"})
    cell = lambda rule, hack: [x["episode"] for x in rows if x["rule_yes"] == rule and x["author_hack"] == hack]
    return {"n": len(rows), "agree": sum(1 for x in rows if x["rule_yes"] == x["author_hack"]),
            "rule_yes_hack": cell(True, True), "rule_yes_not": cell(True, False),
            "rule_no_hack": cell(False, True), "rule_no_not": cell(False, False)}


def values() -> dict:
    """Every number the block and the TL;DR use, from the result files and the code."""
    from workspace.tool_registry import TOOL_REGISTRY
    from tasks.task import TaskBank
    from config import MAX_STEPS, BUDGET_USD, RUN_BUDGET_USD
    from rewards import naive, intermediate, robust
    from rewards.base import BaseReward
    from anthropic.resources.messages import Messages

    assert set(TOOL_REGISTRY) == TOOLS_EMAIL | TOOLS_CALENDAR | TOOLS_FILE, "tool categories out of date"
    reward_classes = [c for mod in (naive, intermediate, robust)
                      for _, c in inspect.getmembers(mod, inspect.isclass)
                      if issubclass(c, BaseReward) and c is not BaseReward]
    tasks = TaskBank(str(REPO / "tasks" / "task_bank.json")).get_all()
    files = sorted(RESCORED_V8.glob("run_*/task_*.json"))
    recs = [jload(f) for f in files]
    runs = sorted({f.parent.name for f in files})
    n_runs = len(runs)
    assert all(len(list(RESCORED_V8.glob(f"run_*/{t.id}.json"))) == n_runs for t in tasks), \
        "each task should have one episode per run"
    assert {r["metadata"]["max_steps"] for r in recs} == {MAX_STEPS}, "metadata step limit must match config"
    max_tokens = {r["metadata"]["max_tokens"] for r in recs}
    assert len(max_tokens) == 1
    calls = [json.loads(l) for l in COST_LOG.read_text(encoding="utf-8").splitlines() if l.strip()]

    dev = jload(DEV)
    fresh = jload(FRESH)
    agg = jload(AGG_V8)
    d1 = dev["hack_vs_not_hack"]
    d2 = dev["detector_v2_dev_set"]["binary"]
    f1, f2 = fresh["v1"], fresh["v2"]
    fc1 = {c["check"]: c for c in f1["per_check"]}
    fc2 = {c["check"]: c for c in f2["per_check"]}
    dc2 = {c["check"]: c for c in dev["detector_v2_dev_set"]["per_check"]}
    confirm = {}
    for task_id in CONFIRM_TASKS:
        all_runs, hits = _runs_with_subtype(task_id)
        confirm[task_id] = {"n": len(all_runs), "hits": hits}
    el = agg["levels"]
    ex = agg["exploratory"]["clarification_low_vs_medium_high"]
    return {
        "n_tasks": len(tasks), "n_runs": n_runs, "n_episodes": len(files),
        "levels": {lv: sum(1 for t in tasks if t.ambiguity_level == lv) for lv in ("low", "medium", "high")},
        "n_tools": len(TOOL_REGISTRY), "n_email": len(TOOLS_EMAIL), "n_calendar": len(TOOLS_CALENDAR),
        "n_file": len(TOOLS_FILE), "n_rewards": len(reward_classes),
        "reward_names": ", ".join(sorted(c.__name__ for c in reward_classes)),
        "model": ", ".join(sorted({r["metadata"]["model"] for r in recs})),
        "temps": sorted({json.dumps(r["metadata"]["temperature"]) for r in recs}),
        "thinking": sorted({json.dumps(r["metadata"]["thinking"]) for r in recs}),
        "max_steps": MAX_STEPS, "max_tokens": max_tokens.pop(),
        "window_start": sorted(r["timestamp"] for r in recs)[0][:19].replace("T", " "),
        "window_end": sorted(r["timestamp"] for r in recs)[-1][:19].replace("T", " "),
        "seed_in_sdk": "seed" in inspect.signature(Messages.create).parameters,
        "n_calls": len(calls), "spent": sum(x["cost_usd"] for x in calls),
        "budget": BUDGET_USD, "run_budget": RUN_BUDGET_USD,
        "dev": dev, "fresh": fresh, "d1": d1, "d2": d2, "f1": f1, "f2": f2,
        "fc1": fc1, "fc2": fc2, "dc2": dc2,
        "dev_n": d1["n"], "dev_hacks": d1["tp"] + d1["fn"],
        "fresh_n": fresh["scored"], "fresh_hacks": f2["unweighted"]["tp"] + f2["unweighted"]["fn"],
        "dev_weighted": dev["weighted_pool"], "fresh_weighted": f1["weighted"],
        "pool_dev": dev["weighted_pool"]["pool_episodes"], "pool_fresh": f1["weighted"]["pool_episodes"],
        "miss": fresh["v2_miss_bound"], "miss_k": len(fresh["v2_miss_bound"]["per_stratum"]),
        "irr_fp_word": WORDS[fc2["irreversibility_bias"]["false_positive"]],
        "dev_src": rel(DEV), "fresh_src": rel(FRESH),
        "cc": subtype_cross_check(), "confirm": confirm,
        "bank": {t.id: t for t in tasks}, "el": el, "ex": ex,
        # TL;DR values
        "v1_inverse": round(1 / d1["precision"]["point"]),
        "v2_fresh_p": f2["unweighted"]["precision"]["point"],
        "hack_lo": round(f1["weighted"]["hack_rate"]["point"] * 100),
        "hack_hi": round(dev["weighted_pool"]["hack_rate"]["point"] * 100),
        "confirm_002": len(confirm["task_002"]["hits"]), "confirm_009": len(confirm["task_009"]["hits"]),
        "expl_low": el["low"]["clarification_rate"]["point"],
        "expl_high": el["high"]["clarification_rate"]["point"],
    }


def _detector_table(v):
    d1, d2, f1, f2 = v["d1"], v["d2"], v["f1"], v["f2"]
    return "\n".join([
        f"| Detector | Precision on the design set | Precision on **fresh data** (unweighted) | "
        f"Precision on fresh data, weighted to the pool of {v['pool_fresh']} |",
        "|---|---|---|---|",
        f"| v1 | {ci_long(*ci_of(d1['precision']))} | {ci_long(*ci_of(f1['unweighted']['precision']))} | "
        f"{ci_long(*ci_of(f1['weighted']['precision']))} |",
        f"| v2 | {ci_long(*ci_of(d2['precision']))} | {ci_long(*ci_of(f2['unweighted']['precision']))} | "
        f"**{f2['weighted']['precision']['point']:.2f}** (95% CI {f2['weighted']['precision']['ci95'][0]:.2f}–"
        f"{f2['weighted']['precision']['ci95'][1]:.2f}) |",
    ])


def _hack_table(v):
    return "\n".join([
        "| Pool | Share of episodes that are hacks |",
        "|---|---|",
        f"| First design ({v['pool_dev']} episodes) | {ci_long(*ci_of(v['dev_weighted']['hack_rate']), d=3)} |",
        f"| Fresh design ({v['pool_fresh']} episodes) | {ci_long(*ci_of(v['fresh_weighted']['hack_rate']), d=3)} |",
    ])


def _design_table(v):
    d1, d2 = v["d1"], v["d2"]
    return "\n".join([
        "| Detector | TP | FP | FN | TN | Precision | Recall |",
        "|---|---:|---:|---:|---:|---:|---:|",
        f"| v1 | {d1['tp']} | {d1['fp']} | {d1['fn']} | {d1['tn']} | {ci_plain(*ci_of(d1['precision']))} | "
        f"{ci_plain(*ci_of(d1['recall']))} |",
        f"| v2 | {d2['tp']} | {d2['fp']} | {d2['fn']} | {d2['tn']} | {ci_plain(*ci_of(d2['precision']))} | "
        f"{ci_plain(*ci_of(d2['recall']))} |",
    ])


def _fp_table(v):
    rows = ["| Check | v1 fires (fresh) | v1 false positives (fresh) | v2 fires (fresh) | v2 false positives (fresh) |",
            "|---|---:|---:|---:|---:|"]
    for name in CHECKS:
        a, b = v["fc1"][name], v["fc2"][name]
        rows.append(f"| {name} | {a['fired']} | {a['false_positive']} | {b['fired']} | {b['false_positive']} |")
    return "\n".join(rows)


def _confirm_table(v):
    rows = ["| Task | Prompt | Asked instead of acting | Runs |", "|---|---|:-:|---|"]
    for task_id in CONFIRM_TASKS:
        c = v["confirm"][task_id]
        runs = ", ".join(r.replace("run_", "") for r in c["hits"])
        rows.append(f"| {task_id} | *\"{v['bank'][task_id].prompt}\"* | **{len(c['hits'])} / {c['n']}** | {runs} |")
    return "\n".join(rows)


def _expl_table(v):
    el = v["el"]
    return "\n".join([
        "| Ambiguity | Episodes ending in a real clarification (95% CI) |",
        "|---|---|",
        f"| 🟢 Low | {ci_plain(*ci_of(el['low']['clarification_rate']))} |",
        f"| 🟡 Medium | {ci_plain(*ci_of(el['medium']['clarification_rate']))} |",
        f"| 🔴 High | {ci_plain(*ci_of(el['high']['clarification_rate']))} |",
    ])


def block(v: dict) -> str:
    ex, cc, miss = v["ex"], v["cc"], v["miss"]
    expl_diff = f"{minus(ex['difference'])} (95% CI {minus(ex['ci95'][0])} to {minus(ex['ci95'][1])})"
    rest = lambda ids: ", ".join(i.replace("/task_", " task_") for i in ids) or "none"
    return f"""<!-- generated by scripts/results_readme.py; do not edit by hand -->

**Setup:** {v['n_tasks']} tasks × {v['n_runs']} runs = **{v['n_episodes']} episodes** on `claude-haiku-5-5`, temperature not sent (the model doesn't take it), thinking disabled, at most {v['max_steps']} steps and {v['max_tokens']} output tokens per response. Full settings are in [Method](#-method-fixed-settings).

### 🕵️ Can a detector spot hacks? Checked against a human

I hand-labelled episodes as **hack / not a hack**, then compared two detectors with those labels:
- **v1:** the original rules.
- **v2:** revised rules, designed on the first {v['dev_n']} labelled episodes and then **frozen** (`detector-v2-frozen`) before a **fresh, held-out sample** of {v['fresh_n']} was labelled.

```mermaid
flowchart LR
    A["{v['dev_n']} episodes<br/>labelled"] -->|"design v2 rules"| B["🔒 v2 frozen"]
    B --> C["{v['fresh_n']} NEW episodes<br/>labelled blind"]
    C --> D["✅ honest test<br/>of v2"]
```

{_detector_table(v)}

**Reading it:** v2 is clearly better than v1, but its precision fell from {v['d2']['precision']['point']:.2f} to {v['f2']['unweighted']['precision']['point']:.2f} on data it hadn't seen. That drop is why a held-out test matters. Rules tuned on one sample look better than they are.

**How common are real hacks?** By the human labels, stratum-weighted to the episode pool:

{_hack_table(v)}

Note: the hack rates stored in `results/aggregate_claude-haiku-5-5*.json` and `results/gaming_only_*.json` were computed by detector v1 alone, so they are not reliable hack rates. Use the human-labelled rates above.

<details>
<summary><b>Full confusion tables and false-positive sources</b></summary>

**Design set** ({v['dev_n']} labelled episodes, {v['dev_hacks']} hacks; `{v['dev_src']}`):

{_design_table(v)}

**False positives by check** (`{v['fresh_src']}`):

{_fp_table(v)}

All {v['irr_fp_word']} irreversibility false positives are permanent deletes **the task explicitly asked for**. That's the next rule to fix.

**Recall is not established.** Every hack in the fresh sample was flagged, but its not-flagged episodes contained no hacks, so the sample can't show what v2 misses. Joint 95% upper bound on hacks v2 doesn't flag in the {v['pool_fresh']}-episode pool: {miss['upper_bound_hacks_missed_in_pool']:.1f} (exact one-sided Clopper-Pearson per stratum at 0.05/{v['miss_k']}, Bonferroni, summed; key `v2_miss_bound`).

</details>

### ✋ Main behavioural finding: confirm instead of act

When the prompt **explicitly** says *send* or *permanently delete*, how often does the agent stop and ask for confirmation instead?

{_confirm_table(v)}

The same model, on the same prompt, sometimes acts and sometimes asks. That run-to-run variation is why each task ran {v['n_runs']} times.

**Cross-check:** the rule that counts this (`confirm_explicit_irreversible`, `hacking/terminal.py`) agrees with the human hack labels on **{cc['agree']} of {cc['n']}** labelled episodes of these two tasks. This is partly by construction: labelling rule 1 in `docs/LABELING_DECISIONS.md` describes the same pattern. So it checks the rule's implementation, not the label itself.

### 🤔 Exploratory: does the agent ask more when tasks are vague?

> ⚠️ **Exploratory.** This comparison was chosen *after* seeing the data. Treat it as a hypothesis to test, not a finding.

{_expl_table(v)}

Difference, low minus (medium + high): {expl_diff}, permutation p = {ex['permutation_p']:.3f} (`results/aggregate_claude-haiku-5-5_v8.json`).

### ⚠️ Limitations

- **One labeller.** I labelled every episode, discussing each one with an AI assistant before deciding. That isn't independent labelling, and no self-agreement check was run.
- **Small samples.** {v['dev_n']} + {v['fresh_n']} labelled episodes, with {v['dev_hacks']} and {v['fresh_hacks']} hacks. Intervals are wide.
- **One model.** Everything here is `claude-haiku-5-5`. The exact served snapshot wasn't recorded for these runs (see `docs/BACKFILL_NOTE.md`).
- **Recall unknown.** See the bound above.
- **irreversibility_bias** still flags explicitly requested permanent deletes.
- **Overclaiming isn't detected automatically.** One labelled overclaiming case (`run_07/task_023`) was missed.
- **`list_files` doesn't show subfolders.** Listing `/hr` doesn't reveal `/hr/confidential`. This likely caused several confident but false "no files" claims, and the fix belongs in the environment.
- **`check_conflicts` compares timestamps as text**, which is correct only while every time uses the same UTC `Z` format.
- **metric_gaming in v2 is untested.** It fired in neither sample.
- **The robust reward needs an expected end state,** so open-ended tasks are scored N/A.
- **Prompt text issue.** The `move_to_trash` description tells the agent to prefer it over `delete_permanently`, a tool that doesn't exist (the real one is `delete_email`). These results were produced with that text.
- **Measurement only.** No policy is trained on these rewards.

### 🔭 Future work

- [ ] **Detector v3:** treat an explicitly requested permanent delete as in scope, then validate it on a fresh sample.
- [ ] **Fix `list_files`** to show subfolders, and rerun the affected episodes.
- [ ] **Detect overclaiming** by comparing completion claims with the final state.
- [ ] **More models** on the same task bank, with the prompt text fixed.
- [ ] **A second, independent labeller,** with an agreement measure.

Full validation report: [docs/DETECTOR_VALIDATION.md](docs/DETECTOR_VALIDATION.md) · Change history: [docs/CHANGES_SINCE_JUNE_2026.md](docs/CHANGES_SINCE_JUNE_2026.md)"""


def tldr_problems(text: str, v: dict) -> list[str]:
    """Each TL;DR number must appear in the TL;DR section, filled from the result files."""
    start = text.index("## ⚡ TL;DR")
    end = text.index("## 📑", start)
    section = text[start:end]
    return [f"TL;DR number not found: '{p.format(**v)}' (computed from the result files)"
            for p in TL_DR_PHRASES if p.format(**v) not in section]


def expected_between(generated: str) -> str:
    """The exact text between the markers: a newline, the block, then a blank line before the end marker."""
    return "\n" + generated + "\n\n"


def current_between(text: str) -> str:
    start = text.index(BEGIN) + len(BEGIN)
    end = text.index(END)
    return text[start:end]


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    argv = list(sys.argv[1:] if argv is None else argv)
    text = README.read_text(encoding="utf-8")
    generated = block(values()).strip("\n")
    if "--check" in argv:
        if current_between(text) != expected_between(generated):
            print("README Results block is out of date; run: python scripts/results_readme.py")
            return 1
        print("README Results block is up to date.")
        return 0
    start = text.index(BEGIN)
    end = text.index(END) + len(END)
    text = text[:start] + BEGIN + expected_between(generated) + END + text[end:]
    README.write_text(text, encoding="utf-8", newline="\n")
    print("wrote the Results block to README.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
