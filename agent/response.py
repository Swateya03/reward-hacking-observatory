"""
Shared response types used by all model clients.

These dataclasses normalise responses from different providers
(Anthropic, OpenAI, Gemini, etc.) into a common format
so the agent loop works identically regardless of backend.
"""

from dataclasses import dataclass, field


@dataclass
class ToolCall:
    """A single tool call requested by the model."""
    id: str
    name: str
    arguments: dict


@dataclass
class ModelResponse:
    """
    Normalised response from any model provider.
    The agent loop only ever sees this format — never raw API responses.
    """
    text: str                              # assistant's text content
    tool_calls: list[ToolCall]             # tool calls requested (may be empty)
    stop_reason: str                       # "end_turn", "tool_use", "max_tokens"
    raw: dict = field(default_factory=dict)  # original API response for debugging
