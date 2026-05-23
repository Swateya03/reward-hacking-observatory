"""
Calendar Tools — Layer 0
Implements 5 calendar management tools:
  - list_events
  - create_event
  - update_event
  - delete_event
  - check_conflicts

Each function takes tool arguments + session_id and returns
a plain dict result. The MCP handler wraps these into
the correct JSON-RPC response format.
"""

import logging
from datetime import datetime
from uuid import uuid4
from workspace.database.session import get_connection

logger = logging.getLogger(__name__)


# ── Tool implementations ──────────────────────────────────────────────────────

def list_events(session_id: str, date_range: dict = None) -> dict:
    """
    List all events for a session, optionally filtered by date range.

    Args:
        session_id: Session ID
        date_range: Optional dict with "start" and "end" ISO date strings
                   e.g., {"start": "2026-05-25", "end": "2026-05-30"}

    Returns:
        {
            "events": [
                {
                    "id": "event_001",
                    "title": "Weekly Standup",
                    "start_time": "2026-05-25T09:00:00Z",
                    "end_time": "2026-05-25T09:30:00Z",
                    "location": "Conference Room A",
                    "is_recurring": false,
                    "attendee_count": 3,
                    "sensitivity": "low"
                },
                ...
            ],
            "count": 8
        }
    """
    with get_connection() as conn:
        query = """
            SELECT id, title, start_time, end_time, location,
                   is_recurring, attendees, sensitivity
            FROM events
            WHERE session_id = ?
        """
        params = [session_id]

        if date_range and "start" in date_range and "end" in date_range:
            query += " AND start_time >= ? AND end_time <= ?"
            params.extend([date_range["start"], date_range["end"]])

        query += " ORDER BY start_time ASC"

        rows = conn.execute(query, params).fetchall()

    events = []
    for row in rows:
        attendee_count = 0
        if row["attendees"]:
            try:
                import json
                attendees = json.loads(row["attendees"])
                attendee_count = len(attendees) if isinstance(attendees, list) else 0
            except:
                attendee_count = 0

        events.append({
            "id": row["id"],
            "title": row["title"],
            "start_time": row["start_time"],
            "end_time": row["end_time"],
            "location": row["location"],
            "is_recurring": bool(row["is_recurring"]),
            "attendee_count": attendee_count,
            "sensitivity": row["sensitivity"]
        })

    logger.debug(
        "list_events: session=%s count=%d",
        session_id, len(events)
    )

    return {
        "events": events,
        "count": len(events)
    }


def create_event(title: str, start_time: str, end_time: str, session_id: str,
                 attendees: list = None, location: str = None) -> dict:
    """
    Create a new calendar event. Generates a new event ID.

    Returns:
        {
            "success": true,
            "message": "Event created",
            "event_id": "event_009",
            "title": "Team Meeting"
        }

    Raises clear errors for:
        - invalid time format
        - end_time before start_time
    """
    event_id = f"event_{int(uuid4().int % 1000000):06d}"

    try:
        start = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        end = datetime.fromisoformat(end_time.replace("Z", "+00:00"))

        if end <= start:
            return {
                "success": False,
                "error": "Event end_time must be after start_time."
            }
    except ValueError as e:
        return {
            "success": False,
            "error": f"Invalid time format. Use ISO 8601: {str(e)}"
        }

    attendees_json = None
    if attendees:
        import json
        try:
            attendees_json = json.dumps(attendees)
        except:
            return {
                "success": False,
                "error": "Invalid attendees format. Must be a JSON-serializable list."
            }

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO events
                (id, title, start_time, end_time, attendees, is_recurring,
                 recurrence_rule, location, sensitivity, session_id)
            VALUES
                (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (event_id, title, start_time, end_time, attendees_json, 0,
             None, location, "low", session_id)
        )
        conn.commit()

    logger.info(
        "create_event: event_id=%s title=%s session=%s",
        event_id, title, session_id
    )

    return {
        "success": True,
        "message": "Event created",
        "event_id": event_id,
        "title": title
    }


def update_event(id: str, session_id: str, **changes) -> dict:
    """
    Update fields on an existing event. Accepts any field name.

    Valid fields: title, start_time, end_time, attendees, location,
                 is_recurring, recurrence_rule, sensitivity

    Returns:
        {
            "success": true,
            "message": "Event updated",
            "event_id": "event_001",
            "updated_fields": ["title", "location"]
        }

    Raises clear errors for:
        - event not found
        - invalid field name
        - invalid time values
    """
    valid_fields = {
        "title", "start_time", "end_time", "attendees", "location",
        "is_recurring", "recurrence_rule", "sensitivity"
    }

    invalid_fields = set(changes.keys()) - valid_fields
    if invalid_fields:
        return {
            "success": False,
            "error": f"Invalid fields: {', '.join(sorted(invalid_fields))}. "
                     f"Valid fields: {', '.join(sorted(valid_fields))}"
        }

    if not changes:
        return {
            "success": False,
            "error": "No fields to update."
        }

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, start_time, end_time
            FROM events
            WHERE session_id = ? AND id = ?
            """,
            (session_id, id)
        ).fetchone()

        if row is None:
            return {
                "success": False,
                "error": f"Event not found: '{id}'. "
                         f"Use list_events to see available events."
            }

        # Validate time changes if provided
        if "start_time" in changes or "end_time" in changes:
            new_start = changes.get("start_time", row["start_time"])
            new_end = changes.get("end_time", row["end_time"])

            try:
                start = datetime.fromisoformat(new_start.replace("Z", "+00:00"))
                end = datetime.fromisoformat(new_end.replace("Z", "+00:00"))

                if end <= start:
                    return {
                        "success": False,
                        "error": "Event end_time must be after start_time."
                    }
            except ValueError as e:
                return {
                    "success": False,
                    "error": f"Invalid time format. Use ISO 8601: {str(e)}"
                }

        # Process attendees if provided
        if "attendees" in changes:
            import json
            try:
                if isinstance(changes["attendees"], list):
                    changes["attendees"] = json.dumps(changes["attendees"])
                elif isinstance(changes["attendees"], str):
                    json.loads(changes["attendees"])
            except:
                return {
                    "success": False,
                    "error": "Invalid attendees format. Must be a JSON-serializable list."
                }

        # Build UPDATE statement
        set_clauses = ", ".join([f"{k} = ?" for k in changes.keys()])
        values = list(changes.values()) + [session_id, id]

        conn.execute(
            f"""
            UPDATE events
            SET {set_clauses}
            WHERE session_id = ? AND id = ?
            """,
            values
        )
        conn.commit()

    logger.info(
        "update_event: id=%s session=%s fields=%s",
        id, session_id, list(changes.keys())
    )

    return {
        "success": True,
        "message": "Event updated",
        "event_id": id,
        "updated_fields": list(changes.keys())
    }


def delete_event(id: str, session_id: str) -> dict:
    """
    Permanently delete an event. IRREVERSIBLE action.
    The event is removed from the database.

    Returns:
        {"success": true, "message": "...", "event_id": "..."}

    Raises clear errors for:
        - event not found
    """
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id
            FROM events
            WHERE session_id = ? AND id = ?
            """,
            (session_id, id)
        ).fetchone()

        if row is None:
            return {
                "success": False,
                "error": f"Event not found: '{id}'. "
                         f"Use list_events to see available events."
            }

        conn.execute(
            """
            DELETE FROM events
            WHERE session_id = ? AND id = ?
            """,
            (session_id, id)
        )
        conn.commit()

    logger.info(
        "delete_event: id=%s session=%s", id, session_id
    )

    return {
        "success": True,
        "message": "Event permanently deleted",
        "event_id": id
    }


def check_conflicts(start_time: str, end_time: str, session_id: str) -> dict:
    """
    Check for events that conflict with (overlap) the given time range.

    Two events conflict if one starts before the other ends AND
    one ends after the other starts.

    Returns:
        {
            "requested_range": {
                "start_time": "2026-05-28T10:00:00Z",
                "end_time": "2026-05-28T11:00:00Z"
            },
            "conflicts": [
                {
                    "id": "event_004",
                    "title": "Budget Review Meeting",
                    "start_time": "2026-05-28T10:00:00Z",
                    "end_time": "2026-05-28T11:00:00Z",
                    "attendee_count": 2
                },
                ...
            ],
            "conflict_count": 2
        }

    Raises clear errors for:
        - invalid time format
        - end_time before start_time
    """
    try:
        start = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        end = datetime.fromisoformat(end_time.replace("Z", "+00:00"))

        if end <= start:
            return {
                "error": "Requested end_time must be after start_time."
            }
    except ValueError as e:
        return {
            "error": f"Invalid time format. Use ISO 8601: {str(e)}"
        }

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, title, start_time, end_time, attendees
            FROM events
            WHERE session_id = ?
              AND start_time < ?
              AND end_time > ?
            ORDER BY start_time ASC
            """,
            (session_id, end_time, start_time)
        ).fetchall()

    conflicts = []
    for row in rows:
        attendee_count = 0
        if row["attendees"]:
            try:
                import json
                attendees = json.loads(row["attendees"])
                attendee_count = len(attendees) if isinstance(attendees, list) else 0
            except:
                attendee_count = 0

        conflicts.append({
            "id": row["id"],
            "title": row["title"],
            "start_time": row["start_time"],
            "end_time": row["end_time"],
            "attendee_count": attendee_count
        })

    logger.debug(
        "check_conflicts: session=%s range=%s-%s count=%d",
        session_id, start_time, end_time, len(conflicts)
    )

    return {
        "requested_range": {
            "start_time": start_time,
            "end_time": end_time
        },
        "conflicts": conflicts,
        "conflict_count": len(conflicts)
    }


# ── Tool dispatcher ───────────────────────────────────────────────────────────

def dispatch(tool_name: str, arguments: dict, session_id: str) -> dict:
    """
    Route a tool call to the correct implementation.
    Called by the MCP handler.
    """
    if tool_name == "list_events":
        return list_events(
            session_id=session_id,
            date_range=arguments.get("date_range")
        )

    elif tool_name == "create_event":
        return create_event(
            title=arguments["title"],
            start_time=arguments["start_time"],
            end_time=arguments["end_time"],
            session_id=session_id,
            attendees=arguments.get("attendees"),
            location=arguments.get("location")
        )

    elif tool_name == "update_event":
        changes = {k: v for k, v in arguments.items()
                  if k not in ("id", "session_id")}
        return update_event(
            id=arguments["id"],
            session_id=session_id,
            **changes
        )

    elif tool_name == "delete_event":
        return delete_event(
            id=arguments["id"],
            session_id=session_id
        )

    elif tool_name == "check_conflicts":
        return check_conflicts(
            start_time=arguments["start_time"],
            end_time=arguments["end_time"],
            session_id=session_id
        )

    else:
        return {
            "error": f"Unknown tool: '{tool_name}'. "
                     f"Available tools: list_events, create_event, update_event, "
                     f"delete_event, check_conflicts"
        }
