from typing import Any, Literal, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

Role = Literal["system", "user", "assistant"]


class Message(BaseModel):
    role: Role
    # Plain text, or OpenAI-style content parts (e.g. text + image_url) for multimodal calls.
    content: str | list[dict[str, Any]]


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
