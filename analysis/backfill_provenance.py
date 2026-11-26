"""
Backfill run provenance into copies of the schema-7 run files.

The v7 runs (results/runs/<model>/run_01 .. run_10) were written before run_index,
git_commit, git_dirty and returned_model were recorded. This script copies every episode
into results/runs/<model>/backfilled_v7/run_NN/ and adds those fields there. The originals
are not modified.

Sources for each backfilled field are explained in docs/BACKFILL_NOTE.md.

  run_index          the folder name run_NN
  git_commit         the commit HEAD pointed to during the run, found by checking git history
                     against each run's episode timestamps (see verify_commit_window)
  git_dirty          null: not recorded at run time
  returned_model     null: not recorded at run time (see returned_model_unrecorded)

Usage (from the repository root):
  python analysis/backfill_provenance.py --model claude-haiku-5-5 --commit 91705d8
"""

import argparse
import json
import subprocess
from pathlib import Path

EXPECTED_RUNS = 10
EXPECTED_TASKS_PER_RUN = 30
SOURCE_SCHEMA = 7


def backfill_record(record: dict, run_index: int, commit: str) -> dict:
    """Return a copy of a schema-7 episode record with provenance metadata added.
    Raises if the record is not schema 7, so the backfill cannot be applied to the wrong files."""
    version = record["metadata"]["schema_version"]
    if version != SOURCE_SCHEMA:
        raise ValueError(f"expected schema {SOURCE_SCHEMA} to backfill, got {version}")
    out = json.loads(json.dumps(record))  # deep copy
    out["metadata"].update({
        "run_index": run_index,
        "git_commit": commit,
        "commit_backfilled": True,
        "git_dirty": None,
        "returned_model": None,
        "returned_model_unrecorded": True,
    })
    return out


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout.strip()


def verify_commit_window(commit: str, first_ts: str, last_ts: str) -> None:
    """Check that `commit` was HEAD for a run that ran from first_ts to last_ts (ISO timestamps).
    Raises AssertionError with the evidence if not:
      - the newest commit made before the run started is `commit`, and
      - no commit was made while the run was going."""
    before = _git("log", "-1", f"--before={first_ts}", "--format=%H")
    if before != commit:
        raise AssertionError(f"latest commit before the run started is {before}, not {commit}")
    during = _git("log", f"--after={first_ts}", f"--before={last_ts}", "--format=%H")
    if during:
        raise AssertionError(f"commits were made during the run: {during.split()}")


def _load_episodes(run_dir: Path) -> list[tuple[str, dict]]:
    out = []
    for f in sorted(run_dir.glob("task_*.json")):
        out.append((f.name, json.loads(f.read_text(encoding="utf-8"))))
    return out


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--model", required=True)
    p.add_argument("--commit", required=True, help="short or full hash that was HEAD during the runs")
    p.add_argument("--runs-root", default="results/runs")
    args = p.parse_args(argv)

    model_dir = Path(args.runs_root) / args.model
    commit = _git("rev-parse", "--verify", f"{args.commit}^{{commit}}")
    dest_root = model_dir / "backfilled_v7"

    for i in range(1, EXPECTED_RUNS + 1):
        run_name = f"run_{i:02d}"
        src = model_dir / run_name
        episodes = _load_episodes(src)
        if len(episodes) != EXPECTED_TASKS_PER_RUN:
            raise SystemExit(f"{src}: expected {EXPECTED_TASKS_PER_RUN} episodes, found {len(episodes)}")

        stamps = sorted(rec["timestamp"] for _, rec in episodes)
        verify_commit_window(commit, stamps[0], stamps[-1])
        print(f"{run_name}: {len(episodes)} episodes; {commit[:7]} was HEAD from {stamps[0]} to {stamps[-1]}")

        dest = dest_root / run_name
        dest.mkdir(parents=True, exist_ok=True)
        for name, rec in episodes:
            out = backfill_record(rec, i, commit)
            (dest / name).write_text(json.dumps(out, indent=2), encoding="utf-8", newline="\n")

    print(f"wrote {dest_root}")


if __name__ == "__main__":
    main()
