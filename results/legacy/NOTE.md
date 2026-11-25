# Legacy results: `findings_partial_run.json`

- **What it is:** the only findings file that was ever committed to this repository (commit `aae257d`, "Initial commit").
- **Tasks:** 15 of 30 completed (6 low, 2 medium, 7 high).
- **Source run:** unknown. No per-task result files (`results/task_*.json`) or run summary were ever committed, so the numbers cannot be regenerated from this repository.
- **Not reproduced by the demo data:** `analysis/demo_findings.py` sample data gives different numbers (30 tasks, 10/10/10). The commit history shows the README numbers that were copied from test mocks; see docs/ARCHITECTURE_NOTES.md on `main`.
- **Unusable for any claim.** Do not quote, chart, or compare any number in this file. Its source run is unknown, and its labels do not match the current detector: it records `SYCOPHANTIC_CAUTION` on medium and high tasks, which the current detector cannot produce (`hacking/detector.py`, low ambiguity only). Its `hack_rate` definition is not recorded. The charts and regression tests that read it check only its shape and ranges.
- **Kept for history only. This is not current results.** Current results are produced by `run_experiment.py`, then summarised with `python -m analysis.findings --out <path>`, which writes the file you name; the repeated-runs work is tracked separately.
