"""
Workspace Client — Layer 0
HTTP client that talks to the workspace server.
Used by the agent loop to call tools and manage sessions.

Keeps all HTTP logic in one place so the agent loop stays clean.
"""

import json
import logging

import httpx

logger = logging.getLogger(__name__)

WORKSPACE_BASE_URL = "http://localhost:8000"
TIMEOUT = 30.0


class WorkspaceClient:
    """
    Client for the workspace server.
    Handles session management and MCP tool calls.
    """

    def __init__(self, base_url: str = WORKSPACE_BASE_URL):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(timeout=TIMEOUT)

    # ── Session management ────────────────────────────────────────────────────

    def create_session(self, fixture: str = "default") -> str:
        """Create a new session and return the session_id."""
        response = self.client.post(
            f"{self.base_url}/session/create",
            params={"fixture": fixture}
        )
        response.raise_for_status()
        data = response.json()
        session_id = data["session_id"]
        logger.info("Session created: %s (fixture=%s)", session_id, fixture)
        return session_id

    def reset_session(self, session_id: str,
                      fixture: str = "default") -> None:
        """Reset a session back to its initial state."""
        response = self.client.post(
            f"{self.base_url}/session/reset",
            params={"fixture": fixture},
            headers={"x-session-id": session_id}
        )
        response.raise_for_status()
        logger.info("Session reset: %s", session_id)

    def delete_session(self, session_id: str) -> None:
        """Delete a session after an episode ends."""
        response = self.client.request(
            "DELETE",
            f"{self.base_url}/session/delete",
            headers={"x-session-id": session_id}
        )
        response.raise_for_status()

    def get_state(self, session_id: str) -> dict:
        """
        Get raw DB state for a session.
        Used after episode ends to verify what actually changed.
        """
        response = self.client.get(
            f"{self.base_url}/session/state",
            headers={"x-session-id": session_id}
        )
        response.raise_for_status()
        return response.json()

    # ── MCP tool interface ────────────────────────────────────────────────────

    def get_tool_definitions(self) -> list[dict]:
        """
        Get all available tool definitions from the workspace server.
        Returns them in MCP format ready to pass to the model API.
        """
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {}
        }
        response = self.client.post(
            f"{self.base_url}/mcp",
            json=payload
        )
        response.raise_for_status()
        return response.json()["result"]["tools"]

    def call_tool(self, tool_name: str, arguments: dict,
                  session_id: str) -> dict:
        """
        Execute a tool call against the workspace server.

        Args:
            tool_name:  Name of the tool to call
            arguments:  Tool arguments dict
            session_id: Session to execute against

        Returns:
            Tool result as a plain dict
        """
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments
            }
        }
        response = self.client.post(
            f"{self.base_url}/mcp",
            json=payload,
            headers={"x-session-id": session_id}
        )
        response.raise_for_status()

        result = response.json()

        # Extract text content from MCP response
        content = result.get("result", {}).get("content", [])
        if content and content[0].get("type") == "text":
            text = content[0]["text"]
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"text": text}

        # Handle MCP errors
        if "error" in result:
            return {"error": result["error"]["message"]}

        return result

    def health_check(self) -> bool:
        """Check if the workspace server is running."""
        try:
            response = self.client.get(f"{self.base_url}/health")
            return response.status_code == 200
        except Exception:
            return False

    def close(self):
        """Close the HTTP client."""
        self.client.close()
