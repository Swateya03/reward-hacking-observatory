"""
Run provenance in new result files: run_index, git commit and dirty flag, and the model ID
the API returned (response.model). The API is mocked; no network calls are made.
"""

import json
import os
import subprocess
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agent.provenance import git_provenance
from run_experiment import build_result
from tests.test_build_result import CLEAN, _scores, _task  # reuse the existing fixtures


# ── build_result: the new metadata fields ─────────────────────────────────────

def test_build_result_records_run_provenance_and_returned_model():
    rec = build_result(_task({}), CLEAN, _scores(1.0, 0.5), [], model="claude-haiku-5-5",
                       temperature=None, max_steps=20, max_tokens=2048, thinking={"type": "disabled"},
                       run_index=3, git_commit="a" * 40, git_dirty=False,
                       returned_model="claude-haiku-5-5-20260101")
    md = rec["metadata"]
    assert md["run_index"] == 3
    assert md["git_commit"] == "a" * 40
    assert md["git_dirty"] is False
    assert md["returned_model"] == "claude-haiku-5-5-20260101"
    assert md["model"] == "claude-haiku-5-5"  # the requested model is still recorded separately


def test_build_result_new_fields_default_to_null_when_not_given():
    rec = build_result(_task({}), CLEAN, _scores(1.0, 0.5), [], model="m", temperature=0.1, max_steps=20)
    md = rec["metadata"]
    assert md["run_index"] is None
    assert md["git_commit"] is None
    assert md["git_dirty"] is None
    assert md["returned_model"] is None


# ── client: returned model ID, per call and per episode ──────────────────────

def _response(model="claude-haiku-5-5-20260101"):
    usage = SimpleNamespace(input_tokens=100, output_tokens=20,
                            cache_creation_input_tokens=0, cache_read_input_tokens=0)
    return SimpleNamespace(content=[SimpleNamespace(type="text", text="ok")],
                           stop_reason="end_turn", usage=usage, model=model,
                           model_dump=lambda: {"ok": True})


@pytest.fixture
def client(tmp_path):
    from agent.clients.anthropic_client import AnthropicClient
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}), patch("anthropic.Anthropic") as cls:
        sdk = MagicMock()
        cls.return_value = sdk
        c = AnthropicClient(cost_log_path=tmp_path / "cost_log.jsonl")
        c.sdk = sdk
        yield c


TOOLS = [{"name": "list_files", "description": "List", "inputSchema": {"type": "object"}}]
MSGS = [{"role": "user", "content": "Your task: x"}]


def test_cost_log_records_returned_model_for_each_call(client):
    client.sdk.messages.create.return_value = _response("claude-haiku-5-5-20260101")
    client.set_task("task_001")
    client.call(MSGS, TOOLS, step=1)
    entry = json.loads(client.cost.log_path.read_text().splitlines()[0])
    assert entry["model"] == "claude-haiku-5-5"               # requested
    assert entry["returned_model"] == "claude-haiku-5-5-20260101"  # reported by the API


def test_episode_returned_model_is_the_single_id_when_calls_agree(client):
    client.sdk.messages.create.return_value = _response("claude-haiku-5-5-20260101")
    client.set_task("task_001")
    client.call(MSGS, TOOLS, step=1)
    client.call(MSGS, TOOLS, step=2)
    assert client.episode_returned_model() == "claude-haiku-5-5-20260101"


def test_episode_returned_model_lists_ids_when_calls_disagree(client):
    client.set_task("task_001")
    client.sdk.messages.create.side_effect = [_response("id-a"), _response("id-b"), _response("id-a")]
    for step in (1, 2, 3):
        client.call(MSGS, TOOLS, step=step)
    assert client.episode_returned_model() == ["id-a", "id-b"]


def test_returned_model_is_reset_for_each_task(client):
    client.sdk.messages.create.return_value = _response("id-a")
    client.set_task("task_001")
    client.call(MSGS, TOOLS, step=1)
    client.set_task("task_002")
    assert client.episode_returned_model() is None


def test_missing_or_non_string_model_is_recorded_as_null(client):
    client.set_task("task_001")
    no_model = _response()
    del no_model.model
    client.sdk.messages.create.return_value = no_model
    client.call(MSGS, TOOLS, step=1)
    client.sdk.messages.create.return_value = _response(model=MagicMock())  # not a string
    client.call(MSGS, TOOLS, step=2)
    assert client.episode_returned_model() is None
    entries = [json.loads(line) for line in client.cost.log_path.read_text().splitlines()]
    assert all(e["returned_model"] is None for e in entries)


# ── git provenance ───────────────────────────────────────────────────────────

def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    _git(tmp_path, "config", "user.name", "test")
    (tmp_path / "tracked.txt").write_text("one", encoding="utf-8")
    _git(tmp_path, "add", "tracked.txt")
    _git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


def test_provenance_clean_repo_reports_head_and_not_dirty(repo):
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()
    assert git_provenance(repo) == {"git_commit": head, "git_dirty": False}
    assert len(head) == 40


def test_provenance_untracked_file_does_not_mark_tree_dirty(repo):
    (repo / "new_output.json").write_text("{}", encoding="utf-8")
    assert git_provenance(repo)["git_dirty"] is False


def test_provenance_modified_tracked_file_marks_tree_dirty(repo):
    (repo / "tracked.txt").write_text("changed", encoding="utf-8")
    assert git_provenance(repo)["git_dirty"] is True


def test_provenance_outside_a_repository_is_null_not_an_error(tmp_path):
    plain = tmp_path / "not_a_repo"
    plain.mkdir()
    assert git_provenance(plain) == {"git_commit": None, "git_dirty": None}
