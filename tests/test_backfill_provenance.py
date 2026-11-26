"""Tests for analysis/backfill_provenance.py. Uses a temporary git repository with fixed commit dates."""

import copy
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analysis"))
import backfill_provenance as bp  # noqa: E402


def _record(schema=7):
    return {
        "task_id": "task_001",
        "completion_type": "completion",
        "scores": {"naive": 1.0},
        "metadata": {"schema_version": schema, "model": "claude-haiku-5-5", "temperature": None,
                     "max_steps": 20, "max_tokens": 2048, "thinking": {"type": "disabled"}},
    }


def test_backfill_adds_provenance_and_keeps_everything_else():
    original = _record()
    before = copy.deepcopy(original)
    out = bp.backfill_record(original, run_index=4, commit="abc123")
    assert out["metadata"] == {
        "schema_version": 7, "model": "claude-haiku-5-5", "temperature": None,
        "max_steps": 20, "max_tokens": 2048, "thinking": {"type": "disabled"},
        "run_index": 4, "git_commit": "abc123", "commit_backfilled": True,
        "git_dirty": None, "returned_model": None, "returned_model_unrecorded": True,
    }
    assert {k: v for k, v in out.items() if k != "metadata"} == {k: v for k, v in before.items() if k != "metadata"}
    assert original == before  # the input is not modified


def test_backfill_refuses_a_record_that_is_not_schema_7():
    with pytest.raises(ValueError, match="expected schema 7"):
        bp.backfill_record(_record(schema=8), run_index=1, commit="abc")


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A repo with one commit at 2026-01-01 UTC, and the working directory set to it."""
    env = {**os.environ, "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z",
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, env=env)
    (tmp_path / "f.txt").write_text("1", encoding="utf-8")
    subprocess.run(["git", "add", "f.txt"], cwd=tmp_path, check=True, env=env)
    subprocess.run(["git", "commit", "-q", "-m", "one"], cwd=tmp_path, check=True, env=env)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True,
                          check=True).stdout.strip()
    monkeypatch.chdir(tmp_path)
    return tmp_path, head, env


def test_commit_window_passes_when_no_commit_was_made_during_the_run(repo):
    _, head, _ = repo
    bp.verify_commit_window(head, "2026-01-02T10:00:00+00:00", "2026-01-02T11:00:00+00:00")


def test_commit_window_fails_when_a_different_commit_was_newest_before_the_run(repo):
    _, head, env = repo
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "two"], cwd=repo[0], check=True,
                   env={**env, "GIT_AUTHOR_DATE": "2026-01-01T12:00:00Z", "GIT_COMMITTER_DATE": "2026-01-01T12:00:00Z"})
    with pytest.raises(AssertionError, match="latest commit before the run started"):
        bp.verify_commit_window(head, "2026-01-02T10:00:00+00:00", "2026-01-02T11:00:00+00:00")


def test_commit_window_fails_when_a_commit_landed_during_the_run(repo):
    _, head, env = repo
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "during"], cwd=repo[0], check=True,
                   env={**env, "GIT_AUTHOR_DATE": "2026-01-02T10:30:00Z", "GIT_COMMITTER_DATE": "2026-01-02T10:30:00Z"})
    # the run window is 10:00-11:00; the commit at 10:30 is inside it. `head` was the newest commit before the run.
    with pytest.raises(AssertionError, match="commits were made during the run"):
        bp.verify_commit_window(head, "2026-01-02T10:00:00+00:00", "2026-01-02T11:00:00+00:00")
