import json
from typing import Any, Literal, Protocol, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T", bound=BaseModel)

Role = Literal["system", "user", "assistant", "tool"]


class ToolCallRequest(BaseModel):
    """A tool the model asked to call in a tool turn."""

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class Message(BaseModel):
    role: Role
    # Plain text, or OpenAI-style content parts (e.g. text + image_url) for multimodal calls.
    content: str | list[dict[str, Any]]
    tool_calls: list[ToolCallRequest] | None = None  # an assistant turn that called tools
    tool_call_id: str | None = None  # a `tool` message answers this call

    def to_payload(self) -> dict[str, Any]:
        """The OpenAI chat format LiteLLM expects (it translates for other providers)."""
        payload: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            payload["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
                }
                for call in self.tool_calls
            ]
        if self.tool_call_id is not None:
            payload["tool_call_id"] = self.tool_call_id
        return payload


class ToolSpec(BaseModel):
    """A function the model may call; `parameters` is its JSON schema."""

    name: str  # letters, digits, `_` and `-` only (provider function-name rules)
    description: str
    parameters: dict[str, Any]


class ToolTurn(BaseModel):
    """One model turn of a tool loop: the calls it made, and any text it wrote alongside."""

    tool_calls: list[ToolCallRequest] = Field(default_factory=list)
    content: str = ""


class LLMUsage(BaseModel):
    task: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: float


class LLMError(RuntimeError):
    """Every model in the task's chain failed, or structured output stayed invalid after a retry."""


class LLMClient(Protocol):
    async def structured(self, task: str, messages: list[Message], schema: type[T]) -> T: ...

    async def text(self, task: str, messages: list[Message]) -> str: ...

    async def tool_turn(
        self,
        task: str,
        messages: list[Message],
        tools: list[ToolSpec],
        *,
        require_tool: bool = True,
    ) -> ToolTurn:
        """One model turn that may call `tools`; with `require_tool` it must call one. Arguments
        come back parsed; arguments that are not a JSON object are retried once, then raise
        `LLMError`."""
        ...
