import asyncio
import functools
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
    ToolCallRequest,
    ToolSpec,
    ToolTurn,
    litellm_client,  # imports litellm after setting LITELLM_MODE
    track_usage,
)
from tests.conftest import make_settings

MESSAGES = [Message(role="user", content="hi")]


class Answer(BaseModel):
    value: int


def _response(content: Any) -> Any:
    # A str is a text reply; a list of (name, raw arguments) pairs is a tool-calling reply.
    if isinstance(content, list):
        calls = [
            SimpleNamespace(id=f"call_{i}", function=SimpleNamespace(name=name, arguments=args))
            for i, (name, args) in enumerate(content)
        ]
        message = SimpleNamespace(content=None, tool_calls=calls)
    else:
        message = SimpleNamespace(content=content, tool_calls=None)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message)],
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
    assert call["messages"][:-1] == [m.to_payload() for m in MESSAGES]


async def test_reasoning_effort_is_sent_only_when_set() -> None:
    plain = {"model": "openai/m", "fallbacks": []}
    registry = ModelRegistry.load(
        overrides={"nlu": {**plain, "reasoning_effort": "none"}, "supervisor": plain}
    )
    completion = ScriptedCompletion({"openai/m": ['{"value": 1}', '{"value": 2}']})
    client = LiteLLMClient(registry, {"openai": "o"}, completion_fn=completion)
    await client.structured("nlu", MESSAGES, Answer)
    await client.structured("supervisor", MESSAGES, Answer)
    assert completion.calls[0]["reasoning_effort"] == "none"
    assert "reasoning_effort" not in completion.calls[1]


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


LOOKUP = ToolSpec(
    name="parts_catalog__search_parts",
    description="Search parts",
    parameters={"type": "object", "properties": {"symptom": {"type": "string"}}},
)


async def test_tool_turn_sends_tools_and_parses_calls() -> None:
    completion = ScriptedCompletion(
        {"anthropic/primary": [[("parts_catalog__search_parts", '{"symptom": "no drain"}')]]}
    )
    turn = await _client(completion).tool_turn("nlu", MESSAGES, [LOOKUP])
    assert turn.tool_calls == [
        ToolCallRequest(
            id="call_0", name="parts_catalog__search_parts", arguments={"symptom": "no drain"}
        )
    ]
    sent = completion.calls[0]
    assert sent["tool_choice"] == "auto"  # thinking modes reject a forced choice
    assert sent["tools"] == [{"type": "function", "function": LOOKUP.model_dump()}]


async def test_tool_turn_through_litellm_does_not_load_its_mcp_bridge() -> None:
    """LiteLLM's MCP bridge needs mcp>=2; importing it failed every tool call (we pin mcp<2)."""
    call = {"id": "c1", "type": "function", "function": {"name": LOOKUP.name, "arguments": "{}"}}
    client = LiteLLMClient(
        _registry(),
        {"anthropic": "a", "openai": "o"},
        completion_fn=functools.partial(litellm_client.litellm.acompletion, mock_tool_calls=[call]),
    )
    turn = await client.tool_turn("nlu", MESSAGES, [LOOKUP])
    assert [c.name for c in turn.tool_calls] == [LOOKUP.name]


async def test_tool_turn_retries_once_on_bad_arguments_then_fails() -> None:
    bad = [("parts_catalog__search_parts", "{not json")]
    good = [("parts_catalog__search_parts", "{}")]
    completion = ScriptedCompletion({"anthropic/primary": [bad, good, bad, ["x"]]})
    client = _client(completion)
    assert (await client.tool_turn("nlu", MESSAGES, [LOOKUP])).tool_calls[0].arguments == {}
    completion.script["anthropic/primary"] = [bad, '"no call"']
    with pytest.raises(LLMError, match="tool call invalid after retry"):
        await client.tool_turn("nlu", MESSAGES, [LOOKUP])


async def test_tool_turn_without_requirement_may_answer_in_text() -> None:
    completion = ScriptedCompletion({"anthropic/primary": ["just text"]})
    turn = await _client(completion).tool_turn("nlu", MESSAGES, [LOOKUP], require_tool=False)
    assert turn == ToolTurn(content="just text")
    assert completion.calls[0]["tool_choice"] == "auto"


async def test_tool_turn_falls_back_and_reports_usage() -> None:
    sink: list[LLMUsage] = []
    completion = ScriptedCompletion(
        {
            "anthropic/primary": [RuntimeError("down")],
            "openai/backup": [[("parts_catalog__search_parts", "{}")]],
        }
    )
    await _client(completion, sink=sink).tool_turn("nlu", MESSAGES, [LOOKUP])
    assert [u.model for u in sink] == ["openai/backup"]


async def test_tool_history_is_sent_in_openai_format() -> None:
    call = ToolCallRequest(id="c1", name="parts_catalog__search_parts", arguments={"a": 1})
    history = [
        *MESSAGES,
        Message(role="assistant", content="", tool_calls=[call]),
        Message(role="tool", content='{"parts": []}', tool_call_id="c1"),
    ]
    completion = ScriptedCompletion({"anthropic/primary": ["done"]})
    await _client(completion).text("nlu", history)
    sent = completion.calls[0]["messages"]
    assert sent[0] == {"role": "user", "content": "hi"}
    assert sent[1]["tool_calls"] == [
        {
            "id": "c1",
            "type": "function",
            "function": {"name": "parts_catalog__search_parts", "arguments": '{"a": 1}'},
        }
    ]
    assert sent[2] == {"role": "tool", "content": '{"parts": []}', "tool_call_id": "c1"}


async def test_fake_client_scripts_tool_turns() -> None:
    fake = FakeLLMClient(
        {
            "responder": [
                {"tool_calls": [{"id": "1", "name": "service_booking__book", "arguments": {}}]},
                ToolTurn(),
            ]
        }
    )
    turn = await fake.tool_turn("responder", MESSAGES, [LOOKUP])
    assert turn.tool_calls[0].name == "service_booking__book"  # not offered: passed through
    assert fake.calls[0].tools == ["parts_catalog__search_parts"]
    with pytest.raises(AssertionError, match="must call a tool"):
        await fake.tool_turn("responder", MESSAGES, [LOOKUP])
