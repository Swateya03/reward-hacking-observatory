"""
Layer 2 Tests
Covers TaskBank, ModelResponse, AnthropicClient, and AgentLoop.

Run with:
  pytest tests/test_layer2.py -v

No real API calls — everything is mocked.
"""

import json
import os
import time
from unittest.mock import MagicMock, Mock, patch

import pytest

from agent.clients.anthropic_client import AnthropicClient
from agent.loop import AgentLoop
from agent.response import ModelResponse, ToolCall
from agent.workspace_client import WorkspaceClient
from tasks.task import Task, TaskBank


# ── TaskBank Tests ─────────────────────────────────────────────────────────

class TestTaskBank:
    """Tests for TaskBank loading and filtering."""

    def test_load_task_bank(self):
        """Load task_bank.json and verify 30 tasks are loaded."""
        bank = TaskBank("tasks/task_bank.json")
        assert bank.count() == 30, f"Expected 30 tasks, got {bank.count()}"

    def test_get_by_ambiguity_low(self):
        """get_by_ambiguity('low') returns exactly 10 tasks."""
        bank = TaskBank("tasks/task_bank.json")
        tasks = bank.get_by_ambiguity("low")
        assert len(tasks) == 10, f"Expected 10 low tasks, got {len(tasks)}"
        for task in tasks:
            assert task.ambiguity_level == "low"

    def test_get_by_ambiguity_medium(self):
        """get_by_ambiguity('medium') returns exactly 10 tasks."""
        bank = TaskBank("tasks/task_bank.json")
        tasks = bank.get_by_ambiguity("medium")
        assert len(tasks) == 10, f"Expected 10 medium tasks, got {len(tasks)}"
        for task in tasks:
            assert task.ambiguity_level == "medium"

    def test_get_by_ambiguity_high(self):
        """get_by_ambiguity('high') returns exactly 10 tasks."""
        bank = TaskBank("tasks/task_bank.json")
        tasks = bank.get_by_ambiguity("high")
        assert len(tasks) == 10, f"Expected 10 high tasks, got {len(tasks)}"
        for task in tasks:
            assert task.ambiguity_level == "high"

    def test_get_by_id(self):
        """get_by_id returns the correct task by ID."""
        bank = TaskBank("tasks/task_bank.json")
        task = bank.get_by_id("task_001")
        assert task.id == "task_001"
        assert task.ambiguity_level == "low"

    def test_get_by_id_not_found(self):
        """get_by_id raises KeyError for unknown task."""
        bank = TaskBank("tasks/task_bank.json")
        with pytest.raises(KeyError):
            bank.get_by_id("nonexistent_task")

    def test_get_simple_tasks(self):
        """get_simple_tasks returns only low-ambiguity tasks."""
        bank = TaskBank("tasks/task_bank.json")
        tasks = bank.get_simple_tasks()
        assert len(tasks) == 10
        for task in tasks:
            assert task.ambiguity_level == "low"

    def test_all_tasks_have_required_fields(self):
        """All tasks have required fields."""
        bank = TaskBank("tasks/task_bank.json")
        required_fields = {
            "id", "prompt", "ambiguity_level", "fixture",
            "reward_hack_temptation"
        }

        for task in bank.get_all():
            for field in required_fields:
                assert hasattr(task, field), (
                    f"Task {task.id} missing field: {field}"
                )
                value = getattr(task, field)
                assert value is not None, (
                    f"Task {task.id} field {field} is None"
                )


# ── ModelResponse Tests ────────────────────────────────────────────────────

class TestModelResponse:
    """Tests for response dataclasses."""

    def test_tool_call_initialises(self):
        """ToolCall dataclass initialises with id, name, arguments."""
        tc = ToolCall(id="call_123", name="list_files", arguments={"folder": "/tmp"})
        assert tc.id == "call_123"
        assert tc.name == "list_files"
        assert tc.arguments == {"folder": "/tmp"}

    def test_model_response_empty_tool_calls(self):
        """ModelResponse initialises with empty tool_calls."""
        resp = ModelResponse(
            text="Hello",
            tool_calls=[],
            stop_reason="end_turn"
        )
        assert resp.text == "Hello"
        assert resp.tool_calls == []
        assert resp.stop_reason == "end_turn"
        assert resp.raw == {}

    def test_model_response_with_tool_calls(self):
        """ModelResponse initialises with tool_calls."""
        calls = [
            ToolCall(id="1", name="list_files", arguments={"folder": "/tmp"})
        ]
        resp = ModelResponse(
            text="Let me list files",
            tool_calls=calls,
            stop_reason="tool_use"
        )
        assert resp.text == "Let me list files"
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].name == "list_files"

    def test_model_response_raw_default(self):
        """ModelResponse.raw defaults to empty dict."""
        resp = ModelResponse(
            text="Test",
            tool_calls=[],
            stop_reason="end_turn"
        )
        assert isinstance(resp.raw, dict)
        assert resp.raw == {}


# ── AnthropicClient Tests ──────────────────────────────────────────────────

class TestAnthropicClient:
    """Tests for AnthropicClient (mocked)."""

    def test_missing_api_key_raises_error(self):
        """Missing ANTHROPIC_API_KEY raises EnvironmentError."""
        # Save original key
        original_key = os.environ.get("ANTHROPIC_API_KEY")
        try:
            # Remove the key
            if "ANTHROPIC_API_KEY" in os.environ:
                del os.environ["ANTHROPIC_API_KEY"]

            with pytest.raises(EnvironmentError):
                AnthropicClient()
        finally:
            # Restore the key
            if original_key:
                os.environ["ANTHROPIC_API_KEY"] = original_key

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
    @patch("anthropic.Anthropic")
    def test_format_tools_converts_mcp_to_anthropic(self, mock_anthropic_cls):
        """_format_tools converts MCP format to Anthropic format."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client

        client = AnthropicClient()

        mcp_tools = [
            {
                "name": "list_files",
                "description": "List files",
                "inputSchema": {
                    "type": "object",
                    "properties": {"folder": {"type": "string"}}
                }
            }
        ]

        anthropic_tools = client._format_tools(mcp_tools)

        assert len(anthropic_tools) == 1
        assert anthropic_tools[0]["name"] == "list_files"
        assert anthropic_tools[0]["description"] == "List files"
        assert "input_schema" in anthropic_tools[0]

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
    @patch("anthropic.Anthropic")
    def test_normalise_text_only_response(self, mock_anthropic_cls):
        """_normalise handles text-only response correctly."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client

        client = AnthropicClient()

        # Mock response with text only
        mock_response = MagicMock()
        mock_response.content = [
            MagicMock(type="text", text="Hello there")
        ]
        mock_response.stop_reason = "end_turn"
        mock_response.model_dump.return_value = {"test": "data"}

        result = client._normalise(mock_response)

        assert isinstance(result, ModelResponse)
        assert result.text == "Hello there"
        assert result.tool_calls == []
        assert result.stop_reason == "end_turn"

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
    @patch("anthropic.Anthropic")
    def test_normalise_tool_use_response(self, mock_anthropic_cls):
        """_normalise handles tool_use response correctly."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client

        client = AnthropicClient()

        # Mock response with tool_use
        mock_response = MagicMock()
        mock_tool_use = MagicMock()
        mock_tool_use.type = "tool_use"
        mock_tool_use.id = "tool_123"
        mock_tool_use.name = "list_files"
        mock_tool_use.input = {"folder": "/tmp"}

        mock_response.content = [
            MagicMock(type="text", text="Let me list files"),
            mock_tool_use
        ]
        mock_response.stop_reason = "tool_use"
        mock_response.model_dump.return_value = {"test": "data"}

        result = client._normalise(mock_response)

        assert result.text == "Let me list files"
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].id == "tool_123"
        assert result.tool_calls[0].name == "list_files"


# ── AgentLoop Tests ────────────────────────────────────────────────────────

class TestAgentLoop:
    """Tests for AgentLoop (fully mocked)."""

    @patch("agent.loop.WorkspaceClient")
    @patch("agent.loop.AnthropicClient")
    def test_run_returns_trajectory(self, mock_model_cls, mock_workspace_cls):
        """run() returns a list of trajectory steps."""
        # Setup mocks
        mock_workspace = MagicMock()
        mock_workspace.create_session.return_value = "session_123"
        mock_workspace.get_tool_definitions.return_value = []
        mock_workspace_cls.return_value = mock_workspace

        mock_model = MagicMock()
        # Return a completion response (text, no tool calls)
        mock_response = ModelResponse(
            text="Task completed",
            tool_calls=[],
            stop_reason="end_turn"
        )
        mock_model.call.return_value = mock_response
        mock_model_cls.return_value = mock_model

        # Create task
        task = Task(
            id="test_001",
            prompt="Test task",
            ambiguity_level="low",
            fixture="default",
            expected_state={},
            required_tools=[]
        )

        # Run loop
        loop = AgentLoop(mock_model, mock_workspace, task)
        trajectory = loop.run(max_steps=20)

        assert isinstance(trajectory, list)
        assert len(trajectory) > 0

    @patch("agent.loop.WorkspaceClient")
    @patch("agent.loop.AnthropicClient")
    def test_trajectory_step_fields(self, mock_model_cls, mock_workspace_cls):
        """Each step has required fields."""
        mock_workspace = MagicMock()
        mock_workspace.create_session.return_value = "session_123"
        mock_workspace.get_tool_definitions.return_value = []
        mock_workspace_cls.return_value = mock_workspace

        mock_model = MagicMock()
        mock_response = ModelResponse(
            text="Done",
            tool_calls=[],
            stop_reason="end_turn"
        )
        mock_model.call.return_value = mock_response
        mock_model_cls.return_value = mock_model

        task = Task(
            id="test_001",
            prompt="Test",
            ambiguity_level="low",
            fixture="default",
            expected_state={},
            required_tools=[]
        )

        loop = AgentLoop(mock_model, mock_workspace, task)
        trajectory = loop.run(max_steps=20)

        required_fields = {
            "step", "type", "tool", "arguments", "result",
            "reversible", "was_in_task_scope", "reasoning_before", "timestamp"
        }

        for step in trajectory:
            for field in required_fields:
                assert field in step, f"Step missing field: {field}"
                assert step[field] is not None or field in (
                    "tool", "arguments", "result", "reversible"
                ), f"Field {field} should be None for this step type"

    @patch("agent.loop.WorkspaceClient")
    @patch("agent.loop.AnthropicClient")
    def test_completion_detected(self, mock_model_cls, mock_workspace_cls):
        """Completion detected when stop_reason='end_turn' and no tool calls."""
        mock_workspace = MagicMock()
        mock_workspace.create_session.return_value = "session_123"
        mock_workspace.get_tool_definitions.return_value = []
        mock_workspace_cls.return_value = mock_workspace

        mock_model = MagicMock()
        mock_response = ModelResponse(
            text="Task is complete",
            tool_calls=[],
            stop_reason="end_turn"
        )
        mock_model.call.return_value = mock_response
        mock_model_cls.return_value = mock_model

        task = Task(
            id="test_001",
            prompt="Test",
            ambiguity_level="low",
            fixture="default",
            expected_state={},
            required_tools=[]
        )

        loop = AgentLoop(mock_model, mock_workspace, task)
        trajectory = loop.run(max_steps=20)

        # Last step should be completion type
        assert trajectory[-1]["type"] == "completion"

    @patch("agent.loop.WorkspaceClient")
    @patch("agent.loop.AnthropicClient")
    def test_clarification_detected(self, mock_model_cls, mock_workspace_cls):
        """Clarification detected when response has '?' and no tool calls."""
        mock_workspace = MagicMock()
        mock_workspace.create_session.return_value = "session_123"
        mock_workspace.get_tool_definitions.return_value = []
        mock_workspace_cls.return_value = mock_workspace

        mock_model = MagicMock()
        mock_response = ModelResponse(
            text="Should I delete all files or just old ones?",
            tool_calls=[],
            stop_reason="end_turn"
        )
        mock_model.call.return_value = mock_response
        mock_model_cls.return_value = mock_model

        task = Task(
            id="test_001",
            prompt="Test",
            ambiguity_level="high",
            fixture="default",
            expected_state={},
            required_tools=[]
        )

        loop = AgentLoop(mock_model, mock_workspace, task)
        trajectory = loop.run(max_steps=20)

        # Last step should be clarification type
        assert trajectory[-1]["type"] == "clarification"

    @patch("agent.loop.WorkspaceClient")
    @patch("agent.loop.AnthropicClient")
    def test_was_in_task_scope_true(self, mock_model_cls, mock_workspace_cls):
        """was_in_task_scope=True when tool is in task.required_tools."""
        mock_workspace = MagicMock()
        mock_workspace.create_session.return_value = "session_123"
        mock_workspace.get_tool_definitions.return_value = [
            {
                "name": "list_files",
                "description": "List files",
                "inputSchema": {}
            }
        ]
        mock_workspace.call_tool.return_value = {"files": []}
        mock_workspace_cls.return_value = mock_workspace

        mock_model = MagicMock()
        # First call: tool use, second call: completion
        tool_call = ToolCall(
            id="call_1",
            name="list_files",
            arguments={"folder": "/tmp"}
        )
        responses = [
            ModelResponse(
                text="Let me list files",
                tool_calls=[tool_call],
                stop_reason="tool_use"
            ),
            ModelResponse(
                text="Done",
                tool_calls=[],
                stop_reason="end_turn"
            )
        ]
        mock_model.call.side_effect = responses
        mock_model_cls.return_value = mock_model

        task = Task(
            id="test_001",
            prompt="Test",
            ambiguity_level="low",
            fixture="default",
            expected_state={},
            required_tools=["list_files"]  # list_files is required
        )

        loop = AgentLoop(mock_model, mock_workspace, task)
        trajectory = loop.run(max_steps=20)

        # Find the tool_call step
        tool_call_steps = [s for s in trajectory if s["type"] == "tool_call"]
        assert len(tool_call_steps) > 0
        assert tool_call_steps[0]["was_in_task_scope"] is True

    @patch("agent.loop.WorkspaceClient")
    @patch("agent.loop.AnthropicClient")
    def test_was_in_task_scope_false(self, mock_model_cls, mock_workspace_cls):
        """was_in_task_scope=False when tool is not in task.required_tools."""
        mock_workspace = MagicMock()
        mock_workspace.create_session.return_value = "session_123"
        mock_workspace.get_tool_definitions.return_value = [
            {
                "name": "list_files",
                "description": "List files",
                "inputSchema": {}
            }
        ]
        mock_workspace.call_tool.return_value = {"files": []}
        mock_workspace_cls.return_value = mock_workspace

        mock_model = MagicMock()
        tool_call = ToolCall(
            id="call_1",
            name="list_files",
            arguments={"folder": "/tmp"}
        )
        responses = [
            ModelResponse(
                text="Let me list files",
                tool_calls=[tool_call],
                stop_reason="tool_use"
            ),
            ModelResponse(
                text="Done",
                tool_calls=[],
                stop_reason="end_turn"
            )
        ]
        mock_model.call.side_effect = responses
        mock_model_cls.return_value = mock_model

        task = Task(
            id="test_001",
            prompt="Test",
            ambiguity_level="low",
            fixture="default",
            expected_state={},
            required_tools=["send_email"]  # list_files is NOT required
        )

        loop = AgentLoop(mock_model, mock_workspace, task)
        trajectory = loop.run(max_steps=20)

        # Find the tool_call step
        tool_call_steps = [s for s in trajectory if s["type"] == "tool_call"]
        assert len(tool_call_steps) > 0
        assert tool_call_steps[0]["was_in_task_scope"] is False


if __name__ == "__main__":
    import subprocess
    subprocess.run(["pytest", __file__, "-v", "--tb=short"])
