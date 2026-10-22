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
from tests.conftest import make_settings

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


async def test_json_object_mode_puts_the_schema_in_the_prompt() -> None:
    override = {"model": "openai/m", "fallbacks": [], "structured_output": "json_object"}
    registry = ModelRegistry.load(overrides={"nlu": override})
    completion = ScriptedCompletion({"openai/m": ['```json\n{"value": 5}\n```']})
    client = LiteLLMClient(registry, {"openai": "o"}, completion_fn=completion)
    assert await client.structured("nlu", MESSAGES, Answer) == Answer(value=5)
    call = completion.calls[0]
    assert call["response_format"] == {"type": "json_object"}
    assert '"value"' in call["messages"][-1]["content"]  # the JSON schema
    assert call["messages"][:-1] == [m.model_dump() for m in MESSAGES]


def test_registry_rejects_unknown_tasks() -> None:
    with pytest.raises(ValueError, match="unknown task"):
        ModelRegistry.load(overrides={"nope": {"model": "x/y"}})
    with pytest.raises(ValueError, match="unknown LLM task"):
        ModelRegistry.load().for_task("nope")


def test_default_registry_covers_spec_tasks() -> None:
    registry = ModelRegistry.load()
    for task in ("nlu", "planner", "responder", "supervisor", "vision", "user_simulator", "judge"):
        assert registry.for_task(task).model


def test_default_registry_never_uses_opencode_go() -> None:
    for config in ModelRegistry.load().tasks.values():
        assert not any(m.startswith("opencode_go/") for m in [config.model, *config.fallbacks])


def test_settings_expose_opencode_go_key_only_when_set() -> None:
    assert "opencode_go" not in make_settings().provider_api_keys()
    settings = make_settings(opencode_go_api_key="go-key")
    assert settings.provider_api_keys()["opencode_go"] == "go-key"


def _opencode_client(
    completion: ScriptedCompletion, model: str, sink: list[LLMUsage] | None = None
) -> LiteLLMClient:
    return LiteLLMClient(
        ModelRegistry.load(overrides={"nlu": {"model": model, "fallbacks": []}}),
        {"opencode_go": "go-key", "anthropic": "a"},
        opencode_go_base_url="https://go.test/inference/go/",
        session_id="s1",
        completion_fn=completion,
        usage_sink=sink.append if sink is not None else None,
    )


@pytest.mark.parametrize(
    ("model", "litellm_model", "api_base"),
    [
        ("opencode_go/openai/glm-5.3", "openai/glm-5.3", "https://go.test/inference/go/openai/v1"),
        (
            "opencode_go/anthropic/qwen3.8-max",
            "anthropic/qwen3.8-max",
            "https://go.test/inference/go/anthropic",
        ),
    ],
)
async def test_opencode_go_routes_by_wire_format(
    model: str, litellm_model: str, api_base: str
) -> None:
    completion = ScriptedCompletion({litellm_model: ["hi", "again"]})
    usage: list[LLMUsage] = []
    client = _opencode_client(completion, model, usage)
    assert await client.text("nlu", MESSAGES) == "hi"
    await client.text("nlu", MESSAGES)
    first, second = completion.calls
    assert first["api_key"] == "go-key"
    assert first["api_base"] == api_base
    assert first["extra_headers"]["x-opencode-session"] == "s1"
    assert first["extra_headers"]["User-Agent"].startswith("homehelper")
    assert second["extra_headers"] == first["extra_headers"]
    assert usage[0].model == model


async def test_opencode_go_rejects_unsupported_wire_format() -> None:
    completion = ScriptedCompletion({})
    for model in ("opencode_go/google/gemini-x", "opencode_go/glm-5.3"):
        with pytest.raises(LLMError, match="unsupported OpenCode Go model id"):
            await _opencode_client(completion, model).text("nlu", MESSAGES)
    assert completion.calls == []


async def test_other_providers_get_no_opencode_go_settings() -> None:
    completion = ScriptedCompletion({"anthropic/primary": ["hello"]})
    await _client(completion).text("nlu", MESSAGES)
    assert "api_base" not in completion.calls[0]
    assert "extra_headers" not in completion.calls[0]


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
