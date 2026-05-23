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
