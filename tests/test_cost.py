"""Cost tracking, budget guard, prompt-cache breakpoints, budget stop.

Mocked client only. No API calls, no workspace server.
"""

import json
import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import config
from agent.cost import BudgetExceeded, CostTracker, cost_of_usage, worst_case_cost
from agent.loop import SYSTEM_PROMPT, AgentLoop
from agent.response import ModelResponse
from run_experiment import run_task


def _usage(inp=0, out=0, cw=0, cr=0):
    return {"input_tokens": inp, "output_tokens": out,
            "cache_creation_input_tokens": cw, "cache_read_input_tokens": cr}


# ── config ───────────────────────────────────────────────────────────────────

def test_config_model_budget_and_pricing_source():
    assert config.MODEL == "claude-haiku-5-5"
    assert config.BUDGET_USD == 6.50
    assert config.MAX_TOKENS == 2048
    assert config.PRICING_SOURCE == "https://platform.claude.com/docs/en/about-claude/pricing"
    assert config.PRICING_RETRIEVED == "2026-11-25"
    # Haiku 5.5 is the cheaper of the two priced models (base input and output)
    h5 = config.PRICING["claude-haiku-5-5"]["tiers"][0]
    h4 = config.PRICING["claude-haiku-4-5-20251001"]["tiers"][0]
    assert h5["input"] < h4["input"] and h5["output"] < h4["output"]


# ── cost arithmetic ──────────────────────────────────────────────────────────

def test_cost_of_usage_small_prompt_uses_tier_one():
    # 1000*0.10 + 200*0.125 + 3000*0.01 + 500*0.50 = 405 per million
    cost = cost_of_usage("claude-haiku-5-5", _usage(inp=1000, out=500, cw=200, cr=3000))
    assert cost == pytest.approx(405 / 1_000_000)


def test_cost_of_usage_long_prompt_uses_tier_two():
    # prompt counts input + cache writes + cache reads: 150,000 > 100,000 -> tier two prices
    cost = cost_of_usage("claude-haiku-5-5", _usage(inp=50_000, out=0, cw=0, cr=100_000))
    assert cost == pytest.approx((50_000 * 0.50 + 100_000 * 0.05) / 1_000_000)


def test_missing_usage_fields_count_as_zero():
    assert cost_of_usage("claude-haiku-5-5", {"input_tokens": 10, "output_tokens": None}) == \
        pytest.approx(10 * 0.10 / 1_000_000)


def test_worst_case_uses_most_expensive_input_rate_and_max_tokens():
    worst = worst_case_cost("claude-haiku-5-5", est_input_tokens=1000, max_tokens=2048)
    assert worst == pytest.approx((1000 * 0.20 + 2048 * 0.50) / 1_000_000)  # 0.20 = 1h cache write


# ── tracker: log, running total, resume ──────────────────────────────────────

def test_record_appends_jsonl_with_running_total(tmp_path):
    log = tmp_path / "cost_log.jsonl"
    t = CostTracker("claude-haiku-5-5", log_path=log, budget=6.5)
    t.set_task("task_001")
    e1 = t.record(step=1, usage=_usage(inp=1000, out=100))
    e2 = t.record(step=2, usage=_usage(cr=2000, out=50))
    lines = [json.loads(x) for x in log.read_text().splitlines()]
    assert len(lines) == 2
    assert lines[0]["task_id"] == "task_001" and lines[0]["step"] == 1
    assert lines[1]["running_total_usd"] == pytest.approx(e1["cost_usd"] + e2["cost_usd"], abs=1e-7)
    assert lines[1]["cache_read_input_tokens"] == 2000


def test_resumed_tracker_continues_the_running_total(tmp_path):
    log = tmp_path / "cost_log.jsonl"
    first = CostTracker("claude-haiku-5-5", log_path=log, budget=6.5)
    first.record(step=1, usage=_usage(inp=10_000, out=1000))
    total_before = first.total_usd
    second = CostTracker("claude-haiku-5-5", log_path=log, budget=6.5)
    assert second.total_usd == pytest.approx(total_before, abs=1e-7)
    assert second.calls == 1


# ── budget guard ─────────────────────────────────────────────────────────────

def test_guard_allows_a_call_within_budget(tmp_path):
    t = CostTracker("claude-haiku-5-5", log_path=tmp_path / "l.jsonl", budget=6.5)
    assert t.guard(est_input_tokens=5000, max_tokens=2048) > 0


def test_guard_raises_before_the_call_when_worst_case_exceeds_budget(tmp_path):
    t = CostTracker("claude-haiku-5-5", log_path=tmp_path / "l.jsonl", budget=1e-6)
    t.set_task("task_021")
    with pytest.raises(BudgetExceeded) as exc:
        t.guard(est_input_tokens=5000, max_tokens=2048, step=7)
    assert exc.value.task_id == "task_021"
    assert exc.value.step == 7
    assert exc.value.budget == 1e-6


def test_guard_counts_the_running_total(tmp_path):
    t = CostTracker("claude-haiku-5-5", log_path=tmp_path / "l.jsonl", budget=0.001)
    t.total_usd = 0.00099  # already spent
    with pytest.raises(BudgetExceeded):
        t.guard(est_input_tokens=1000, max_tokens=2048)


# ── client: cache_control breakpoints, usage logging, guard ──────────────────

def _fake_response(text="ok"):
    usage = SimpleNamespace(input_tokens=100, output_tokens=20,
                            cache_creation_input_tokens=0, cache_read_input_tokens=0)
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)],
                           stop_reason="end_turn", usage=usage,
                           model_dump=lambda: {"ok": True})


TOOLS = [
    {"name": "list_files", "description": "List files", "inputSchema": {"type": "object"}},
    {"name": "move_to_trash", "description": "Trash", "inputSchema": {"type": "object"}},
]


def _loop_messages(task_prompt="Delete old files"):
    """The first message exactly as AgentLoop builds it."""
    loop = AgentLoop(MagicMock(), MagicMock(), SimpleNamespace(id="t", prompt=task_prompt, fixture="default",
                                                              required_tools=[]))
    loop.session_id = "s"
    loop.workspace_client.create_session.return_value = "s"
    loop.workspace_client.get_tool_definitions.return_value = []
    loop.model_client.call.side_effect = [ModelResponse(text="done", tool_calls=[], stop_reason="end_turn")]
    loop.run(max_steps=1)
    return loop.model_client.call.call_args[0][0]


@pytest.fixture
def client(tmp_path):
    from agent.clients.anthropic_client import AnthropicClient
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}), patch("anthropic.Anthropic") as cls:
        sdk = MagicMock()
        cls.return_value = sdk
        c = AnthropicClient(cost_log_path=tmp_path / "cost_log.jsonl")
        c.sdk = sdk
        yield c


def test_cache_control_is_sent_on_tools_system_block_and_last_block(client):
    client.sdk.messages.create.return_value = _fake_response()
    messages = _loop_messages("Delete old files")
    client.call(messages, TOOLS, step=1)

    kwargs = client.sdk.messages.create.call_args.kwargs
    assert kwargs["tools"][-1]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in kwargs["tools"][0]
    first = kwargs["messages"][0]["content"]
    assert first[0]["cache_control"] == {"type": "ephemeral"}          # the system prompt block
    assert "cache_control" not in first[1]                              # the task text is not a breakpoint
    last = kwargs["messages"][-1]["content"]
    assert last[-1]["cache_control"] == {"type": "ephemeral"}


def test_at_most_three_cache_breakpoints_are_sent(client):
    client.sdk.messages.create.return_value = _fake_response()
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "c"}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "1", "content": "{}"}]},
    ]
    client.call(messages, TOOLS, step=2)
    kwargs = client.sdk.messages.create.call_args.kwargs
    blocks = [kwargs["tools"][-1]] + [b for m in kwargs["messages"] for b in m["content"]]
    assert sum("cache_control" in b for b in blocks) == 3


def test_prompt_text_is_unchanged_by_the_block_split(client):
    client.sdk.messages.create.return_value = _fake_response()
    messages = _loop_messages("Delete old files")
    client.call(messages, TOOLS, step=1)
    first = client.sdk.messages.create.call_args.kwargs["messages"][0]["content"]
    joined = "".join(b["text"] for b in first)
    assert joined == f"{SYSTEM_PROMPT}\n\nYour task: Delete old files"


def test_usage_is_logged_after_the_call(client):
    client.sdk.messages.create.return_value = _fake_response()
    client.set_task("task_001")
    client.call(_loop_messages(), TOOLS, step=3)
    entry = json.loads(client.cost.log_path.read_text().splitlines()[0])
    assert entry["task_id"] == "task_001"
    assert entry["step"] == 3
    assert entry["input_tokens"] == 100 and entry["output_tokens"] == 20
    assert entry["cost_usd"] == pytest.approx((100 * 0.10 + 20 * 0.50) / 1_000_000)


def test_guard_stops_before_the_request_is_sent(client):
    client.cost.budget = 1e-9
    with pytest.raises(BudgetExceeded):
        client.call(_loop_messages(), TOOLS, step=1)
    client.sdk.messages.create.assert_not_called()


def test_budget_stop_is_not_swallowed_as_a_task_failure(client):
    """run_task must re-raise BudgetExceeded so the run stops, instead of counting a failed task."""
    task = SimpleNamespace(id="task_001", prompt="x", fixture="default", required_tools=[],
                           ambiguity_level="low", expected_state={}, forbidden_tools=[],
                           min_irreversible_actions=0)
    workspace = MagicMock()
    workspace.create_session.return_value = "s"
    workspace.get_tool_definitions.return_value = []
    client.cost.budget = 1e-9
    with pytest.raises(BudgetExceeded):
        run_task(task, client, workspace, max_steps=3)


# ── model-specific request options ───────────────────────────────────────────

def test_haiku_5_5_request_omits_temperature_and_disables_thinking(client):
    client.sdk.messages.create.return_value = _fake_response()
    assert client.temperature is None
    client.call(_loop_messages(), TOOLS, step=1)
    kwargs = client.sdk.messages.create.call_args.kwargs
    assert "temperature" not in kwargs
    assert kwargs["thinking"] == {"type": "disabled"}


def test_haiku_4_5_request_sends_temperature_and_no_thinking_option(tmp_path):
    from agent.clients.anthropic_client import AnthropicClient
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}), patch("anthropic.Anthropic") as cls:
        sdk = MagicMock()
        cls.return_value = sdk
        sdk.messages.create.return_value = _fake_response()
        c = AnthropicClient(model="claude-haiku-4-5-20251001", cost_log_path=tmp_path / "l.jsonl")
        assert c.temperature == config.TEMPERATURE
        c.call(_loop_messages(), TOOLS, step=1)
        kwargs = sdk.messages.create.call_args.kwargs
    assert kwargs["temperature"] == config.TEMPERATURE
    assert "thinking" not in kwargs
