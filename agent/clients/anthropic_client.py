"""
Anthropic Client — Layer 0
Thin wrapper around the Anthropic SDK.
Normalises responses into a common ModelResponse format
so the agent loop works identically with any model provider.

Layer 0: Claude only.
Layer 2 will add OpenAI and Gemini clients.
"""

import logging
import os

import anthropic

from agent.response import ModelResponse, ToolCall

logger = logging.getLogger(__name__)


class AnthropicClient:
    """
    Anthropic API client for Claude models.
    Handles tool calling and response normalisation.
    """

    def __init__(
        self,
        model: str = "claude-sonnet-4-20250514",
        temperature: float = 0.1,
        max_tokens: int = 4096
    ):
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "ANTHROPIC_API_KEY environment variable not set. "
                "Export it before running: export ANTHROPIC_API_KEY=sk-..."
            )
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        logger.info("AnthropicClient initialised: model=%s", model)

    def call(self, messages: list[dict], tools: list[dict]) -> ModelResponse:
        """
        Call the Claude API with a list of messages and available tools.

        Args:
            messages: Conversation history in OpenAI-compatible format.
                      [{"role": "user", "content": "..."}, ...]
            tools:    List of tool definitions in MCP format.
                      Will be converted to Anthropic tool format internally.

        Returns:
            ModelResponse with text, tool_calls, and stop_reason.
        """
        # Convert MCP tool format to Anthropic tool format
        anthropic_tools = self._format_tools(tools)

        # Separate system message from conversation
        system_msg = ""
        conversation = []
        for msg in messages:
            if msg["role"] == "system":
                system_msg = msg["content"]
            else:
                conversation.append(msg)

        logger.debug(
            "Calling Claude: model=%s turns=%d tools=%d",
            self.model, len(conversation), len(anthropic_tools)
        )

        response = self.client.messages.create(
            model=self.model,
            system=system_msg,
            messages=conversation,
            tools=anthropic_tools,
            temperature=self.temperature,
            max_tokens=self.max_tokens
        )

        return self._normalise(response)

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
