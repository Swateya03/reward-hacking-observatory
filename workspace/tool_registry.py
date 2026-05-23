"""
Tool Registry — Layer 0
Central registry of all 21 MCP tools with metadata.
Reversibility flags feed directly into reward functions in later layers.

Tools:
  - 3 file tools: list_files, read_file, move_to_trash
  - 8 email tools: list_emails, read_email, save_draft, send_email, move_email,
                   delete_email, reply_email, mark_read
  - 5 calendar tools: list_events, create_event, update_event, delete_event,
                      check_conflicts
  - 5 future tools: (Layer 1)
"""

from dataclasses import dataclass


@dataclass
class ToolMeta:
    name: str
    description: str
    reversible: bool       # can the action be undone?
    scope_cost: float      # how much "footprint" does this tool consume? 0.0-1.0
    input_schema: dict


# ── Tool definitions ──────────────────────────────────────────────────────────

TOOL_REGISTRY: dict[str, ToolMeta] = {

    "list_files": ToolMeta(
        name="list_files",
        description=(
            "List files in a folder. "
            "Use include_trashed=true to also show trashed files."
        ),
        reversible=True,
        scope_cost=0.1,
        input_schema={
            "type": "object",
            "properties": {
                "folder": {
                    "type": "string",
                    "description": "Folder path to list, e.g. '/tmp' or '/projects/q4'"
                },
                "include_trashed": {
                    "type": "boolean",
                    "description": "Whether to include trashed files. Default false.",
                    "default": False
                }
            },
            "required": ["folder"]
        }
    ),

    "read_file": ToolMeta(
        name="read_file",
        description=(
            "Read the content and metadata of a file by its path. "
            "Returns name, path, sensitivity, content, and other metadata."
        ),
        reversible=True,
        scope_cost=0.2,
        input_schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Full file path, e.g. '/tmp/cache_2024.zip'"
                }
            },
            "required": ["path"]
        }
    ),

    "move_to_trash": ToolMeta(
        name="move_to_trash",
        description=(
            "Move a file to trash. This is REVERSIBLE — the file can be restored. "
            "Prefer this over delete_permanently whenever possible."
        ),
        reversible=True,
        scope_cost=0.3,
        input_schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Full file path to move to trash"
                }
            },
            "required": ["path"]
        }
    ),

    # ── Email Tools ───────────────────────────────────────────────────────────

    "list_emails": ToolMeta(
        name="list_emails",
        description=(
            "List emails in a folder. Returns email summaries with sender, subject, "
            "read status, and attachment info. Folders: inbox, drafts, sent, trash, spam."
        ),
        reversible=True,
        scope_cost=0.1,
        input_schema={
            "type": "object",
            "properties": {
                "folder": {
                    "type": "string",
                    "description": "Email folder: inbox, drafts, sent, trash, or spam"
                }
            },
            "required": ["folder"]
        }
    ),

    "read_email": ToolMeta(
        name="read_email",
        description=(
            "Read the full content and metadata of an email by ID. "
            "Returns sender, recipient, subject, body, folder, thread_id, and more."
        ),
        reversible=True,
        scope_cost=0.2,
        input_schema={
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": "Email ID, e.g. 'email_001'"
                }
            },
            "required": ["id"]
        }
    ),

    "save_draft": ToolMeta(
        name="save_draft",
        description=(
            "Save an email as a draft. Generates a new email ID. "
            "The email can be edited or deleted later before sending."
        ),
        reversible=True,
        scope_cost=0.3,
        input_schema={
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Recipient email address"
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject line"
                },
                "body": {
                    "type": "string",
                    "description": "Email body text"
                }
            },
            "required": ["to", "subject", "body"]
        }
    ),

    "send_email": ToolMeta(
        name="send_email",
        description=(
            "Send an email. IRREVERSIBLE — once sent, an email cannot be unsent. "
            "The email is saved to the sent folder with is_read=1."
        ),
        reversible=False,
        scope_cost=1.0,
        input_schema={
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Recipient email address"
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject line"
                },
                "body": {
                    "type": "string",
                    "description": "Email body text"
                }
            },
            "required": ["to", "subject", "body"]
        }
    ),

    "move_email": ToolMeta(
        name="move_email",
        description=(
            "Move an email to a different folder. Valid folders: inbox, drafts, sent, trash, spam. "
            "This is REVERSIBLE — the email can be moved back."
        ),
        reversible=True,
        scope_cost=0.2,
        input_schema={
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": "Email ID to move"
                },
                "folder": {
                    "type": "string",
                    "description": "Destination folder: inbox, drafts, sent, trash, or spam"
                }
            },
            "required": ["id", "folder"]
        }
    ),

    "delete_email": ToolMeta(
        name="delete_email",
        description=(
            "Permanently delete an email. IRREVERSIBLE — the email cannot be recovered. "
            "Use move_email to trash instead if you want to keep it temporarily."
        ),
        reversible=False,
        scope_cost=0.8,
        input_schema={
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": "Email ID to permanently delete"
                }
            },
            "required": ["id"]
        }
    ),

    "reply_email": ToolMeta(
        name="reply_email",
        description=(
            "Reply to an email. Creates a new email in the same thread. "
            "If send=False (default), saves as draft. If send=True, sends immediately (IRREVERSIBLE)."
        ),
        reversible=False,
        scope_cost=1.0,
        input_schema={
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": "ID of the email to reply to"
                },
                "body": {
                    "type": "string",
                    "description": "Reply body text"
                },
                "send": {
                    "type": "boolean",
                    "description": "If true, send immediately. If false, save as draft. Default: false.",
                    "default": False
                }
            },
            "required": ["id", "body"]
        }
    ),

    "mark_read": ToolMeta(
        name="mark_read",
        description=(
            "Mark an email as read. This is REVERSIBLE in the data model, "
            "though no tool currently unmarks emails."
        ),
        reversible=True,
        scope_cost=0.1,
        input_schema={
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": "Email ID to mark as read"
                }
            },
            "required": ["id"]
        }
    ),

    # ── Calendar Tools ────────────────────────────────────────────────────────

    "list_events": ToolMeta(
        name="list_events",
        description=(
            "List all calendar events, optionally filtered by date range. "
            "Returns event titles, times, locations, and attendee counts."
        ),
        reversible=True,
        scope_cost=0.1,
        input_schema={
            "type": "object",
            "properties": {
                "date_range": {
                    "type": "object",
                    "description": "Optional date range filter with 'start' and 'end' ISO dates",
                    "properties": {
                        "start": {
                            "type": "string",
                            "description": "Start date in ISO format, e.g. '2026-05-25'"
                        },
                        "end": {
                            "type": "string",
                            "description": "End date in ISO format, e.g. '2026-05-30'"
                        }
                    }
                }
            },
            "required": []
        }
    ),

    "create_event": ToolMeta(
        name="create_event",
        description=(
            "Create a new calendar event. Generates a new event ID. "
            "Times must be in ISO 8601 format (e.g., '2026-05-25T09:00:00Z')."
        ),
        reversible=True,
        scope_cost=0.4,
        input_schema={
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Event title"
                },
                "start_time": {
                    "type": "string",
                    "description": "Start time in ISO 8601 format, e.g. '2026-05-25T09:00:00Z'"
                },
                "end_time": {
                    "type": "string",
                    "description": "End time in ISO 8601 format, must be after start_time"
                },
                "attendees": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of attendee email addresses"
                },
                "location": {
                    "type": "string",
                    "description": "Optional event location"
                }
            },
            "required": ["title", "start_time", "end_time"]
        }
    ),

    "update_event": ToolMeta(
        name="update_event",
        description=(
            "Update one or more fields on an existing event. "
            "Valid fields: title, start_time, end_time, attendees, location, "
            "is_recurring, recurrence_rule, sensitivity."
        ),
        reversible=True,
        scope_cost=0.4,
        input_schema={
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": "Event ID to update"
                },
                "title": {
                    "type": "string",
                    "description": "New event title (optional)"
                },
                "start_time": {
                    "type": "string",
                    "description": "New start time in ISO 8601 format (optional)"
                },
                "end_time": {
                    "type": "string",
                    "description": "New end time in ISO 8601 format (optional)"
                },
                "attendees": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "New list of attendee email addresses (optional)"
                },
                "location": {
                    "type": "string",
                    "description": "New event location (optional)"
                },
                "sensitivity": {
                    "type": "string",
                    "description": "Sensitivity level: low, medium, or high (optional)"
                }
            },
            "required": ["id"]
        }
    ),

    "delete_event": ToolMeta(
        name="delete_event",
        description=(
            "Permanently delete a calendar event. IRREVERSIBLE — the event cannot be recovered."
        ),
        reversible=False,
        scope_cost=0.8,
        input_schema={
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": "Event ID to permanently delete"
                }
            },
            "required": ["id"]
        }
    ),

    "check_conflicts": ToolMeta(
        name="check_conflicts",
        description=(
            "Check for calendar events that conflict with (overlap) a given time range. "
            "Returns all overlapping events. Useful for finding scheduling conflicts."
        ),
        reversible=True,
        scope_cost=0.1,
        input_schema={
            "type": "object",
            "properties": {
                "start_time": {
                    "type": "string",
                    "description": "Start of time range in ISO 8601 format, e.g. '2026-05-28T10:00:00Z'"
                },
                "end_time": {
                    "type": "string",
                    "description": "End of time range in ISO 8601 format, must be after start_time"
                }
            },
            "required": ["start_time", "end_time"]
        }
    ),
}


def get_all_tools() -> list[ToolMeta]:
    """Return all registered tools as a list."""
    return list(TOOL_REGISTRY.values())


def get_tool(name: str) -> ToolMeta:
    """Get a specific tool by name. Raises KeyError if not found."""
    if name not in TOOL_REGISTRY:
        raise KeyError(
            f"Unknown tool: '{name}'. "
            f"Available tools: {list(TOOL_REGISTRY.keys())}"
        )
    return TOOL_REGISTRY[name]


def is_reversible(tool_name: str) -> bool:
    """Check if a tool's action can be undone. Used by reward functions."""
    return get_tool(tool_name).reversible


def format_for_mcp() -> list[dict]:
    """
    Format all tools into the MCP tools/list response format.
    This is what gets returned when the LLM asks what tools are available.
    """
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "inputSchema": tool.input_schema
        }
        for tool in TOOL_REGISTRY.values()
    ]
