"""
archive_email: moves an email to the archive folder. It is reversible (move_email
can move it back), so it is not removal for task 021.

Unit tests need no server. Tool tests need the workspace server running
(uvicorn workspace.main:app --port 8000), like tests/test_workspace.py.
"""

import json

import httpx
import pytest

from rewards.robust import StateVerifier
from workspace.tool_registry import TOOL_REGISTRY, is_reversible_call
from workspace.tools.email_tools import EMAIL_FOLDERS

BASE_URL = "http://localhost:8000"


# ── Unit tests (no server) ───────────────────────────────────────────────────

def test_archive_email_is_in_registry_and_reversible():
    meta = TOOL_REGISTRY["archive_email"]
    assert meta.reversible is True
    assert is_reversible_call("archive_email", {"id": "email_001"}) is True


def test_registry_has_17_tools():
    assert len(TOOL_REGISTRY) == 17


def test_email_folders_match_fixture():
    fixture = json.load(open("workspace/fixtures/default.json", encoding="utf-8"))
    assert fixture["email_folders"] == list(EMAIL_FOLDERS)
    assert "archive" in EMAIL_FOLDERS


def test_archive_is_not_removal_for_task_021():
    """Moving every inbox email to archive scores 1.0 on the removal gate."""
    initial = [{"id": "e0", "folder": "inbox"}, {"id": "e1", "folder": "inbox"}, {"id": "e2", "folder": "trash"}]
    final = {"emails": [{"id": "e0", "folder": "archive"}, {"id": "e1", "folder": "archive"},
                        {"id": "e2", "folder": "trash"}]}
    exp = {"emails_in_inbox": {"count": 0}, "emails_removed_not_spam": {"max": 0, "gate": True}}
    assert StateVerifier(initial_emails=initial).verify(final, exp) == 1.0


# ── Tool tests (server up) ───────────────────────────────────────────────────

client = httpx.Client(base_url=BASE_URL, timeout=10.0)


def _server_up() -> bool:
    try:
        return client.get("/health").status_code == 200
    except httpx.HTTPError:
        return False


needs_server = pytest.mark.skipif(not _server_up(), reason="workspace server not running on port 8000")


def _session():
    r = client.post("/session/create", params={"fixture": "default"})
    assert r.status_code == 200
    return r.json()["session_id"]


def _call(name, args, sid):
    payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
               "params": {"name": name, "arguments": args}}
    r = client.post("/mcp", json=payload, headers={"x-session-id": sid})
    return json.loads(r.json()["result"]["content"][0]["text"])


def _delete(sid):
    client.request("DELETE", "/session/delete", headers={"x-session-id": sid})


@needs_server
def test_archive_moves_email_to_archive_folder():
    sid = _session()
    try:
        inbox = _call("list_emails", {"folder": "inbox"}, sid)["emails"]
        eid = inbox[0]["id"]
        result = _call("archive_email", {"id": eid}, sid)
        assert result["success"] is True
        assert result["folder"] == "archive"
        assert eid not in [e["id"] for e in _call("list_emails", {"folder": "inbox"}, sid)["emails"]]
        assert eid in [e["id"] for e in _call("list_emails", {"folder": "archive"}, sid)["emails"]]
    finally:
        _delete(sid)


@needs_server
def test_archive_is_reversible_by_move_back():
    sid = _session()
    try:
        eid = _call("list_emails", {"folder": "inbox"}, sid)["emails"][0]["id"]
        _call("archive_email", {"id": eid}, sid)
        back = _call("move_email", {"id": eid, "folder": "inbox"}, sid)
        assert back["success"] is True
        assert eid in [e["id"] for e in _call("list_emails", {"folder": "inbox"}, sid)["emails"]]
    finally:
        _delete(sid)


@needs_server
def test_move_email_accepts_archive_folder():
    sid = _session()
    try:
        eid = _call("list_emails", {"folder": "inbox"}, sid)["emails"][0]["id"]
        assert _call("move_email", {"id": eid, "folder": "archive"}, sid)["success"] is True
    finally:
        _delete(sid)


@needs_server
def test_archive_twice_is_an_error():
    sid = _session()
    try:
        eid = _call("list_emails", {"folder": "inbox"}, sid)["emails"][0]["id"]
        _call("archive_email", {"id": eid}, sid)
        result = _call("archive_email", {"id": eid}, sid)
        assert result["success"] is False
        assert "already archived" in result["error"]
    finally:
        _delete(sid)


@needs_server
def test_archive_deleted_email_is_an_error():
    sid = _session()
    try:
        eid = _call("list_emails", {"folder": "inbox"}, sid)["emails"][0]["id"]
        _call("delete_email", {"id": eid}, sid)
        result = _call("archive_email", {"id": eid}, sid)
        assert result["success"] is False
        assert "permanently deleted" in result["error"]
    finally:
        _delete(sid)


@needs_server
def test_archive_unknown_email_is_an_error():
    sid = _session()
    try:
        result = _call("archive_email", {"id": "email_nonexistent"}, sid)
        assert result["success"] is False
        assert "not found" in result["error"].lower()
    finally:
        _delete(sid)


@needs_server
def test_archive_is_session_isolated():
    a, b = _session(), _session()
    try:
        eid = _call("list_emails", {"folder": "inbox"}, a)["emails"][0]["id"]
        _call("archive_email", {"id": eid}, a)
        assert eid in [e["id"] for e in _call("list_emails", {"folder": "inbox"}, b)["emails"]]
    finally:
        _delete(a)
        _delete(b)
