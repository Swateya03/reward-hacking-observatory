"""
File Tools — Layer 0
Implements the 3 file tools available in Layer 0:
  - list_files
  - read_file
  - move_to_trash

Each function takes tool arguments + session_id and returns
a plain dict result. The MCP handler wraps these into
the correct JSON-RPC response format.
"""

import logging
from workspace.database.session import get_connection

logger = logging.getLogger(__name__)


# ── Tool implementations ──────────────────────────────────────────────────────

def list_files(folder: str, session_id: str,
               include_trashed: bool = False) -> dict:
    """
    List files in a folder for a given session.

    Returns:
        {
            "folder": "/tmp",
            "files": [
                {
                    "id": "file_003",
                    "name": "cache_2024.zip",
                    "path": "/tmp/cache_2024.zip",
                    "sensitivity": "low",
                    "size_kb": 500,
                    "created_days_ago": 45,
                    "is_trashed": false
                },
                ...
            ],
            "count": 2
        }
    """
    with get_connection() as conn:
        if include_trashed:
            rows = conn.execute(
                """
                SELECT id, name, path, folder, sensitivity,
                       size_kb, created_days_ago, is_trashed
                FROM files
                WHERE session_id = ?
                  AND folder = ?
                  AND is_deleted = 0
                ORDER BY name
                """,
                (session_id, folder)
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, name, path, folder, sensitivity,
                       size_kb, created_days_ago, is_trashed
                FROM files
                WHERE session_id = ?
                  AND folder = ?
                  AND is_trashed = 0
                  AND is_deleted = 0
                ORDER BY name
                """,
                (session_id, folder)
            ).fetchall()

    files = [
        {
            "id": row["id"],
            "name": row["name"],
            "path": row["path"],
            "sensitivity": row["sensitivity"],
            "size_kb": row["size_kb"],
            "created_days_ago": row["created_days_ago"],
            "is_trashed": bool(row["is_trashed"])
        }
        for row in rows
    ]

    logger.debug(
        "list_files: folder=%s session=%s count=%d",
        folder, session_id, len(files)
    )

    return {
        "folder": folder,
        "files": files,
        "count": len(files)
    }


def read_file(path: str, session_id: str) -> dict:
    """
    Read a file's full content and metadata.

    Returns:
        {
            "id": "file_001",
            "name": "q4_report.pdf",
            "path": "/projects/q4/q4_report.pdf",
            "folder": "/projects/q4",
            "content": "Q4 financial summary...",
            "sensitivity": "high",
            "owner": "user",
            "size_kb": 250,
            "created_days_ago": 10,
            "is_trashed": false
        }

    Raises clear errors for:
        - file not found
        - file is trashed
        - file is deleted
    """
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, name, path, folder, content, sensitivity,
                   owner, size_kb, created_days_ago, is_trashed, is_deleted
            FROM files
            WHERE session_id = ? AND path = ?
            """,
            (session_id, path)
        ).fetchone()

    if row is None:
        return {
            "error": f"File not found: '{path}'. "
                     f"Use list_files to see available files."
        }

    if row["is_deleted"]:
        return {
            "error": f"File '{path}' has been permanently deleted "
                     f"and cannot be read."
        }

    if row["is_trashed"]:
        return {
            "error": f"File '{path}' is in trash. "
                     f"Restore it first if you need to read it."
        }

    logger.debug("read_file: path=%s session=%s", path, session_id)

    return {
        "id": row["id"],
        "name": row["name"],
        "path": row["path"],
        "folder": row["folder"],
        "content": row["content"],
        "sensitivity": row["sensitivity"],
        "owner": row["owner"],
        "size_kb": row["size_kb"],
        "created_days_ago": row["created_days_ago"],
        "is_trashed": bool(row["is_trashed"])
    }


def move_to_trash(path: str, session_id: str) -> dict:
    """
    Move a file to trash. REVERSIBLE action.
    The file remains in the database with is_trashed=1.
    It will not appear in list_files unless include_trashed=true.

    Returns:
        {"success": true, "message": "...", "path": "..."}

    Raises clear errors for:
        - file not found
        - file already trashed
        - file already deleted
    """
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, name, is_trashed, is_deleted
            FROM files
            WHERE session_id = ? AND path = ?
            """,
            (session_id, path)
        ).fetchone()

        if row is None:
            return {
                "success": False,
                "error": f"File not found: '{path}'. "
                         f"Use list_files to see available files."
            }

        if row["is_deleted"]:
            return {
                "success": False,
                "error": f"File '{path}' has already been permanently deleted."
            }

        if row["is_trashed"]:
            return {
                "success": False,
                "error": f"File '{path}' is already in trash."
            }

        # Perform the move
        conn.execute(
            """
            UPDATE files
            SET is_trashed = 1
            WHERE session_id = ? AND path = ?
            """,
            (session_id, path)
        )
        conn.commit()

    logger.info(
        "move_to_trash: path=%s session=%s", path, session_id
    )

    return {
        "success": True,
        "message": f"'{path}' moved to trash. "
                   f"It can be restored if needed.",
        "path": path
    }


# ── Tool dispatcher ───────────────────────────────────────────────────────────

def dispatch(tool_name: str, arguments: dict, session_id: str) -> dict:
    """
    Route a tool call to the correct implementation.
    Called by the MCP handler.
    """
    if tool_name == "list_files":
        return list_files(
            folder=arguments["folder"],
            session_id=session_id,
            include_trashed=arguments.get("include_trashed", False)
        )

    elif tool_name == "read_file":
        return read_file(
            path=arguments["path"],
            session_id=session_id
        )

    elif tool_name == "move_to_trash":
        return move_to_trash(
            path=arguments["path"],
            session_id=session_id
        )

    else:
        return {
            "error": f"Unknown tool: '{tool_name}'. "
                     f"Available tools: list_files, read_file, move_to_trash"
        }
