"""Scripted LLMClient for unit and integration tests (spec P6)."""

from collections import defaultdict, deque
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from pydantic import BaseModel

from homehelper.llm.types import Message, T

# A scripted reply: a model instance or dict (structured), a str (text), an exception to raise,
# or a callable that receives the messages and returns one of those.
Reply = BaseModel | dict[str, Any] | str | Exception | Callable[[list[Message]], Any]


class FakeCall(BaseModel):
    task: str
    messages: list[Message]
    schema_name: str | None


class FakeLLMClient:
    def __init__(self, script: Mapping[str, Iterable[Reply]] | None = None) -> None:
        self._queues: dict[str, deque[Reply]] = defaultdict(deque)
        self.calls: list[FakeCall] = []
        for task, replies in (script or {}).items():
            self.add(task, *replies)

    def add(self, task: str, *replies: Reply) -> None:
        self._queues[task].extend(replies)

    def calls_for(self, task: str) -> list[FakeCall]:
        return [call for call in self.calls if call.task == task]

    async def text(self, task: str, messages: list[Message]) -> str:
        reply = self._next(task, messages, schema_name=None)
        if not isinstance(reply, str):
            raise TypeError(f"scripted reply for text task {task!r} must be str, got {reply!r}")
        return reply

    async def structured(self, task: str, messages: list[Message], schema: type[T]) -> T:
        reply = self._next(task, messages, schema_name=schema.__name__)
        if isinstance(reply, schema):
            return reply
        if isinstance(reply, BaseModel):
            return schema.model_validate(reply.model_dump())
        if isinstance(reply, str):
            return schema.model_validate_json(reply)
        return schema.model_validate(reply)

    def _next(self, task: str, messages: list[Message], schema_name: str | None) -> Any:
        self.calls.append(FakeCall(task=task, messages=messages, schema_name=schema_name))
        queue = self._queues[task]
        if not queue:
            raise AssertionError(f"FakeLLMClient: no scripted reply left for task {task!r}")
        reply = queue.popleft()
        if callable(reply) and not isinstance(reply, BaseModel | type):
            reply = reply(messages)
        if isinstance(reply, Exception):
            raise reply
        return reply
