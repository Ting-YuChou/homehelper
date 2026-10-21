import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

from homehelper.llm import (
    FakeLLMClient,
    LiteLLMClient,
    LLMError,
    LLMUsage,
    Message,
    ModelRegistry,
    track_usage,
)

MESSAGES = [Message(role="user", content="hi")]


class Answer(BaseModel):
    value: int


def _response(content: str) -> Any:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
    )


class ScriptedCompletion:
    """Stands in for litellm.acompletion: maps model -> list of contents or exceptions."""

    def __init__(self, script: dict[str, list[Any]]) -> None:
        self.script = script
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        reply = self.script[kwargs["model"]].pop(0)
        if isinstance(reply, Exception):
            raise reply
        return _response(reply)


def _registry() -> ModelRegistry:
    return ModelRegistry.load(
        overrides={"nlu": {"model": "anthropic/primary", "fallbacks": ["openai/backup"]}}
    )


def _client(
    completion: ScriptedCompletion,
    keys: dict[str, str] | None = None,
    sink: list[LLMUsage] | None = None,
) -> LiteLLMClient:
    return LiteLLMClient(
        _registry(),
        keys if keys is not None else {"anthropic": "a", "openai": "o"},
        completion_fn=completion,
        usage_sink=sink.append if sink is not None else None,
    )


async def test_falls_back_when_primary_fails() -> None:
    completion = ScriptedCompletion(
        {"anthropic/primary": [RuntimeError("down")], "openai/backup": ["hello"]}
    )
    usage: list[LLMUsage] = []
    assert await _client(completion, sink=usage).text("nlu", MESSAGES) == "hello"
    assert [c["model"] for c in completion.calls] == ["anthropic/primary", "openai/backup"]
    assert completion.calls[1]["api_key"] == "o"
    assert [(u.model, u.input_tokens, u.output_tokens) for u in usage] == [("openai/backup", 10, 5)]


async def test_track_usage_collects_calls_in_scope_including_child_tasks() -> None:
    completion = ScriptedCompletion({"anthropic/primary": ["a", "b", "c"]})
    client = _client(completion)
    await client.text("nlu", MESSAGES)  # outside any scope: not counted
    with track_usage() as tally:
        await client.text("nlu", MESSAGES)
        await asyncio.create_task(client.text("nlu", MESSAGES))
    assert len(tally.calls) == 2
    assert (tally.input_tokens, tally.output_tokens) == (20, 10)


async def test_raises_when_every_model_fails() -> None:
    completion = ScriptedCompletion(
        {"anthropic/primary": [RuntimeError("a")], "openai/backup": [TimeoutError("b")]}
    )
    with pytest.raises(LLMError, match="all models failed"):
        await _client(completion).text("nlu", MESSAGES)


async def test_skips_models_without_api_key() -> None:
    completion = ScriptedCompletion({"openai/backup": ["only backup"]})
    result = await _client(completion, keys={"openai": "o"}).text("nlu", MESSAGES)
    assert result == "only backup"
    with pytest.raises(LLMError, match="no API key"):
        await _client(completion, keys={}).text("nlu", MESSAGES)


async def test_structured_output_parses_and_passes_schema() -> None:
    completion = ScriptedCompletion({"anthropic/primary": ['{"value": 3}']})
    assert await _client(completion).structured("nlu", MESSAGES, Answer) == Answer(value=3)
    assert completion.calls[0]["response_format"] is Answer


async def test_structured_output_retries_once_with_validation_errors() -> None:
    completion = ScriptedCompletion({"anthropic/primary": ['{"value": "x"}', '{"value": 4}']})
    assert await _client(completion).structured("nlu", MESSAGES, Answer) == Answer(value=4)
    retry_messages = completion.calls[1]["messages"]
    assert retry_messages[-2] == {"role": "assistant", "content": '{"value": "x"}'}
    assert "did not match the required JSON schema" in retry_messages[-1]["content"]


async def test_structured_output_fails_after_second_invalid_reply() -> None:
    completion = ScriptedCompletion({"anthropic/primary": ["nope", "still nope"]})
    with pytest.raises(LLMError, match="invalid after retry"):
        await _client(completion).structured("nlu", MESSAGES, Answer)


def test_registry_rejects_unknown_tasks() -> None:
    with pytest.raises(ValueError, match="unknown task"):
        ModelRegistry.load(overrides={"nope": {"model": "x/y"}})
    with pytest.raises(ValueError, match="unknown LLM task"):
        ModelRegistry.load().for_task("nope")


def test_default_registry_covers_spec_tasks() -> None:
    registry = ModelRegistry.load()
    for task in ("nlu", "planner", "responder", "supervisor", "vision", "user_simulator", "judge"):
        assert registry.for_task(task).model


async def test_fake_client_replays_script_and_records_calls() -> None:
    fake = FakeLLMClient(
        {
            "nlu": [{"value": 1}, Answer(value=2), lambda messages: '{"value": 3}'],
            "responder": ["text reply", RuntimeError("boom")],
        }
    )
    assert [await fake.structured("nlu", MESSAGES, Answer) for _ in range(3)] == [
        Answer(value=1),
        Answer(value=2),
        Answer(value=3),
    ]
    assert await fake.text("responder", MESSAGES) == "text reply"
    with pytest.raises(RuntimeError, match="boom"):
        await fake.text("responder", MESSAGES)
    with pytest.raises(AssertionError, match="no scripted reply"):
        await fake.text("responder", MESSAGES)
    assert [c.schema_name for c in fake.calls_for("nlu")] == ["Answer"] * 3
