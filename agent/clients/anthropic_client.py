"""
Anthropic Client — Layer 0
Thin wrapper around the Anthropic SDK.
Normalises responses into a common ModelResponse format
so the agent loop works identically with any model provider.

Layer 0: Claude only.
Layer 2 will add OpenAI and Gemini clients.

Prompt caching (Anthropic docs: build-with-claude/prompt-caching): cache_control
breakpoints are placed on
  1. the last tool definition (caches the tool list),
  2. the first content block of the first user message (the system prompt; this
     caches tools + system), and
  3. the last content block of the last message (caches the growing conversation).
That is 3 of the 4 breakpoints allowed. Each call first checks the budget
(agent/cost.py) and then logs its usage.
"""

import copy
import json
import logging
import os

import anthropic

from agent.cost import CostTracker
from agent.response import ModelResponse, ToolCall
import config
from config import MAX_TOKENS, MODEL, TEMPERATURE

logger = logging.getLogger(__name__)

CACHE_CONTROL = {"type": "ephemeral"}


class AnthropicClient:
    """
    Anthropic API client for Claude models.
    Handles tool calling, prompt caching, budget guard and cost logging.
    """

    def __init__(
        self,
        model: str = MODEL,
        temperature: float = TEMPERATURE,
        max_tokens: int = MAX_TOKENS,
        cost_tracker: CostTracker | None = None,
        cost_log_path=None,
    ):
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "ANTHROPIC_API_KEY environment variable not set. "
                "Export it before running: export ANTHROPIC_API_KEY=sk-..."
            )
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        options = config.MODEL_OPTIONS.get(model, {})
        # Some models reject temperature (docs: "Omit temperature, top_p, and top_k").
        # The value actually sent is recorded in metadata, so None means "not sent".
        self.temperature = temperature if options.get("temperature", temperature) is not None else None
        self.thinking = options.get("thinking")
        self.max_tokens = max_tokens
        self.cost = cost_tracker or CostTracker(model, log_path=cost_log_path)
        logger.info("AnthropicClient initialised: model=%s", model)

    def set_task(self, task_id: str | None) -> None:
        """Label subsequent cost-log entries with the task they belong to."""
        self.cost.set_task(task_id)

    def call(self, messages: list[dict], tools: list[dict], step: int | None = None) -> ModelResponse:
        """
        Call the Claude API with a list of messages and available tools.

        Args:
            messages: Conversation history in OpenAI-compatible format.
                      [{"role": "user", "content": "..."}, ...]
            tools:    List of tool definitions in MCP format.
                      Will be converted to Anthropic tool format internally.
            step:     Step number, recorded in the cost log.

        Returns:
            ModelResponse with text, tool_calls, and stop_reason.

        Raises:
            BudgetExceeded (before the request is sent) if the worst case for this call
            would take the running total over config.BUDGET_USD.
        """
        # Convert MCP tool format to Anthropic tool format
        anthropic_tools = self._format_tools(tools)
        if anthropic_tools:
            anthropic_tools[-1]["cache_control"] = dict(CACHE_CONTROL)

        # Separate system message from conversation
        system_msg = ""
        conversation = []
        for msg in messages:
            if msg["role"] == "system":
                system_msg = msg["content"]
            else:
                conversation.append(msg)
        conversation = self._with_breakpoints(conversation)

        # Upper bound on input tokens: one token per character of the serialised request.
        # Deliberately generous, so the guard never under-estimates.
        est_input = len(json.dumps(anthropic_tools)) + len(system_msg) + len(json.dumps(conversation))
        self.cost.guard(est_input, self.max_tokens, step=step)

        logger.debug(
            "Calling Claude: model=%s turns=%d tools=%d",
            self.model, len(conversation), len(anthropic_tools)
        )

        kwargs = dict(
            model=self.model,
            messages=conversation,
            tools=anthropic_tools,
            max_tokens=self.max_tokens,
        )
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        if self.thinking is not None:
            kwargs["thinking"] = self.thinking
        if system_msg:
            kwargs["system"] = system_msg
        response = self.client.messages.create(**kwargs)

        self.cost.record(step, self._usage_dict(response.usage))
        return self._normalise(response)

    @staticmethod
    def _usage_dict(usage) -> dict:
        return {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cache_creation_input_tokens": usage.cache_creation_input_tokens,
            "cache_read_input_tokens": usage.cache_read_input_tokens,
        }

    @staticmethod
    def _with_breakpoints(conversation: list[dict]) -> list[dict]:
        """Copy the conversation and add cache_control to the first block of the first
        message and to the last block of the last message. Strings become text blocks."""
        conv = copy.deepcopy(conversation)
        if not conv:
            return conv
        for msg in (conv[0], conv[-1]):
            if isinstance(msg["content"], str):
                msg["content"] = [{"type": "text", "text": msg["content"]}]
        conv[0]["content"][0]["cache_control"] = dict(CACHE_CONTROL)
        conv[-1]["content"][-1]["cache_control"] = dict(CACHE_CONTROL)
        return conv

    def _format_tools(self, tools: list[dict]) -> list[dict]:
        """Convert MCP tool format to Anthropic API tool format."""
        return [
            {
                "name": t["name"],
                "description": t["description"],
                "input_schema": t["inputSchema"]
            }
            for t in tools
        ]

    def _normalise(self, response) -> ModelResponse:
        """Convert raw Anthropic response to ModelResponse."""
        text_parts = []
        tool_calls = []

        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.id,
                    name=block.name,
                    arguments=block.input
                ))

        return ModelResponse(
            text=" ".join(text_parts),
            tool_calls=tool_calls,
            stop_reason=response.stop_reason,
            raw=response.model_dump()
        )
