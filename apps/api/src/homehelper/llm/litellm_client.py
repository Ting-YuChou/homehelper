"""LLMClient backed by the LiteLLM SDK (library mode, no proxy)."""

import json
import logging
import os
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from contextlib import nullcontext
from typing import Any

# LiteLLM loads `.env` into os.environ on import unless told otherwise; configuration comes only
# from Settings, so keep secrets out of the process environment.
os.environ.setdefault("LITELLM_MODE", "PRODUCTION")

import litellm
from litellm.cost_calculator import get_response_cost_from_hidden_params
from pydantic import BaseModel, ValidationError

from homehelper.core.logging import get_logger
from homehelper.core.tracing import Tracer
from homehelper.llm.registry import ModelRegistry, TaskConfig
from homehelper.llm.types import (
    LLMError,
    LLMUsage,
    Message,
    T,
    ToolCallRequest,
    ToolSpec,
    ToolTurn,
)
from homehelper.llm.usage import record_usage

log = get_logger(__name__)

# Errors are logged by us; LiteLLM's multi-line help banners would only add noise to JSON logs.
litellm.suppress_debug_info = True
logging.getLogger("LiteLLM").setLevel(logging.WARNING)

CompletionFn = Callable[..., Awaitable[Any]]
UsageSink = Callable[[LLMUsage], None]


OPENCODE_GO = "opencode_go"
# OpenCode Go serves each wire format under its own path (https://opencode.ai/docs/go/).
# Ids are `opencode_go/<wire>/<model>`, e.g. `opencode_go/openai/glm-5.3`.
OPENCODE_GO_PATHS = {"openai": "/openai/v1", "anthropic": "/anthropic"}
# Go asks clients to name themselves and send a stable `x-opencode-session`.
OPENCODE_GO_USER_AGENT = "homehelper-evals/1.0"


# Sent on the retry when a turn that must call a tool answered in text (`tool_choice` is "auto").
TOOL_CALL_NUDGE = "Respond by calling one of the provided tools, not with plain text."


def _schema_instruction(schema: type[BaseModel]) -> Message:
    return Message(
        role="user",
        content=(
            "Reply with only a JSON object, no prose and no code fences, that validates against "
            f"this JSON schema:\n{json.dumps(schema.model_json_schema())}"
        ),
    )


def _strip_fences(content: str) -> str:
    """JSON mode replies sometimes arrive wrapped in a Markdown code fence."""
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.removesuffix("```").strip()
    return text


def _response_format(config: TaskConfig, schema: type[BaseModel] | None) -> Any:
    if schema is None:
        return None
    if config.structured_output == "json_object":
        return {"type": "json_object"}
    return schema


def _tool_turn(message: Any) -> ToolTurn:
    """Parse a LiteLLM (OpenAI-format) assistant message; raises ValueError on bad arguments."""
    calls = []
    for call in getattr(message, "tool_calls", None) or []:
        try:
            arguments = json.loads(call.function.arguments or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError(f"{call.function.name}: arguments are not JSON") from exc
        if not isinstance(arguments, dict):
            raise ValueError(f"{call.function.name}: arguments are not a JSON object")
        calls.append(ToolCallRequest(id=call.id, name=call.function.name, arguments=arguments))
    return ToolTurn(tool_calls=calls, content=getattr(message, "content", None) or "")


def _trace_output(message: Any) -> Any:
    calls = getattr(message, "tool_calls", None)
    if not calls:
        return message.content or ""
    return {
        "content": message.content or "",
        "tool_calls": [{"name": c.function.name, "arguments": c.function.arguments} for c in calls],
    }


def provider_of(model: str) -> str:
    return model.split("/", 1)[0]


class LiteLLMClient:
    """Picks the model per task, walks the fallback chain on errors, validates structured output
    with Pydantic (one corrective retry), and reports tokens and cost to the trace and a sink."""

    def __init__(
        self,
        registry: ModelRegistry,
        api_keys: Mapping[str, str],
        *,
        opencode_go_base_url: str = "https://opencode.ai/inference/go",
        session_id: str | None = None,
        tracer: Tracer | None = None,
        usage_sink: UsageSink | None = None,
        completion_fn: CompletionFn | None = None,
        num_retries: int = 2,
    ) -> None:
        self._registry = registry
        self._api_keys = dict(api_keys)
        self._opencode_go_base_url = opencode_go_base_url.rstrip("/")
        # One session per client: an eval run shares a client across its conversations.
        self._session_id = session_id or uuid.uuid4().hex
        self._tracer = tracer
        self._usage_sink = usage_sink
        self._completion_fn: CompletionFn = completion_fn or litellm.acompletion
        self._num_retries = num_retries

    async def text(self, task: str, messages: list[Message]) -> str:
        message, _ = await self._complete(task, messages)
        return message.content or ""

    async def structured(self, task: str, messages: list[Message], schema: type[T]) -> T:
        if self._registry.for_task(task).structured_output == "json_object":
            messages = [*messages, _schema_instruction(schema)]
        message, model = await self._complete(task, messages, response_format=schema)
        content = message.content or ""
        try:
            return schema.model_validate_json(_strip_fences(content))
        except ValidationError as exc:
            log.warning("llm_structured_invalid", task=task, model=model, errors=exc.error_count())
            retry_messages = [
                *messages,
                Message(role="assistant", content=content),
                Message(
                    role="user",
                    content=(
                        "Your previous reply did not match the required JSON schema. "
                        f"Validation errors:\n{exc}\nReply again with only valid JSON."
                    ),
                ),
            ]
        message, model = await self._complete(task, retry_messages, response_format=schema)
        content = message.content or ""
        try:
            return schema.model_validate_json(_strip_fences(content))
        except ValidationError as exc:
            raise LLMError(f"{task}: structured output invalid after retry ({model})") from exc

    async def tool_turn(
        self,
        task: str,
        messages: list[Message],
        tools: list[ToolSpec],
        *,
        require_tool: bool = True,
    ) -> ToolTurn:
        request = {
            "tools": [{"type": "function", "function": spec.model_dump()} for spec in tools],
            # Not "required" even when a call is required: thinking modes (DeepSeek's, Anthropic's
            # extended thinking) reject a forced tool choice. The requirement is checked below.
            "tool_choice": "auto",
            # With `tools`, LiteLLM imports its MCP proxy bridge, which needs mcp>=2 (we pin <2,
            # ADR-006) and which we do not use: the agent calls MCP itself (ADR-008).
            "_skip_mcp_handler": True,
        }
        model = ""
        for _ in range(2):  # one retry, as for structured output
            message, model = await self._complete(task, messages, **request)
            try:
                turn = _tool_turn(message)
            except ValueError as exc:
                log.warning("llm_tool_arguments_invalid", task=task, model=model, error=str(exc))
                continue
            if require_tool and not turn.tool_calls:
                log.warning("llm_tool_call_missing", task=task, model=model)
                messages = [*messages, Message(role="user", content=TOOL_CALL_NUDGE)]
                continue
            return turn
        raise LLMError(f"{task}: tool call invalid after retry ({model})")

    def _chain(self, config: TaskConfig) -> list[str]:
        models = [config.model, *config.fallbacks]
        available = [m for m in models if provider_of(m) in self._api_keys]
        if not available:
            raise LLMError(f"no API key configured for any model in chain: {models}")
        return available

    def _route(self, model: str) -> tuple[str, dict[str, Any]]:
        """LiteLLM model id and connection kwargs for a registry model id."""
        provider, _, rest = model.partition("/")
        kwargs: dict[str, Any] = {"api_key": self._api_keys[provider]}
        if provider != OPENCODE_GO:
            return model, kwargs
        path = OPENCODE_GO_PATHS.get(provider_of(rest))
        if path is None or "/" not in rest:
            supported = ", ".join(f"{OPENCODE_GO}/{wire}/<model>" for wire in OPENCODE_GO_PATHS)
            raise LLMError(f"unsupported OpenCode Go model id {model!r}; use {supported}")
        kwargs["api_base"] = self._opencode_go_base_url + path
        kwargs["extra_headers"] = {
            "User-Agent": OPENCODE_GO_USER_AGENT,
            "x-opencode-session": self._session_id,
        }
        return rest, kwargs

    async def _complete(
        self,
        task: str,
        messages: list[Message],
        response_format: type[T] | None = None,
        **request: Any,
    ) -> tuple[Any, str]:
        """The first successful reply message in the task's chain, and the model that wrote it."""
        config = self._registry.for_task(task)
        payload = [m.to_payload() for m in messages]
        errors: list[str] = []
        for model in self._chain(config):
            litellm_model, connection = self._route(model)
            if config.reasoning_effort is not None:
                connection["reasoning_effort"] = config.reasoning_effort
            if "tools" in request and provider_of(model) == "openai":
                # gpt-5.4+ with tools and reasoning is sent through LiteLLM's Responses bridge,
                # which imports the MCP gateway (mcp>=2) before honouring `_skip_mcp_handler`.
                # Only an explicit "none" keeps the call on chat completions.
                connection["reasoning_effort"] = "none"
            started = time.perf_counter()
            with self._generation(task, model, payload) as generation:
                try:
                    response = await self._completion_fn(
                        model=litellm_model,
                        messages=payload,
                        response_format=_response_format(config, response_format),
                        timeout=config.timeout_s,
                        max_tokens=config.max_tokens,
                        num_retries=self._num_retries,
                        **request,
                        **connection,
                    )
                    message = response.choices[0].message
                except Exception as exc:
                    errors.append(f"{model}: {type(exc).__name__}")
                    log.warning("llm_call_failed", task=task, model=model, error=repr(exc))
                    if generation is not None:
                        generation.update(level="ERROR", status_message=type(exc).__name__)
                    continue

                usage = self._usage(task, model, response, (time.perf_counter() - started) * 1000)
                if generation is not None:
                    generation.update(
                        output=_trace_output(message),
                        usage_details={"input": usage.input_tokens, "output": usage.output_tokens},
                        cost_details={"total": usage.cost_usd},
                    )
            record_usage(usage)
            if self._usage_sink:
                self._usage_sink(usage)
            return message, model
        raise LLMError(f"{task}: all models failed: {'; '.join(errors)}")

    def _generation(self, task: str, model: str, payload: list[dict[str, Any]]) -> Any:
        if self._tracer is None:
            return nullcontext(None)
        return self._tracer.generation(task, model=model, input=payload)

    @staticmethod
    def _usage(task: str, model: str, response: Any, latency_ms: float) -> LLMUsage:
        tokens = getattr(response, "usage", None)
        try:
            # A provider-reported cost first: LiteLLM has no OpenRouter prices, and
            # `completion_cost` ignores the cost OpenRouter returns.
            reported = get_response_cost_from_hidden_params(getattr(response, "_hidden_params", {}))
            cost = float(
                reported
                if reported is not None
                else litellm.completion_cost(completion_response=response, model=model)
            )
        except Exception:
            cost = 0.0  # unknown pricing must never fail the call
        return LLMUsage(
            task=task,
            model=model,
            input_tokens=getattr(tokens, "prompt_tokens", 0) or 0,
            output_tokens=getattr(tokens, "completion_tokens", 0) or 0,
            cost_usd=cost,
            latency_ms=round(latency_ms, 1),
        )
