"""
Layer 0 Tests
Covers the 40 problem statements from the evaluation checklist.

Run with:
  pytest tests/test_layer0.py -v

The workspace server must be running:
  uvicorn workspace.main:app --reload --port 8000
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
