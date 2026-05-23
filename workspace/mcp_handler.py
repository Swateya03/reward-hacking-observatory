"""
MCP Handler — Layer 0
Handles the JSON-RPC 2.0 protocol that MCP uses.

Two methods implemented:
  - tools/list  → returns all available tools
  - tools/call  → executes a tool and returns the result

MCP message format:
  Request:  { "jsonrpc": "2.0", "id": 1, "method": "tools/call",
              "params": { "name": "list_files", "arguments": {...} } }
  Response: { "jsonrpc": "2.0", "id": 1,
              "result": { "content": [{ "type": "text", "text": "..." }] } }
"""

import json
import logging

from fastapi import Request
from fastapi.responses import JSONResponse

from workspace.tool_registry import format_for_mcp
from workspace.tools import file_tools
from workspace.tools import email_tools
from workspace.tools import calendar_tools

logger = logging.getLogger(__name__)


async def handle_mcp_request(request: Request) -> JSONResponse:
    """
    Main MCP protocol handler. Parses the JSON-RPC request,
    routes to the correct method, and returns a JSON-RPC response.
    """
    # Parse body
    try:
        body = await request.json()
    except Exception:
        return _error_response(None, -32700, "Parse error: invalid JSON")

    rpc_id = body.get("id")
    method = body.get("method")

    logger.debug("MCP request: method=%s id=%s", method, rpc_id)

    # Route by method
    if method == "tools/list":
        return _handle_tools_list(rpc_id)

    elif method == "tools/call":
        session_id = request.headers.get("x-session-id")
        if not session_id:
            return _error_response(
                rpc_id, -32602,
                "Missing required header: x-session-id. "
                "Every tool call must include a session ID."
            )
        return _handle_tools_call(rpc_id, body.get("params", {}), session_id)

    elif method in ("notifications/initialized", "initialize"):
        # MCP lifecycle notifications — acknowledge silently
        return JSONResponse(content=None, status_code=204)

    else:
        return _error_response(
            rpc_id, -32601,
            f"Method not found: '{method}'. "
            f"Supported methods: tools/list, tools/call"
        )


def _handle_tools_list(rpc_id) -> JSONResponse:
    """Return the list of all available tools in MCP format."""
    tools = format_for_mcp()
    return JSONResponse(content={
        "jsonrpc": "2.0",
        "id": rpc_id,
        "result": {
            "tools": tools
        }
    })


def _handle_tools_call(rpc_id, params: dict,
                        session_id: str) -> JSONResponse:
    """Execute a tool call and return the result in MCP format."""
    tool_name = params.get("name")
    arguments = params.get("arguments", {})

    if not tool_name:
        return _error_response(
            rpc_id, -32602,
            "Missing 'name' in tool call params"
        )

    logger.info(
        "Tool call: tool=%s session=%s args=%s",
        tool_name, session_id, arguments
    )

    # Route to the correct dispatcher based on tool name
    file_tools_set = {"list_files", "read_file", "move_to_trash"}
    email_tools_set = {"list_emails", "read_email", "save_draft", "send_email",
                       "move_email", "delete_email", "reply_email", "mark_read"}
    calendar_tools_set = {"list_events", "create_event", "update_event",
                          "delete_event", "check_conflicts"}

    try:
        if tool_name in file_tools_set:
            result = file_tools.dispatch(tool_name, arguments, session_id)
        elif tool_name in email_tools_set:
            result = email_tools.dispatch(tool_name, arguments, session_id)
        elif tool_name in calendar_tools_set:
            result = calendar_tools.dispatch(tool_name, arguments, session_id)
        else:
            return _error_response(
                rpc_id, -32601,
                f"Unknown tool: '{tool_name}'. "
                f"Available tools: {', '.join(sorted(file_tools_set | email_tools_set | calendar_tools_set))}"
            )
    except (KeyError, TypeError) as e:
        # Handle missing required arguments gracefully
        return _error_response(
            rpc_id, -32602,
            f"Invalid arguments for tool '{tool_name}': {str(e)}"
        )

    # Serialize result as text content (MCP standard)
    result_text = json.dumps(result, indent=2, ensure_ascii=False)

    return JSONResponse(content={
        "jsonrpc": "2.0",
        "id": rpc_id,
        "result": {
            "content": [
                {
                    "type": "text",
                    "text": result_text
                }
            ]
        }
    })


def _error_response(rpc_id, code: int, message: str) -> JSONResponse:
    """Return a JSON-RPC error response."""
    logger.warning("MCP error: code=%d message=%s", code, message)
    return JSONResponse(content={
        "jsonrpc": "2.0",
        "id": rpc_id,
        "error": {
            "code": code,
            "message": message
        }
    })
