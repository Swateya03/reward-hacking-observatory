# Legacy results: `findings_partial_run.json`

- **What it is:** the only findings file that was ever committed to this repository (commit `aae257d`, "Initial commit").
- **Tasks:** 15 of 30 completed (6 low, 2 medium, 7 high).
- **Source run:** unknown. No per-task result files (`results/task_*.json`) or run summary were ever committed, so the numbers cannot be regenerated from this repository.
- **Not reproduced by the demo data:** `analysis/demo_findings.py` sample data gives different numbers (30 tasks, 10/10/10). The commit history shows the README numbers that were copied from test mocks; see docs/ARCHITECTURE_NOTES.md on branch docs/architecture-notes.
- **Kept for history only. This is not current results.** Current results are produced by `run_experiment.py` -> `analysis/findings.py`, which write new files; the repeated-runs work is tracked separately.
