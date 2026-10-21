"""Per-scope LLM usage, e.g. the cost of one user turn for `messages.cost_usd` (spec §14.1).

Everything an `LLMClient` spends while a `track_usage()` block is active is added to the tally it
yields. The scope is a contextvar, so it follows async generators and asyncio tasks (LangGraph
nodes) started inside it. Scopes don't nest: an inner scope hides the outer one.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from pydantic import BaseModel, Field

from homehelper.llm.types import LLMUsage


class UsageTally(BaseModel):
    calls: list[LLMUsage] = Field(default_factory=list)

    @property
    def cost_usd(self) -> float:
        return sum(call.cost_usd for call in self.calls)

    @property
    def input_tokens(self) -> int:
        return sum(call.input_tokens for call in self.calls)

    @property
    def output_tokens(self) -> int:
        return sum(call.output_tokens for call in self.calls)


_current: ContextVar[UsageTally | None] = ContextVar("llm_usage_tally", default=None)


@contextmanager
def track_usage() -> Iterator[UsageTally]:
    tally = UsageTally()
    token = _current.set(tally)
    try:
        yield tally
    finally:
        _current.reset(token)


def record_usage(usage: LLMUsage) -> None:
    """Called by LLM clients after every successful call; a no-op outside `track_usage()`."""
    tally = _current.get()
    if tally is not None:
        tally.calls.append(usage)
