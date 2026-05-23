"""
Email Tools — Layer 0
Implements 8 email management tools:
  - list_emails
  - read_email
  - save_draft
  - send_email
  - move_email
  - delete_email
  - reply_email
  - mark_read

Each function takes tool arguments + session_id and returns
a plain dict result. The MCP handler wraps these into
the correct JSON-RPC response format.
"""

import logging
from uuid import uuid4
from workspace.database.session import get_connection

logger = logging.getLogger(__name__)


# ── Tool implementations ──────────────────────────────────────────────────────

def list_emails(folder: str, session_id: str) -> dict:
    """
    List emails in a folder for a given session.

    Returns:
        {
            "folder": "inbox",
            "emails": [
                {
                    "id": "email_001",
                    "sender": "client@acme.com",
                    "subject": "Q2 Proposal - Ready for Review",
                    "is_read": false,
                    "has_attachment": true,
                    "sensitivity": "high",
                    "created_days_ago": 1
                },
                ...
            ],
            "count": 5
        }
    """
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, sender, recipient, subject, is_read,
                   has_attachment, sensitivity, created_days_ago
            FROM emails
            WHERE session_id = ?
              AND folder = ?
              AND is_deleted = 0
            ORDER BY created_days_ago ASC
            """,
            (session_id, folder)
        ).fetchall()

    emails = [
        {
            "id": row["id"],
            "sender": row["sender"],
            "subject": row["subject"],
            "is_read": bool(row["is_read"]),
            "has_attachment": bool(row["has_attachment"]),
            "sensitivity": row["sensitivity"],
            "created_days_ago": row["created_days_ago"]
        }
        for row in rows
    ]

    logger.debug(
        "list_emails: folder=%s session=%s count=%d",
        folder, session_id, len(emails)
    )

    return {
        "folder": folder,
        "emails": emails,
        "count": len(emails)
    }


def read_email(id: str, session_id: str) -> dict:
    """
    Read an email's full content and metadata.

    Returns:
        {
            "id": "email_001",
            "sender": "client@acme.com",
            "recipient": "user@company.com",
            "subject": "Q2 Proposal - Ready for Review",
            "body": "Hi, I've reviewed your proposal...",
            "folder": "inbox",
            "thread_id": "thread_001",
            "is_read": false,
            "has_attachment": true,
            "sensitivity": "high",
            "created_days_ago": 1
        }

    Raises clear errors for:
        - email not found
        - email is deleted
    """
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, sender, recipient, subject, body, folder,
                   thread_id, is_read, has_attachment, sensitivity,
                   created_days_ago, is_deleted
            FROM emails
            WHERE session_id = ? AND id = ?
            """,
            (session_id, id)
        ).fetchone()

    if row is None:
        return {
            "error": f"Email not found: '{id}'. "
                     f"Use list_emails to see available emails."
        }

    if row["is_deleted"]:
        return {
            "error": f"Email '{id}' has been permanently deleted "
                     f"and cannot be read."
        }

    logger.debug("read_email: id=%s session=%s", id, session_id)

    return {
        "id": row["id"],
        "sender": row["sender"],
        "recipient": row["recipient"],
        "subject": row["subject"],
        "body": row["body"],
        "folder": row["folder"],
        "thread_id": row["thread_id"],
        "is_read": bool(row["is_read"]),
        "has_attachment": bool(row["has_attachment"]),
        "sensitivity": row["sensitivity"],
        "created_days_ago": row["created_days_ago"]
    }


def save_draft(to: str, subject: str, body: str, session_id: str) -> dict:
    """
    Save an email as a draft. Generates a new email ID.

    Returns:
        {
            "success": true,
            "message": "Draft saved",
            "email_id": "email_013",
            "folder": "drafts"
        }
    """
    email_id = f"email_{int(uuid4().int % 1000000):06d}"

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO emails
                (id, sender, recipient, subject, body, folder, thread_id,
                 is_read, has_attachment, sensitivity, created_days_ago, is_deleted, session_id)
            VALUES
                (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (email_id, "user@company.com", to, subject, body, "drafts", None,
             0, 0, "low", 0, 0, session_id)
        )
        conn.commit()

    logger.info(
        "save_draft: email_id=%s to=%s session=%s", email_id, to, session_id
    )

    return {
        "success": True,
        "message": "Draft saved",
        "email_id": email_id,
        "folder": "drafts"
    }


def send_email(to: str, subject: str, body: str, session_id: str) -> dict:
    """
    Send an email. Saves to sent folder.
    NOTE: This is IRREVERSIBLE. Once sent, an email cannot be unsent.

    Returns:
        {
            "success": true,
            "message": "Email sent",
            "email_id": "email_014",
            "folder": "sent",
            "irreversible": true
        }
    """
    email_id = f"email_{int(uuid4().int % 1000000):06d}"

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO emails
                (id, sender, recipient, subject, body, folder, thread_id,
                 is_read, has_attachment, sensitivity, created_days_ago, is_deleted, session_id)
            VALUES
                (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (email_id, "user@company.com", to, subject, body, "sent", None,
             1, 0, "low", 0, 0, session_id)
        )
        conn.commit()

    logger.info(
        "send_email: email_id=%s to=%s session=%s", email_id, to, session_id
    )

    return {
        "success": True,
        "message": "Email sent",
        "email_id": email_id,
        "folder": "sent",
        "irreversible": True
    }


def move_email(id: str, folder: str, session_id: str) -> dict:
    """
    Move an email to a different folder.
    Valid folders: inbox, drafts, sent, trash, spam

    Returns:
        {"success": true, "message": "...", "email_id": "...", "folder": "..."}

    Raises clear errors for:
        - email not found
        - email already deleted
        - invalid folder name
    """
    valid_folders = {"inbox", "drafts", "sent", "trash", "spam"}

    if folder not in valid_folders:
        return {
            "success": False,
            "error": f"Invalid folder '{folder}'. "
                     f"Valid folders: {', '.join(sorted(valid_folders))}"
        }

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, folder, is_deleted
            FROM emails
            WHERE session_id = ? AND id = ?
            """,
            (session_id, id)
        ).fetchone()

        if row is None:
            return {
                "success": False,
                "error": f"Email not found: '{id}'. "
                         f"Use list_emails to see available emails."
            }

        if row["is_deleted"]:
            return {
                "success": False,
                "error": f"Email '{id}' has been permanently deleted "
                         f"and cannot be moved."
            }

        if row["folder"] == folder:
            return {
                "success": False,
                "error": f"Email '{id}' is already in folder '{folder}'."
            }

        conn.execute(
            """
            UPDATE emails
            SET folder = ?
            WHERE session_id = ? AND id = ?
            """,
            (folder, session_id, id)
        )
        conn.commit()

    logger.info(
        "move_email: id=%s from=%s to=%s session=%s",
        id, row["folder"], folder, session_id
    )

    return {
        "success": True,
        "message": f"Email moved to '{folder}'",
        "email_id": id,
        "folder": folder
    }


def delete_email(id: str, session_id: str) -> dict:
    """
    Permanently delete an email. IRREVERSIBLE action.
    Sets is_deleted=1 in the database.

    Returns:
        {"success": true, "message": "...", "email_id": "..."}

    Raises clear errors for:
        - email not found
        - email already deleted
    """
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, is_deleted
            FROM emails
            WHERE session_id = ? AND id = ?
            """,
            (session_id, id)
        ).fetchone()

        if row is None:
            return {
                "success": False,
                "error": f"Email not found: '{id}'. "
                         f"Use list_emails to see available emails."
            }

        if row["is_deleted"]:
            return {
                "success": False,
                "error": f"Email '{id}' has already been permanently deleted."
            }

        conn.execute(
            """
            UPDATE emails
            SET is_deleted = 1
            WHERE session_id = ? AND id = ?
            """,
            (session_id, id)
        )
        conn.commit()

    logger.info(
        "delete_email: id=%s session=%s", id, session_id
    )

    return {
        "success": True,
        "message": "Email permanently deleted",
        "email_id": id
    }


def reply_email(id: str, body: str, session_id: str, send: bool = False) -> dict:
    """
    Reply to an email. Creates a new email with the same thread_id.
    If send=False, saves as draft. If send=True, sends immediately.

    Returns:
        {
            "success": true,
            "message": "...",
            "reply_id": "email_015",
            "folder": "drafts" | "sent",
            "thread_id": "thread_001"
        }

    Raises clear errors for:
        - email not found
        - email is deleted
    """
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, sender, recipient, subject, thread_id, is_deleted
            FROM emails
            WHERE session_id = ? AND id = ?
            """,
            (session_id, id)
        ).fetchone()

        if row is None:
            return {
                "success": False,
                "error": f"Email not found: '{id}'. "
                         f"Use list_emails to see available emails."
            }

        if row["is_deleted"]:
            return {
                "success": False,
                "error": f"Email '{id}' has been permanently deleted "
                         f"and cannot be replied to."
            }

        # Create reply email
        reply_id = f"email_{int(uuid4().int % 1000000):06d}"
        reply_folder = "sent" if send else "drafts"
        reply_subject = f"RE: {row['subject']}" if not row['subject'].startswith("RE: ") else row['subject']
        reply_thread_id = row["thread_id"] or row["id"]

        conn.execute(
            """
            INSERT INTO emails
                (id, sender, recipient, subject, body, folder, thread_id,
                 is_read, has_attachment, sensitivity, created_days_ago, is_deleted, session_id)
            VALUES
                (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (reply_id, "user@company.com", row["sender"], reply_subject, body,
             reply_folder, reply_thread_id, 1 if send else 0, 0, "low", 0, 0, session_id)
        )
        conn.commit()

    logger.info(
        "reply_email: reply_id=%s to=%s send=%s session=%s",
        reply_id, row["sender"], send, session_id
    )

    return {
        "success": True,
        "message": f"Reply {'sent' if send else 'saved as draft'}",
        "reply_id": reply_id,
        "folder": reply_folder,
        "thread_id": reply_thread_id
    }


def mark_read(id: str, session_id: str) -> dict:
    """
    Mark an email as read.

    Returns:
        {"success": true, "message": "...", "email_id": "..."}

    Raises clear errors for:
        - email not found
        - email already deleted
        - email already marked read
    """
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, is_read, is_deleted
            FROM emails
            WHERE session_id = ? AND id = ?
            """,
            (session_id, id)
        ).fetchone()

        if row is None:
            return {
                "success": False,
                "error": f"Email not found: '{id}'. "
                         f"Use list_emails to see available emails."
            }

        if row["is_deleted"]:
            return {
                "success": False,
                "error": f"Email '{id}' has been permanently deleted "
                         f"and cannot be marked read."
            }

        if row["is_read"]:
            return {
                "success": False,
                "error": f"Email '{id}' is already marked as read."
            }

        conn.execute(
            """
            UPDATE emails
            SET is_read = 1
            WHERE session_id = ? AND id = ?
            """,
            (session_id, id)
        )
        conn.commit()

    logger.info(
        "mark_read: id=%s session=%s", id, session_id
    )

    return {
        "success": True,
        "message": "Email marked as read",
        "email_id": id
    }


# ── Tool dispatcher ───────────────────────────────────────────────────────────

def dispatch(tool_name: str, arguments: dict, session_id: str) -> dict:
    """
    Route a tool call to the correct implementation.
    Called by the MCP handler.
    """
    if tool_name == "list_emails":
        return list_emails(
            folder=arguments["folder"],
            session_id=session_id
        )

    elif tool_name == "read_email":
        return read_email(
            id=arguments["id"],
            session_id=session_id
        )

    elif tool_name == "save_draft":
        return save_draft(
            to=arguments["to"],
            subject=arguments["subject"],
            body=arguments["body"],
            session_id=session_id
        )

    elif tool_name == "send_email":
        return send_email(
            to=arguments["to"],
            subject=arguments["subject"],
            body=arguments["body"],
            session_id=session_id
        )

    elif tool_name == "move_email":
        return move_email(
            id=arguments["id"],
            folder=arguments["folder"],
            session_id=session_id
        )

    elif tool_name == "delete_email":
        return delete_email(
            id=arguments["id"],
            session_id=session_id
        )

    elif tool_name == "reply_email":
        return reply_email(
            id=arguments["id"],
            body=arguments["body"],
            send=arguments.get("send", False),
            session_id=session_id
        )

    elif tool_name == "mark_read":
        return mark_read(
            id=arguments["id"],
            session_id=session_id
        )

    else:
        return {
            "error": f"Unknown tool: '{tool_name}'. "
                     f"Available tools: list_emails, read_email, save_draft, send_email, "
                     f"move_email, delete_email, reply_email, mark_read"
        }
