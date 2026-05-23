"""
Session Manager — Layer 0
Handles creation, seeding, resetting, and cleanup of workspace sessions.
Each session gets its own isolated partition of the SQLite database
identified by a unique session_id (UUID4).

This is the env.reset() equivalent for the project.
"""

import json
import logging
import sqlite3
from pathlib import Path
from uuid import uuid4

logger = logging.getLogger(__name__)

# Single SQLite file for all sessions — isolated by session_id column
DB_PATH = Path(__file__).parent / "workspace.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"
FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


def get_connection() -> sqlite3.Connection:
    """Return a sqlite3 connection with row_factory set to dict-like rows."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # allows concurrent reads
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """Create tables if they don't exist. Called once at server startup."""
    schema = SCHEMA_PATH.read_text()
    with get_connection() as conn:
        conn.executescript(schema)
    logger.info("Database initialised at %s", DB_PATH)


def load_fixture(fixture_name: str = "default") -> dict:
    """Load a fixture JSON file from the fixtures directory."""
    fixture_path = FIXTURES_DIR / f"{fixture_name}.json"
    if not fixture_path.exists():
        raise FileNotFoundError(
            f"Fixture '{fixture_name}' not found at {fixture_path}. "
            f"Available fixtures: {list_fixtures()}"
        )
    return json.loads(fixture_path.read_text())


def list_fixtures() -> list[str]:
    """Return names of all available fixture files."""
    return [p.stem for p in FIXTURES_DIR.glob("*.json")]


def create_session(fixture_name: str = "default") -> str:
    """
    Create a new isolated session, seed it with fixture data,
    and return the session_id.

    This is equivalent to env.reset() — gives a fresh starting state.
    """
    session_id = str(uuid4())
    fixture = load_fixture(fixture_name)
    _seed_session(session_id, fixture)
    logger.info("Session created: %s (fixture=%s)", session_id, fixture_name)
    return session_id


def reset_session(session_id: str, fixture_name: str = "default") -> None:
    """
    Wipe all data for a session and reseed from fixture.
    Equivalent to calling env.reset() on an existing episode.
    """
    _clear_session(session_id)
    fixture = load_fixture(fixture_name)
    _seed_session(session_id, fixture)
    logger.info("Session reset: %s", session_id)


def delete_session(session_id: str) -> None:
    """Permanently delete all data for a session. Used for cleanup."""
    _clear_session(session_id)
    logger.info("Session deleted: %s", session_id)


def session_exists(session_id: str) -> bool:
    """Check whether a session has been created and has data."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM files WHERE session_id = ?",
            (session_id,)
        ).fetchone()
        return row["cnt"] > 0


def get_state_snapshot(session_id: str) -> dict:
    """
    Return the full current state of a session as a plain dict.
    Used by reward functions and verifiers to check ground truth
    without going through MCP tools.
    """
    with get_connection() as conn:
        files = conn.execute(
            "SELECT * FROM files WHERE session_id = ?",
            (session_id,)
        ).fetchall()
        emails = conn.execute(
            "SELECT * FROM emails WHERE session_id = ?",
            (session_id,)
        ).fetchall()
        events = conn.execute(
            "SELECT * FROM events WHERE session_id = ?",
            (session_id,)
        ).fetchall()
        return {
            "files": [dict(row) for row in files],
            "emails": [dict(row) for row in emails],
            "events": [dict(row) for row in events]
        }


# ── private helpers ──────────────────────────────────────────────────────────

def _seed_session(session_id: str, fixture: dict) -> None:
    """Insert all fixture rows into the database under this session_id."""
    with get_connection() as conn:
        for file_row in fixture.get("files", []):
            conn.execute(
                """
                INSERT INTO files
                    (id, name, path, folder, content, sensitivity,
                     owner, created_days_ago, size_kb,
                     is_trashed, is_deleted, session_id)
                VALUES
                    (:id, :name, :path, :folder, :content, :sensitivity,
                     :owner, :created_days_ago, :size_kb,
                     :is_trashed, :is_deleted, :session_id)
                """,
                {**file_row, "session_id": session_id}
            )
        for email_row in fixture.get("emails", []):
            conn.execute(
                """
                INSERT INTO emails
                    (id, sender, recipient, subject, body, folder, thread_id,
                     is_read, has_attachment, sensitivity, created_days_ago, session_id)
                VALUES
                    (:id, :sender, :recipient, :subject, :body, :folder, :thread_id,
                     :is_read, :has_attachment, :sensitivity, :created_days_ago, :session_id)
                """,
                {**email_row, "session_id": session_id}
            )
        for event_row in fixture.get("events", []):
            conn.execute(
                """
                INSERT INTO events
                    (id, title, start_time, end_time, attendees, is_recurring,
                     recurrence_rule, location, sensitivity, session_id)
                VALUES
                    (:id, :title, :start_time, :end_time, :attendees, :is_recurring,
                     :recurrence_rule, :location, :sensitivity, :session_id)
                """,
                {**event_row, "session_id": session_id}
            )
        conn.commit()


def _clear_session(session_id: str) -> None:
    """Delete all rows belonging to this session."""
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM files WHERE session_id = ?",
            (session_id,)
        )
        conn.execute(
            "DELETE FROM emails WHERE session_id = ?",
            (session_id,)
        )
        conn.execute(
            "DELETE FROM events WHERE session_id = ?",
            (session_id,)
        )
        conn.commit()
