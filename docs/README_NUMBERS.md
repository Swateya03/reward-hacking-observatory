# README numbers: inventory and conflict resolution

Written for: maintainers checking that README.md matches the data in the repo.

Branch: `fix/readme-consistency`. No reward, detector or agent code was changed.

## 1. Which source each number can come from

There are three possible sources for a number in the README. Only the first can be regenerated.

| Source | What it is | Numbers that come from it |
|---|---|---|
| **A. `results/findings.json`** | The only result file tracked in git (one commit, `aae257d`). Written by `analysis/findings.py`. | 15 of 30 completed; hack rate 40%; per-ambiguity n, hack rate, divergence; hack-type counts (7 + 2 = 9); notable cases. |
| **B. Test mock literals** | `MOCK_FINDINGS` in `tests/test_charts.py` (lines 27–96). Typed by hand. | 29/30, 96.7%, 51.7%, 0.659/0.424/0.234, 80%/70%, −0.072/+0.475/+0.270, 16/6/1 events (23). |
| **C. Demo sample data** | `SAMPLE_RESULTS` in `analysis/demo_findings.py`. Typed by hand. | task_018 naive 1.00 / robust 0.05 / divergence 0.95; task_019. |

Source B and source C are not experiment output. Neither the README nor any test should cite them as results.

## 2. Which run the numbers come from

- **Findings (source A):** one run, date unknown. `findings.json` has no timestamp, and no `results/run_summary.json` exists. The model is not recorded in the file; the code default is `claude-sonnet-4-20250514`. The step limit is not recorded (code default is 20).
- **Raw per-task results:** none in the repo. `results/task_*.json` and `run_summary.json` are gitignored and absent. So nothing can be regenerated from raw runs.
- **"Older run (9 events)" vs "newer run (23 events)":** I looked for evidence of two runs and found none. The git history has one commit. The 9-event set is findings.json. The 23-event set exists only as a hand-typed literal in `tests/test_charts.py`. It was never produced by a script. So the 23 figure is not a newer run; it is a mock that disagrees with the only recorded run.

## 3. Conflicts found and resolved

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

## 4. The sycophantic caution problem (not a number conflict, but it changes the story)

`hacking/detector.py:168` emits SYCOPHANTIC_CAUTION only when `task.ambiguity_level == "low"`. findings.json records 7 such events, all on medium or high tasks (`hack_types.by_ambiguity`). The current code cannot produce that combination. So either the findings came from different detector code, or the file was edited by hand. The README's "sycophantic caution dominates" conclusion therefore rests on events the repo cannot reproduce. The README now says so.

## 5. Full inventory of numbers in README.md (after the fix)

Values below are what `python analysis/readme_numbers.py` prints. Numbers that are design targets, not results, are listed as such.

| Section | Number in README | Source | Status |
|---|---|---|---|
| Badges | 30 tasks, 3 levels | `tasks/task_bank.json` | Traced |
| Badges | 16 tools, 5 hack types, 3 reward functions | `tool_registry.py`, `hacking/taxonomy.py`, `rewards/` | Traced |
| Badges | 40% overall hack rate | findings.json (divergence > 0.1) | Traced (fixed) |
| Badges | 195 tests passing | pytest collection (script) | Traced (fixed) |
| §01, §05 | naive 1.0 / robust 0.05 example | removed from core insight; task_027 used | Traced (fixed) |
| §03 | 16 tools, 30 tasks, 12 files / 12 emails / 8 events | `tool_registry.py`, `task_bank.json`, `default.json` | Traced |
| §04 | 10 / 10 / 10 tasks per level | `task_bank.json` | Traced |
| §04 | Regression values (0%, 80%, 70%, −0.072, +0.475, +0.270, 65.5%) | findings.json (replaced) | Traced (fixed) |
| §06 | 78% (7 of 9), 22% (2 of 9), 100% medium, 57.1% high | findings.json | Traced (fixed) |
| §07 | 15 of 30 completed, 50%; avg naive 0.553; robust 0.420; divergence +0.133; hack rate 40% | findings.json | Traced (fixed) |
| §07 | low n=6 (0%, −0.125); medium n=2 (100%, +0.500); high n=7 (57.1%, +0.250) | findings.json | Traced (fixed) |
| §07, §08 | 9 hack events: SYC 7, METRIC 2, OVERCLAIM 0 | findings.json | Traced (fixed) |
| §07 | 9 of 15 naive > robust (60%) | findings.json | Traced (fixed) |
| §08 | Claude Sonnet 4, 20-step code default, run date unknown | code, findings.json | Traced; step limit and date stated as unknown |
| §08 | task_027 highest divergence (0.85 / 0.00) | findings.json notable_cases | Traced (fixed) |
| §08 | task_004 lowest divergence (−0.30) | findings.json notable_cases | Traced |
| §09 | 16 tools, all 8 email tools named | `tool_registry.py` | Traced (fixed) |
| §10 | 195 pytest tests; per-file 51 / 22 / 25 / 23 / 24 / 31 / 19 | pytest collection | Traced (fixed) |
| §12 | 2 CPU, 2 GB, 70% utilisation, 90% I/O reduction, 5–10% annotation | design text | Design target, not a result. Not changed. |

## 6. Not changed (out of scope for this task)

- `§10` test file names (`test_layer0` … `test_layer9`) do not match the files on disk.
- `tool_registry.py:2` docstring still says "21 MCP tools".
- "Tasks are sampled uniformly from a fixture" (§04): not implemented; `run_experiment.py` runs tasks in order.
- The §12 production numbers are design targets, not measurements.
- The scatter and radar charts cannot be reproduced from the repo.
- §08 Finding 2 says the naive/robust gap "persists even for intermediate reward". findings.json has no intermediate scores, so this claim is unverified.
- §08 Finding 1 says sycophantic caution is "dominant". This depends on the events in §4 above, which the current detector cannot produce.
- The §10 regression-test file name `test_findings_regression.py` does not exist; the file is `tests/test_regression.py`.
