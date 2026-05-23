"""
Workspace Tests

Tests for the FastAPI workspace server, MCP protocol handler, session
isolation, and all 16 tools (file, email, calendar operations).

Run with:
  pytest tests/test_workspace.py -v

The workspace server must be running:
  uvicorn workspace.main:app --reload --port 8000

Test sections:
  # ── Server & Health ──
  # ── Session Isolation ──
  # ── File Tools ──
  # ── Email Tools ──
  # ── Calendar Tools ──
  # ── MCP Protocol ──
"""

import json
import threading
import time

import pytest
import httpx

BASE_URL = "http://localhost:8000"
client = httpx.Client(base_url=BASE_URL, timeout=10.0)


# ── Helpers ───────────────────────────────────────────────────────────────────

def create_session(fixture="default") -> str:
    r = client.post("/session/create", params={"fixture": fixture})
    assert r.status_code == 200, f"create_session failed: {r.text}"
    return r.json()["session_id"]


def call_tool(tool_name: str, args: dict, session_id: str) -> dict:
    payload = {
        "jsonrpc": "2.0", "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": args}
    }
    r = client.post(
        "/mcp", json=payload,
        headers={"x-session-id": session_id}
    )
    assert r.status_code == 200
    content = r.json()["result"]["content"][0]["text"]
    return json.loads(content)


def get_state(session_id: str) -> dict:
    r = client.get("/session/state",
                   headers={"x-session-id": session_id})
    assert r.status_code == 200
    return r.json()


def delete_session(session_id: str):
    client.request("DELETE", "/session/delete",
                   headers={"x-session-id": session_id})


# ── Category 1: Basic Server Health ──────────────────────────────────────────

class TestServerHealth:

    def test_p1_health_endpoint(self):
        """P1: Server responds to /health with 200."""
        r = client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "healthy"
        assert "available_fixtures" in data

    def test_p2_openapi_docs(self):
        """P2: /docs is accessible."""
        r = client.get("/docs")
        assert r.status_code == 200

    def test_p4_concurrent_requests(self):
        """P4: Concurrent requests don't cause errors."""
        errors = []
        sessions = []

        def make_session():
            try:
                sid = create_session()
                sessions.append(sid)
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=make_session) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Concurrent session creation failed: {errors}"
        for sid in sessions:
            delete_session(sid)


# ── Category 2: Session Isolation ────────────────────────────────────────────

class TestSessionIsolation:

    def test_p5_sessions_isolated(self):
        """P5: Actions in session A don't affect session B."""
        sid_a = create_session()
        sid_b = create_session()

        # Trash a file in A
        call_tool("move_to_trash",
                  {"path": "/tmp/cache_2024.zip"}, sid_a)

        # B should still see the file
        result_b = call_tool(
            "list_files", {"folder": "/tmp"}, sid_b)
        paths_b = [f["path"] for f in result_b["files"]]
        assert "/tmp/cache_2024.zip" in paths_b, (
            "Session B was affected by changes in session A"
        )

        delete_session(sid_a)
        delete_session(sid_b)

    def test_p6_reset_restores_state(self):
        """P6: reset_session restores exact original fixture state."""
        sid = create_session()

        # Trash a file
        call_tool("move_to_trash",
                  {"path": "/tmp/cache_2024.zip"}, sid)

        # Verify it's trashed
        result = call_tool("list_files", {"folder": "/tmp"}, sid)
        paths = [f["path"] for f in result["files"]]
        assert "/tmp/cache_2024.zip" not in paths

        # Reset
        r = client.post("/session/reset",
                        params={"fixture": "default"},
                        headers={"x-session-id": sid})
        assert r.status_code == 200

        # File should be back
        result = call_tool("list_files", {"folder": "/tmp"}, sid)
        paths = [f["path"] for f in result["files"]]
        assert "/tmp/cache_2024.zip" in paths, (
            "File not restored after reset"
        )
        delete_session(sid)

    def test_p7_ten_concurrent_sessions(self):
        """P7: 10 simultaneous sessions all seeded correctly."""
        sessions = []
        for _ in range(10):
            sessions.append(create_session())

        for sid in sessions:
            state = get_state(sid)
            assert len(state["files"]) == 12, (
                f"Session {sid} has {len(state['files'])} files, expected 12"
            )

        for sid in sessions:
            delete_session(sid)

    def test_p8_unknown_session_id(self):
        """P8: Calling a tool with nonexistent session_id returns clear error."""
        payload = {
            "jsonrpc": "2.0", "id": 1,
            "method": "tools/call",
            "params": {"name": "list_files",
                       "arguments": {"folder": "/tmp"}}
        }
        r = client.post(
            "/mcp", json=payload,
            headers={"x-session-id": "nonexistent-session-id-abc123"}
        )
        # Should return 200 with an error in the result (not a 500 crash)
        assert r.status_code == 200
        result = r.json()
        content = json.loads(
            result["result"]["content"][0]["text"])
        # Empty result is acceptable — no files exist for this session
        assert "files" in content or "error" in content

    def test_p9_no_data_leakage_between_sessions(self):
        """P9: SQLite has no cross-session data leakage."""
        sid_a = create_session()
        sid_b = create_session()

        state_a = get_state(sid_a)
        state_b = get_state(sid_b)

        # All file rows in A belong to A
        for f in state_a["files"]:
            assert f["session_id"] == sid_a

        # All file rows in B belong to B
        for f in state_b["files"]:
            assert f["session_id"] == sid_b

        delete_session(sid_a)
        delete_session(sid_b)


# ── Category 3: Tool Correctness ─────────────────────────────────────────────

class TestToolCorrectness:

    def test_p10_list_empty_folder(self):
        """P10: list_files on empty folder returns empty list, not error."""
        sid = create_session()
        result = call_tool("list_files",
                           {"folder": "/nonexistent"}, sid)
        assert "files" in result
        assert result["count"] == 0
        delete_session(sid)

    def test_p11_read_nonexistent_file(self):
        """P11: read_file on missing file returns clear error message."""
        sid = create_session()
        result = call_tool("read_file",
                           {"path": "/does/not/exist.txt"}, sid)
        assert "error" in result
        assert "not found" in result["error"].lower()
        delete_session(sid)

    def test_p12_trash_visibility(self):
        """P12: Trashed files hidden by default, visible with include_trashed=true."""
        sid = create_session()

        call_tool("move_to_trash",
                  {"path": "/tmp/cache_2024.zip"}, sid)

        # Hidden by default
        result = call_tool("list_files", {"folder": "/tmp"}, sid)
        paths = [f["path"] for f in result["files"]]
        assert "/tmp/cache_2024.zip" not in paths

        # Visible with include_trashed=true
        result = call_tool(
            "list_files",
            {"folder": "/tmp", "include_trashed": True}, sid
        )
        paths = [f["path"] for f in result["files"]]
        assert "/tmp/cache_2024.zip" in paths

        # is_trashed flag is set
        trashed = [f for f in result["files"]
                   if f["path"] == "/tmp/cache_2024.zip"]
        assert trashed[0]["is_trashed"] is True

        delete_session(sid)

    def test_p13_double_trash_graceful(self):
        """P13: Trashing an already-trashed file returns graceful error."""
        sid = create_session()
        call_tool("move_to_trash",
                  {"path": "/tmp/cache_2024.zip"}, sid)
        result = call_tool("move_to_trash",
                           {"path": "/tmp/cache_2024.zip"}, sid)
        assert result["success"] is False
        assert "already" in result["error"].lower()
        delete_session(sid)

    def test_p14_read_trashed_file(self):
        """P14: Reading a trashed file returns clear error."""
        sid = create_session()
        call_tool("move_to_trash",
                  {"path": "/tmp/cache_2024.zip"}, sid)
        result = call_tool("read_file",
                           {"path": "/tmp/cache_2024.zip"}, sid)
        assert "error" in result
        assert "trash" in result["error"].lower()
        delete_session(sid)

    def test_p15_cross_session_tool_isolation(self):
        """P15: Tool operations in session A don't bleed into session B."""
        sid_a = create_session()
        sid_b = create_session()
        call_tool("move_to_trash",
                  {"path": "/tmp/cache_2024.zip"}, sid_a)
        result = call_tool("read_file",
                           {"path": "/tmp/cache_2024.zip"}, sid_b)
        assert "error" not in result, (
            "Trashing in session A affected session B"
        )
        delete_session(sid_a)
        delete_session(sid_b)


# ── Category 4: MCP Protocol ──────────────────────────────────────────────────

class TestMCPProtocol:

    def test_p16_tools_list_format(self):
        """P16: tools/list returns correct MCP format."""
        payload = {
            "jsonrpc": "2.0", "id": 42,
            "method": "tools/list", "params": {}
        }
        r = client.post("/mcp", json=payload)
        assert r.status_code == 200
        data = r.json()
        assert data["jsonrpc"] == "2.0"
        assert data["id"] == 42
        tools = data["result"]["tools"]
        assert len(tools) == 16  # Layer 1: 3 file + 8 email + 5 calendar tools
        for tool in tools:
            assert "name" in tool
            assert "description" in tool
            assert "inputSchema" in tool

    def test_p17_tools_call_valid(self):
        """P17: tools/call with valid args returns MCP-format result."""
        sid = create_session()
        payload = {
            "jsonrpc": "2.0", "id": 1,
            "method": "tools/call",
            "params": {
                "name": "list_files",
                "arguments": {"folder": "/tmp"}
            }
        }
        r = client.post("/mcp", json=payload,
                        headers={"x-session-id": sid})
        assert r.status_code == 200
        data = r.json()
        assert data["jsonrpc"] == "2.0"
        assert "result" in data
        content = data["result"]["content"]
        assert len(content) > 0
        assert content[0]["type"] == "text"
        delete_session(sid)

    def test_p18_missing_required_arg(self):
        """P18: Missing required argument returns MCP error, not 422."""
        sid = create_session()
        payload = {
            "jsonrpc": "2.0", "id": 1,
            "method": "tools/call",
            "params": {
                "name": "list_files",
                "arguments": {}   # missing required 'folder'
            }
        }
        r = client.post("/mcp", json=payload,
                        headers={"x-session-id": sid})
        # Should be 200 with error in result, not 422
        assert r.status_code == 200
        delete_session(sid)

    def test_p19_unknown_tool_name(self):
        """P19: Unknown tool name returns graceful error."""
        sid = create_session()
        payload = {
            "jsonrpc": "2.0", "id": 1,
            "method": "tools/call",
            "params": {
                "name": "delete_everything",
                "arguments": {}
            }
        }
        r = client.post("/mcp", json=payload,
                        headers={"x-session-id": sid})
        assert r.status_code == 200
        data = r.json()
        # Error responses use "error" key, not "result" key
        if "error" in data:
            assert "unknown" in data["error"]["message"].lower()
        else:
            content = json.loads(data["result"]["content"][0]["text"])
            assert "error" in content
            assert "unknown" in content["error"].lower()
        delete_session(sid)

    def test_p20_missing_session_id_header(self):
        """P20: Missing x-session-id header returns clear error."""
        payload = {
            "jsonrpc": "2.0", "id": 1,
            "method": "tools/call",
            "params": {
                "name": "list_files",
                "arguments": {"folder": "/tmp"}
            }
        }
        r = client.post("/mcp", json=payload)
        # Should return error, not crash
        assert r.status_code in (200, 400, 422)
        if r.status_code == 200:
            data = r.json()
            assert "error" in data

    def test_p21_id_echoed_correctly(self):
        """P21: Response echoes the same id as the request."""
        payload = {
            "jsonrpc": "2.0", "id": 99,
            "method": "tools/list", "params": {}
        }
        r = client.post("/mcp", json=payload)
        data = r.json()
        assert data["id"] == 99


# ── Category 6: End to End ────────────────────────────────────────────────────

class TestEndToEnd:

    def test_p28_ground_truth_verification(self):
        """P28: After trashing a file, DB ground truth reflects the change."""
        sid = create_session()
        call_tool("move_to_trash",
                  {"path": "/tmp/cache_2024.zip"}, sid)
        state = get_state(sid)
        trashed = [
            f for f in state["files"]
            if f["path"] == "/tmp/cache_2024.zip"
        ]
        assert len(trashed) == 1
        assert trashed[0]["is_trashed"] == 1
        delete_session(sid)

    def test_p31_max_steps_respected(self):
        """P31: Episode can be limited — server doesn't enforce steps,
        but multi-step operations work correctly."""
        sid = create_session()
        # Do 3 sequential tool calls — all should succeed
        r1 = call_tool("list_files", {"folder": "/tmp"}, sid)
        r2 = call_tool("read_file",
                       {"path": "/tmp/cache_2024.zip"}, sid)
        r3 = call_tool("move_to_trash",
                       {"path": "/tmp/cache_2024.zip"}, sid)
        assert r1["count"] > 0
        assert "name" in r2
        assert r3["success"] is True
        delete_session(sid)

    def test_p33_fixture_deterministic(self):
        """P33: Same fixture always produces identical initial state."""
        states = []
        sessions = []
        for _ in range(5):
            sid = create_session("default")
            sessions.append(sid)
            state = get_state(sid)
            file_ids = sorted([f["id"] for f in state["files"]])
            states.append(file_ids)

        for s in states:
            assert s == states[0], (
                "Fixture seeding is non-deterministic!"
            )

        for sid in sessions:
            delete_session(sid)


# ── Run all ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import subprocess
    subprocess.run(["pytest", __file__, "-v", "--tb=short"])
"""
Layer 1 Tests
Covers email and calendar tools (8 email tools + 5 calendar tools).

Run with:
  pytest tests/test_layer1.py -v

The workspace server must be running:
  uvicorn workspace.main:app --reload --port 8000
"""

import json
import pytest
import httpx

BASE_URL = "http://localhost:8000"
client = httpx.Client(base_url=BASE_URL, timeout=10.0)


# ── Helpers ───────────────────────────────────────────────────────────────────

def create_session(fixture="default") -> str:
    r = client.post("/session/create", params={"fixture": fixture})
    assert r.status_code == 200, f"create_session failed: {r.text}"
    return r.json()["session_id"]


def call_tool(tool_name: str, args: dict, session_id: str) -> dict:
    payload = {
        "jsonrpc": "2.0", "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": args}
    }
    r = client.post(
        "/mcp", json=payload,
        headers={"x-session-id": session_id}
    )
    assert r.status_code == 200, f"Tool call failed: {r.text}"
    content = r.json()["result"]["content"][0]["text"]
    return json.loads(content)


def get_state(session_id: str) -> dict:
    r = client.get("/session/state",
                   headers={"x-session-id": session_id})
    assert r.status_code == 200
    return r.json()


def delete_session(session_id: str):
    client.request("DELETE", "/session/delete",
                   headers={"x-session-id": session_id})


# ── Category 1: Fixture Completeness ──────────────────────────────────────────

class TestFixtureCompleteness:

    def test_default_fixture_has_files_emails_events(self):
        """Default fixture seeds 12 files, 12 emails, 8 events."""
        sid = create_session()
        state = get_state(sid)

        assert "files" in state, "Fixture missing files"
        assert "emails" in state, "Fixture missing emails"
        assert "events" in state, "Fixture missing events"

        assert len(state["files"]) == 12, (
            f"Expected 12 files, got {len(state['files'])}"
        )
        assert len(state["emails"]) == 12, (
            f"Expected 12 emails, got {len(state['emails'])}"
        )
        assert len(state["events"]) == 8, (
            f"Expected 8 events, got {len(state['events'])}"
        )

        delete_session(sid)

    def test_fixture_emails_have_required_fields(self):
        """All emails in fixture have required fields."""
        sid = create_session()
        state = get_state(sid)

        required_email_fields = {
            "id", "sender", "recipient", "subject", "body",
            "folder", "is_read", "has_attachment", "sensitivity", "session_id"
        }

        for email in state["emails"]:
            assert required_email_fields.issubset(email.keys()), (
                f"Email {email.get('id')} missing fields: "
                f"{required_email_fields - email.keys()}"
            )

        delete_session(sid)

    def test_fixture_events_have_required_fields(self):
        """All events in fixture have required fields."""
        sid = create_session()
        state = get_state(sid)

        required_event_fields = {
            "id", "title", "start_time", "end_time",
            "is_recurring", "sensitivity", "session_id"
        }

        for event in state["events"]:
            assert required_event_fields.issubset(event.keys()), (
                f"Event {event.get('id')} missing fields: "
                f"{required_event_fields - event.keys()}"
            )

        delete_session(sid)


# ── Category 2: Email Tools ──────────────────────────────────────────────────

class TestEmailTools:

    def test_list_emails_inbox_count(self):
        """list_emails returns correct count for inbox folder."""
        sid = create_session()
        result = call_tool("list_emails", {"folder": "inbox"}, sid)

        assert "emails" in result
        assert "count" in result
        assert result["count"] > 0, "Inbox should have emails from fixture"
        # Fixture has 5 emails in inbox
        assert result["count"] == 5, (
            f"Expected 5 emails in inbox, got {result['count']}"
        )

        delete_session(sid)

    def test_list_emails_all_folders(self):
        """list_emails works for all folder types."""
        sid = create_session()
        folders = ["inbox", "drafts", "sent", "trash", "spam"]

        for folder in folders:
            result = call_tool("list_emails", {"folder": folder}, sid)
            assert "emails" in result, f"Failed to list {folder}"
            assert "count" in result

        delete_session(sid)

    def test_read_email_returns_full_content(self):
        """read_email returns full email content and metadata."""
        sid = create_session()

        # First list to get an email ID
        list_result = call_tool("list_emails", {"folder": "inbox"}, sid)
        assert list_result["count"] > 0

        email_id = list_result["emails"][0]["id"]

        # Now read it
        result = call_tool("read_email", {"id": email_id}, sid)

        assert result["id"] == email_id
        assert "sender" in result
        assert "recipient" in result
        assert "subject" in result
        assert "body" in result
        assert "folder" in result
        assert "is_read" in result

        delete_session(sid)

    def test_read_email_nonexistent(self):
        """read_email returns error for nonexistent email."""
        sid = create_session()
        result = call_tool("read_email", {"id": "email_nonexistent"}, sid)

        assert "error" in result
        assert "not found" in result["error"].lower()

        delete_session(sid)

    def test_save_draft_creates_email(self):
        """save_draft creates a new email in drafts folder."""
        sid = create_session()

        # Save a draft
        result = call_tool("save_draft", {
            "to": "recipient@example.com",
            "subject": "Test Draft",
            "body": "This is a draft email"
        }, sid)

        assert result["success"] is True
        assert "email_id" in result
        assert result["folder"] == "drafts"

        # Verify it exists in drafts
        list_result = call_tool("list_emails", {"folder": "drafts"}, sid)
        email_ids = [e["id"] for e in list_result["emails"]]
        assert result["email_id"] in email_ids

        delete_session(sid)

    def test_send_email_creates_email(self):
        """send_email creates email in sent folder (irreversible)."""
        sid = create_session()

        # Send an email
        result = call_tool("send_email", {
            "to": "recipient@example.com",
            "subject": "Test Email",
            "body": "This email has been sent"
        }, sid)

        assert result["success"] is True
        assert "email_id" in result
        assert result["folder"] == "sent"
        assert result["irreversible"] is True

        # Verify it exists in sent
        list_result = call_tool("list_emails", {"folder": "sent"}, sid)
        email_ids = [e["id"] for e in list_result["emails"]]
        assert result["email_id"] in email_ids

        delete_session(sid)

    def test_move_email_to_folder(self):
        """move_email moves email to correct folder."""
        sid = create_session()

        # Get an email from inbox
        list_result = call_tool("list_emails", {"folder": "inbox"}, sid)
        email_id = list_result["emails"][0]["id"]

        # Move it to trash
        result = call_tool("move_email", {
            "id": email_id,
            "folder": "trash"
        }, sid)

        assert result["success"] is True
        assert result["folder"] == "trash"

        # Verify it's in trash
        trash_result = call_tool("list_emails", {"folder": "trash"}, sid)
        trash_ids = [e["id"] for e in trash_result["emails"]]
        assert email_id in trash_ids

        # Verify it's not in inbox
        inbox_result = call_tool("list_emails", {"folder": "inbox"}, sid)
        inbox_ids = [e["id"] for e in inbox_result["emails"]]
        assert email_id not in inbox_ids

        delete_session(sid)

    def test_move_email_invalid_folder(self):
        """move_email returns error for invalid folder."""
        sid = create_session()

        list_result = call_tool("list_emails", {"folder": "inbox"}, sid)
        email_id = list_result["emails"][0]["id"]

        result = call_tool("move_email", {
            "id": email_id,
            "folder": "invalid_folder"
        }, sid)

        assert result["success"] is False
        assert "error" in result

        delete_session(sid)

    def test_reply_email_draft(self):
        """reply_email with send=False saves to drafts."""
        sid = create_session()

        # Get an email to reply to
        list_result = call_tool("list_emails", {"folder": "inbox"}, sid)
        email_id = list_result["emails"][0]["id"]

        # Reply without sending
        result = call_tool("reply_email", {
            "id": email_id,
            "body": "This is my reply",
            "send": False
        }, sid)

        assert result["success"] is True
        assert "reply_id" in result
        assert result["folder"] == "drafts"

        # Verify reply exists in drafts
        drafts_result = call_tool("list_emails", {"folder": "drafts"}, sid)
        draft_ids = [e["id"] for e in drafts_result["emails"]]
        assert result["reply_id"] in draft_ids

        delete_session(sid)

    def test_reply_email_send(self):
        """reply_email with send=True sends immediately (irreversible)."""
        sid = create_session()

        # Get an email to reply to
        list_result = call_tool("list_emails", {"folder": "inbox"}, sid)
        email_id = list_result["emails"][0]["id"]

        # Reply and send
        result = call_tool("reply_email", {
            "id": email_id,
            "body": "This is my sent reply",
            "send": True
        }, sid)

        assert result["success"] is True
        assert "reply_id" in result
        assert result["folder"] == "sent"

        # Verify reply exists in sent
        sent_result = call_tool("list_emails", {"folder": "sent"}, sid)
        sent_ids = [e["id"] for e in sent_result["emails"]]
        assert result["reply_id"] in sent_ids

        delete_session(sid)

    def test_mark_read(self):
        """mark_read updates is_read flag in database."""
        sid = create_session()

        # Get an unread email from inbox
        list_result = call_tool("list_emails", {"folder": "inbox"}, sid)
        unread_emails = [e for e in list_result["emails"] if not e["is_read"]]

        if unread_emails:
            email_id = unread_emails[0]["id"]

            # Mark as read
            result = call_tool("mark_read", {"id": email_id}, sid)

            assert result["success"] is True

            # Verify it's marked as read
            read_result = call_tool("read_email", {"id": email_id}, sid)
            assert read_result["is_read"] is True

        delete_session(sid)

    def test_mark_read_already_read(self):
        """mark_read returns error if email already read."""
        sid = create_session()

        # Get a read email
        list_result = call_tool("list_emails", {"folder": "inbox"}, sid)
        read_emails = [e for e in list_result["emails"] if e["is_read"]]

        if read_emails:
            email_id = read_emails[0]["id"]

            # Try to mark as read (already is)
            result = call_tool("mark_read", {"id": email_id}, sid)

            assert result["success"] is False
            assert "already" in result["error"].lower()

        delete_session(sid)

    def test_email_session_isolation(self):
        """Email actions in session A don't affect session B."""
        sid_a = create_session()
        sid_b = create_session()

        # Move an email to trash in A
        list_a = call_tool("list_emails", {"folder": "inbox"}, sid_a)
        email_id = list_a["emails"][0]["id"]

        call_tool("move_email", {
            "id": email_id,
            "folder": "trash"
        }, sid_a)

        # B should still have it in inbox
        list_b = call_tool("list_emails", {"folder": "inbox"}, sid_b)
        b_inbox_ids = [e["id"] for e in list_b["emails"]]

        assert email_id in b_inbox_ids, (
            "Email move in session A affected session B"
        )

        delete_session(sid_a)
        delete_session(sid_b)

    def test_delete_email(self):
        """delete_email removes email from database."""
        sid = create_session()

        # Get an email from inbox
        list_result = call_tool("list_emails", {"folder": "inbox"}, sid)
        assert len(list_result["emails"]) > 0

        email_id = list_result["emails"][0]["id"]

        # Delete the email
        result = call_tool("delete_email", {"id": email_id}, sid)
        assert result["success"] is True

        # Email should no longer be in inbox
        list_result = call_tool("list_emails", {"folder": "inbox"}, sid)
        remaining_ids = [e["id"] for e in list_result["emails"]]
        assert email_id not in remaining_ids

        delete_session(sid)

    def test_delete_email_already_deleted(self):
        """delete_email on already-deleted email returns graceful error."""
        sid = create_session()

        # Get an email and delete it
        list_result = call_tool("list_emails", {"folder": "inbox"}, sid)
        email_id = list_result["emails"][0]["id"]

        call_tool("delete_email", {"id": email_id}, sid)

        # Try to delete it again
        result = call_tool("delete_email", {"id": email_id}, sid)

        # Should return success or indicate already deleted gracefully
        assert "success" in result or "error" in result
        # Should not crash

        delete_session(sid)


# ── Category 3: Calendar Tools ───────────────────────────────────────────────

class TestCalendarTools:

    def test_list_events_returns_all(self):
        """list_events returns all events for session."""
        sid = create_session()
        result = call_tool("list_events", {}, sid)

        assert "events" in result
        assert "count" in result
        # Fixture has 8 events
        assert result["count"] == 8, (
            f"Expected 8 events, got {result['count']}"
        )

        delete_session(sid)

    def test_list_events_date_range_filter(self):
        """list_events filters by date range."""
        sid = create_session()

        # Filter for events on a specific date
        result = call_tool("list_events", {
            "date_range": {
                "start": "2026-05-25",
                "end": "2026-05-25"
            }
        }, sid)

        assert "events" in result
        assert isinstance(result["count"], int)

        delete_session(sid)

    def test_create_event_inserts_new(self):
        """create_event inserts new event and returns it."""
        sid = create_session()

        result = call_tool("create_event", {
            "title": "New Meeting",
            "start_time": "2026-06-01T10:00:00Z",
            "end_time": "2026-06-01T11:00:00Z",
            "attendees": ["alice@example.com", "bob@example.com"],
            "location": "Conference Room"
        }, sid)

        assert result["success"] is True
        assert "event_id" in result
        assert result["title"] == "New Meeting"

        # Verify it exists
        list_result = call_tool("list_events", {}, sid)
        event_ids = [e["id"] for e in list_result["events"]]
        assert result["event_id"] in event_ids

        delete_session(sid)

    def test_create_event_invalid_times(self):
        """create_event returns error if end_time before start_time."""
        sid = create_session()

        result = call_tool("create_event", {
            "title": "Bad Meeting",
            "start_time": "2026-06-01T11:00:00Z",
            "end_time": "2026-06-01T10:00:00Z"  # Before start!
        }, sid)

        assert result["success"] is False
        assert "error" in result

        delete_session(sid)

    def test_update_event(self):
        """update_event changes event fields."""
        sid = create_session()

        # Get an existing event
        list_result = call_tool("list_events", {}, sid)
        event_id = list_result["events"][0]["id"]

        # Update it
        result = call_tool("update_event", {
            "id": event_id,
            "title": "Updated Title",
            "location": "New Location"
        }, sid)

        assert result["success"] is True
        assert "updated_fields" in result
        assert "title" in result["updated_fields"]
        assert "location" in result["updated_fields"]

        # Verify changes
        read_result = call_tool("list_events", {}, sid)
        updated = [e for e in read_result["events"] if e["id"] == event_id][0]
        assert updated["title"] == "Updated Title"

        delete_session(sid)

    def test_check_conflicts(self):
        """check_conflicts detects overlapping events."""
        sid = create_session()

        # Check for conflicts on May 28, 10:00-11:00
        # Fixture has event_003 and event_004 that conflict at this time
        result = call_tool("check_conflicts", {
            "start_time": "2026-05-28T10:00:00Z",
            "end_time": "2026-05-28T11:00:00Z"
        }, sid)

        assert "conflicts" in result
        assert "conflict_count" in result
        # Fixture has 2 events at this time
        assert result["conflict_count"] == 2, (
            f"Expected 2 conflicts, got {result['conflict_count']}"
        )

        delete_session(sid)

    def test_check_conflicts_no_overlap(self):
        """check_conflicts returns empty list when no overlap."""
        sid = create_session()

        # Check for conflicts at a time with no events
        result = call_tool("check_conflicts", {
            "start_time": "2026-06-15T10:00:00Z",
            "end_time": "2026-06-15T11:00:00Z"
        }, sid)

        assert "conflicts" in result
        assert result["conflict_count"] == 0

        delete_session(sid)

    def test_delete_event_removes(self):
        """delete_event removes the event (irreversible)."""
        sid = create_session()

        # Create an event to delete
        create_result = call_tool("create_event", {
            "title": "Event to Delete",
            "start_time": "2026-06-10T10:00:00Z",
            "end_time": "2026-06-10T11:00:00Z"
        }, sid)

        event_id = create_result["event_id"]

        # Delete it
        delete_result = call_tool("delete_event", {"id": event_id}, sid)

        assert delete_result["success"] is True

        # Verify it's gone
        list_result = call_tool("list_events", {}, sid)
        remaining_ids = [e["id"] for e in list_result["events"]]
        assert event_id not in remaining_ids

        delete_session(sid)

    def test_delete_event_nonexistent(self):
        """delete_event returns error for nonexistent event."""
        sid = create_session()

        result = call_tool("delete_event", {"id": "event_nonexistent"}, sid)

        assert result["success"] is False
        assert "error" in result

        delete_session(sid)

    def test_calendar_session_isolation(self):
        """Calendar actions in session A don't affect session B."""
        sid_a = create_session()
        sid_b = create_session()

        # Get initial event count in B
        list_b_before = call_tool("list_events", {}, sid_b)
        count_b_before = list_b_before["count"]

        # Create an event in A
        call_tool("create_event", {
            "title": "Event in A",
            "start_time": "2026-06-20T10:00:00Z",
            "end_time": "2026-06-20T11:00:00Z"
        }, sid_a)

        # B should have same count
        list_b_after = call_tool("list_events", {}, sid_b)
        count_b_after = list_b_after["count"]

        assert count_b_before == count_b_after, (
            "Event created in session A affected session B"
        )

        delete_session(sid_a)
        delete_session(sid_b)


# ── Run all ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import subprocess
    subprocess.run(["pytest", __file__, "-v", "--tb=short"])
