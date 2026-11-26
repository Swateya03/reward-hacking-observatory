# Backfill note: run provenance for the v7 runs

The 300 episodes of runs 1–10 (schema 7) were written before the run writer recorded
`run_index`, `git_commit`, `git_dirty` and `returned_model`. They were not re-run.

Paths below are relative to `results/runs/claude-haiku-5-5/`.

- The raw files are `run_NN/task_NNN.json`. They are tracked and were not modified.
- The copies with the fields added are in `backfilled_v7/run_NN/task_NNN.json`. They are not tracked.
  They are rebuilt by `analysis/backfill_provenance.py`.
- Every other field is copied unchanged, and `schema_version` stays 7.

## Reproduce

From the repository root:

```
python analysis/backfill_provenance.py --model claude-haiku-5-5 --commit 91705d8
python analysis/rescore_v8.py --model claude-haiku-5-5 --base results/runs --source-dir results/runs/claude-haiku-5-5/backfilled_v7
```

The second command needs the workspace server running (`uvicorn workspace.main:app --port 8000`).

## Fields

| Field | Value in backfilled copies | Source | Confidence |
|---|---|---|---|
| `run_index` | 1–10 | The folder name `run_NN` the episode was in. | Exact. |
| `git_commit` | `91705d88ad028c93df9147f27f8e8b7a5e9e80cb` | Git history, checked against the episode timestamps (see below). | Inferred, flagged with `commit_backfilled: true`. |
| `commit_backfilled` | `true` | Marks `git_commit` as inferred. | — |
| `git_dirty` | `null` | Not recorded at run time. The tree state during the runs cannot be recovered. | Unknown. |
| `returned_model` | `null` | Not recorded at run time. See the search below. | Unknown. |
| `returned_model_unrecorded` | `true` | Marks `returned_model` as unknown. | — |

### How `git_commit` was found

`91705d8` (“Docs: intermediate excess-calls penalty counts all calls, by design”) was the
newest commit before the first episode of run 1. Then no commit was made until after the last
episode of run 10. `verify_commit_window` in the backfill script checks this for each run:

- the newest commit before the run's first episode is `91705d8`, and
- no commit was made between the run's first and last episode.

Run window (UTC, from the episode `timestamp` fields):

| Run | First episode | Last episode |
|---|---|---|
| run_01 | 17:41:01 | 17:43:29 |
| run_10 | 18:05:41 | 18:08:12 |

The commit before run 1 was `91705d8` at 17:40:41 UTC (23:10:41 IST). The next commit,
`fd4cc62`, was at 18:09:16 UTC, after run 10 ended.

This shows which commit was HEAD. It does not show which files were on disk. If the working tree
had uncommitted edits to tracked files while the runs were going, the code that ran was not
exactly `91705d8`. `git_dirty` is `null` because that cannot be checked now.

### How `returned_model` was searched

Searched for the API's returned model ID in every place a run leaves data:

- `cost_log.jsonl` (1080 rows). Each row has the requested model only (`claude-haiku-5-5`).
  No returned-ID field existed.
- The episode files. Their top-level keys have no response field, and their `metadata` has only
  the requested model.
- `run_summary.json` files and the `dry_run*` folders. Nothing there.
- No raw API responses were saved anywhere under `results/`.

So the returned model ID is unrecoverable for these 300 episodes. The README limitation says so.

## Re-scoring

`rescored_v8/` was regenerated from the backfilled copies with the second command above.
Checked against the v8 files from before the regeneration:

- scores, `hacking`, `completion_type` and `stopped_reason`: identical in all 300 episodes;
- the only metadata changes are the six new keys above, and no existing metadata value changed;
- `results/rescore_v8_report.json` is unchanged.

## For new runs

From this change on, `run_experiment.py` writes `run_index`, `git_commit`, `git_dirty` and
`returned_model` into each episode's `metadata`. It also writes `returned_model` for each call
in `cost_log.jsonl`. These fields are additive: `schema_version` stays 8, and the v8 analysis
reads the same fields as before. A new run's files have no backfill flags.
