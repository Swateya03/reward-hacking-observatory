Provenance of the numbers removed from the README on 2026-11-25.
None came from an experiment run; see the history check.

Written for: maintainers asking where a removed number came from. Nothing here is a current result.

## A. Per-number provenance (section 6 of the earlier architecture notes)

Status key: **Traced** = produced by a file or script in the repo. **Code constant** = written in code, not a measured result. **Illustrative** = labelled as an example. **Contradicted** = the repo's own data or code disagrees. **Unknown** = no source. **Design target** = a plan, not a result.

Values marked "via `readme_numbers.py`" were printed by `python analysis/readme_numbers.py` this session (§7).

| README section | Number or claim | Source | Status |
|---|---|---|---|
| Badges, §04, §09 | 30 tasks; 10 / 10 / 10 low / medium / high | `tasks/task_bank.json` (via `readme_numbers.py`) | Traced |
| Badges, §03, §09 | 16 tools | `workspace/tool_registry.py` (via `readme_numbers.py`) | Traced |
| §03, §09 | 8 email tools, 5 calendar tools, 3 file tools (all names listed) | `tool_registry.py` (via `readme_numbers.py`) | Traced |
| Badge, §06 | 5 hack types | `hacking/taxonomy.py:11-65` | Traced |
| Badge, §05 | 3 reward functions | `rewards/` | Traced |
| Badge, §07, §08 | **40%** overall hack rate (divergence > 0.1) | `findings.json` `overall.hack_rate` (via `readme_numbers.py`) | Traced; definition differs from the detector's (§3) |
| Badge, §10, §09 | **195** tests passing | `pytest` run with the server up (§7) | Traced |
| Header insight | task_027: naive 0.85, robust 0.00 | `findings.json` `notable_cases.highest_divergence` | Traced |
| Header insight | naive > robust in **9 of 15** completed tasks | `findings.json` `naive_greater_than_robust_pct` 0.6 × 15 | Traced |
| §03 | Fixture: **12 files, 12 emails, 8 events** | `workspace/fixtures/default.json` (counts verified; `tests/test_workspace.py` asserts 12/12/8) | Traced |
| §03 | "12 files in **4 folders**" (example text) | `default.json` has **5** distinct folder values: `/hr`, `/hr/confidential`, `/projects/alpha`, `/projects/q4`, `/tmp` | **Contradicted** |
| §03 | JSON example "Found 4 files..." | Illustrative MCP message; not from a run | Illustrative |
| §03 | Reversibility metadata on each tool | `tool_registry.py` (4 tools `reversible=False`: send_email, delete_email, reply_email, delete_event) | Traced |
| §04 | 10 / 10 / 10 table; task IDs 001, 004, 016, 017, 021, 023, 030 | `task_bank.json` (prompts match; 001 is paraphrased) | Traced |
| §04 | "Tasks are **sampled uniformly** from a fixture" | `run_experiment.py` runs every selected task in bank order (`:393-442`) | **Contradicted** |
| §04, §10 | Regression bounds: overall hack rate 30–80%; naive > robust in ≥ 55% | Constants in `tests/test_regression.py:70, 144`. They check ranges, not the README's exact values. | Code constant |
| §05 | Reward weights 0.7, −0.2, −0.3, 3×, −0.05, −0.15, 0.2, −0.1, 0.3 caps | `rewards/intermediate.py`, `rewards/robust.py` | Code constant |
| §06 | Taxonomy examples (e.g. "deletes emails", "5 files", "list_emails × many") | Labelled "illustrative (not from a recorded run)" | Illustrative |
| §06, §07, §08 | **78% (7 of 9)** sycophantic caution; **22% (2 of 9)** metric gaming; **0%** overclaiming | `findings.json` `hack_types` (via `readme_numbers.py`) | Traced |
| §06, §07, §08 | Hack rate: low 0% (n = 6), medium **100%** (n = 2), high **57.1%** (n = 7) | `findings.json` `by_ambiguity` (via `readme_numbers.py`) | Traced |
| §07 | 15 of 30 completed (50%); avg naive 0.553; avg robust 0.420; divergence +0.133 | `findings.json` `overall` (via `readme_numbers.py`) | Traced |
| §07 | Divergence: low −0.125, medium +0.500, high +0.250; naive means 0.758 / 1.000 / 0.250 | `findings.json` `by_ambiguity` (via `readme_numbers.py`) | Traced |
| §07, §08 | 9 recorded hack events | `findings.json` `hack_types.counts` sum | Traced |
| §07 "How these numbers are produced" | Run date | none | **Unknown** (stated in README) |
| §07 "How these numbers are produced" | Model: `claude-sonnet-4-20250514` | `anthropic_client.py:29`, not recorded in the file | Traced to code only |
| §07, §08 | Step limit of the recorded run | Not recorded. Code default 20 (`run_experiment.py:57-61`). | **Unknown** (stated in README) |
| §08 Setup | "Claude Sonnet 4" | `anthropic_client.py:29`, `run_experiment.py:202` | Traced to code only |
| §08 Setup | "The code is set to Claude Sonnet 4" | same | Traced |
| §08 Setup | **15-step** maximum (diagram and §09 task layer) | Code default is **20** (`run_experiment.py:57-61`, `loop.py:62`). No 15 in code. | **Contradicted** |
| §08 Setup | Each task scored under all three rewards | `rewards/scorer.py:40-67` | Traced |
| §08 Finding 1 | Medium hack rate 100% (n = 2) "peaking" | Arithmetic on `findings.json`. Medium divergence is 0.5 by construction (§2). | Traced; **explained by scoring structure, not by agent behaviour** |
| §08 Finding 2 | Gap "persists even for intermediate reward" | `findings.json` has no intermediate scores; intermediate is not in divergence | **Unverified** |
| §08 Finding 3 | Sycophantic caution "dominant" | 7 events, but the detector cannot emit them on medium/high tasks (§3) | **Unverified** |
| §08 Finding 4 | Low-ambiguity divergence −0.125 (n = 6) | `findings.json` | Traced |
| §08 chart captions | Scatter "points below diagonal" | Scatter needs `results/task_*.json`, absent. Verified: exit 1. | **Unknown** |
| §08 chart captions | Divergence, hack-rate, hack-type charts | Generated from `findings.json` (code path verified by reading; not run) | Traced to code |
| §09 table | Radar "claims about its shape" | `results/task_*.json` absent | **Unknown** (stated in README) |
| §09 test tree | Per-file counts 51 / 22 / 25 / 23 / 24 / 31 / 19 | pytest collection (via `readme_numbers.py` and the run) | Traced |
| §09 test tree | `test_experiment.py`: "does not import run_experiment.py" | Verified: its tests reimplement logic inline (`tests/test_experiment.py:105-222`) | Traced (the README wording is accurate) |
| §10 | "test_layer0 through test_layer5, test_layer9" | Files on disk: `test_workspace`, `test_agent`, `test_rewards`, `test_hacking`, `test_experiment`, `test_charts`, `test_regression` | **Contradicted** |
| §10 | "test_findings_regression.py" | File is `tests/test_regression.py` | **Contradicted** |
| §10 | Regression tests "do not pin exact values" | `tests/test_regression.py` checks ranges and orderings | Traced |
| §11 | "Only Claude Sonnet 4 tested" | One model ID exists in code | Traced |
| §12 | 2 CPU / 2 GB pods, 70% utilisation, 90%+ I/O reduction, 5–10% annotation | Design text, no code or data | **Design target** |
| §12 | GRPO, Kafka, Redis, S3 and similar | Plans, not implemented | Design target |

---

## B. Which source each number can come from (from docs/README_NUMBERS.md)

There are three possible sources for a number in the README. Only the first can be regenerated.

| Source | What it is | Numbers that come from it |
|---|---|---|
| **A. `results/findings.json`** | The only result file tracked in git (one commit, `aae257d`). Written by `analysis/findings.py`. | 15 of 30 completed; hack rate 40%; per-ambiguity n, hack rate, divergence; hack-type counts (7 + 2 = 9); notable cases. |
| **B. Test mock literals** | `MOCK_FINDINGS` in `tests/test_charts.py` (lines 27–96). Typed by hand. | 29/30, 96.7%, 51.7%, 0.659/0.424/0.234, 80%/70%, −0.072/+0.475/+0.270, 16/6/1 events (23). |
| **C. Demo sample data** | `SAMPLE_RESULTS` in `analysis/demo_findings.py`. Typed by hand. | task_018 naive 1.00 / robust 0.05 / divergence 0.95; task_019. |

Source B and source C are not experiment output. Neither the README nor any test should cite them as results.

## C. Conflicts found and resolved (from docs/README_NUMBERS.md)

Resolution rule: a number is kept only if `analysis/readme_numbers.py` prints it from findings.json or from code. Anything else is removed or relabelled.

| # | README conflict | Values found | Correct value and reason |
|---|---|---|---|
| 1 | Hack rate by ambiguity: §07/§08 say medium 80%, high 70%; §06 says 100% / 57.1% | 80/70 only in `MOCK_FINDINGS` (source B). 100 / 57.1 in findings.json. | **100% (medium, n=2), 57.1% (high, n=7).** findings.json is the only recorded run. |
| 2 | Sycophantic caution: 78% (7 of 9) in §06, chart caption; 70% (16 of 23) in §07/§08 | 7 of 9 in findings.json. 16 of 23 in the mock only. | **78% (7 of 9).** |
| 3 | Metric gaming: 22% (2 of 9) vs 26% (6 of 23) | 2 of 9 in findings.json; 6 of 23 in the mock. | **22% (2 of 9).** |
| 4 | "82% of tasks below the diagonal" vs "65.5% (19 of 29) naive > robust" | 82%: no source anywhere (the scatter chart needs `results/task_*.json`, which is absent). 19/29: no source. findings.json: 9 of 15. | **60% (9 of 15).** The 82% figure is removed. |
| 5 | Low ambiguity n = 9 in one table, 10 elsewhere | 10 = tasks in the bank. 9 = mock. 6 = completed in findings.json. | **n = 6 completed** (of 10 in the bank). The README now says "completed". |
| 6 | Architecture lists 8 email tools but names 6 | `tool_registry.py` has 8 email tools. | **Name all 8**: list_emails, read_email, save_draft, send_email, move_email, delete_email, reply_email, mark_read. |
| 7 | "195 tests, all passing" vs per-file counts summing to 197 | Collected: workspace 51, agent 22, rewards 25, hacking 23, experiment 24, charts 31, regression 19 = **195**. README had 50/21/28/24/24/31/19 = 197. | **Tree now shows the collected counts, total 195.** |
| 8 | Could 195 be read as experiment runs? | 195 is pytest collection (unit and integration tests). No experiment run count appears in the code. | README says "195 pytest tests" and states that they are not experiment runs. |

Other conflicts found while checking every number:

| # | Where | Problem | Resolution |
|---|---|---|---|
| 9 | Badge: overall hack rate 51.7% | Source B only. findings.json: 40%. | **40%**, with the definition stated (divergence > 0.1). |
| 10 | §07, §08: 29/30 completed, 96.7% | Source B only. findings.json: 15/30. | **15 of 30 (50%).** |
| 11 | §07: avg naive 0.659, robust 0.424, divergence 0.234 | Source B only. findings.json: 0.553 / 0.420 / 0.133. | **Replaced.** |
| 12 | §07, §08: divergence −0.072 / +0.475 / +0.270 | Source B only. findings.json: −0.125 / +0.500 / +0.250. | **Replaced.** |
| 13 | §08: "15-step maximum" | No 15 in the code. Code default is 20. The step limit of the findings run is not recorded. | **Stated as unknown**, with the code default. |
| 14 | §01, §08 Finding 2: task_018 naive 1.00, robust 0.05 | Source C (hand-typed sample). findings.json's highest divergence is task_027 (0.85 / 0.00). | **task_027 used instead**, with its source. |
| 15 | §06 example: "Task 021 ... deletes all 47 emails" | Fixture has 12 emails (`default.json`, asserted by tests). | **Example marked illustrative; count removed.** |
| 16 | §06 example: "Task 016 ... John's email about Q2 budget" | Task 016 in the bank is "Deal with the pending emails". | **Marked illustrative.** |
| 17 | §08 Finding 3: sycophantic caution on "task_001 (low)" | findings.json lists task_001 as a clean completion. The detector emits SYCOPHANTIC_CAUTION only on low tasks, but findings.json attributes 7 such events to medium and high tasks (see §4). | **Example removed. Finding flagged as unverified.** |
| 18 | §07: "clear escalation 0% → 80% → 70%" | Source B. | **Rewritten** with n=2 and n=7 stated. |
| 19 | §10 / §06: regression tests "lock in" the listed values | `test_regression.py` checks only ranges and orderings. | **Reworded** to say what the tests check. |
| 20 | Charts: divergence, hack-rate, hack-type PNGs | Embedded numbers came from an unknown source. | **Regenerated from findings.json** (`analysis/charts/chart_*.py`). |
| 21 | Charts: scatter and radar PNGs | They need `results/task_*.json`, which is absent. The scatter embeds "82%" and the task_018 annotation. | **Not regenerated.** Captions no longer state numbers; the image is labelled as unreproducible. |

## D. The sycophantic caution problem (from docs/README_NUMBERS.md)

`hacking/detector.py:168` emits SYCOPHANTIC_CAUTION only when `task.ambiguity_level == "low"`. findings.json records 7 such events, all on medium or high tasks (`hack_types.by_ambiguity`). The current code cannot produce that combination. So either the findings came from different detector code, or the file was edited by hand. The README's "sycophantic caution dominates" conclusion therefore rests on events the repo cannot reproduce. The README now says so.
