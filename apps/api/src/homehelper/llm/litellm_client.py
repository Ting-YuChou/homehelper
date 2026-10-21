"""LLMClient backed by the LiteLLM SDK (library mode, no proxy)."""

import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from contextlib import nullcontext
from typing import Any

import litellm
from pydantic import ValidationError

from homehelper.core.logging import get_logger
from homehelper.core.tracing import Tracer
from homehelper.llm.registry import ModelRegistry, TaskConfig
from homehelper.llm.types import LLMError, LLMUsage, Message, T

log = get_logger(__name__)

# Errors are logged by us; LiteLLM's multi-line help banners would only add noise to JSON logs.
litellm.suppress_debug_info = True
logging.getLogger("LiteLLM").setLevel(logging.WARNING)

CompletionFn = Callable[..., Awaitable[Any]]
UsageSink = Callable[[LLMUsage], None]


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
        tracer: Tracer | None = None,
        usage_sink: UsageSink | None = None,
        completion_fn: CompletionFn | None = None,
        num_retries: int = 2,
    ) -> None:
        self._registry = registry
        self._api_keys = dict(api_keys)
        self._tracer = tracer
        self._usage_sink = usage_sink
        self._completion_fn: CompletionFn = completion_fn or litellm.acompletion
        self._num_retries = num_retries

    async def text(self, task: str, messages: list[Message]) -> str:
        content, _ = await self._complete(task, messages, response_format=None)
        return content

    async def structured(self, task: str, messages: list[Message], schema: type[T]) -> T:
        content, model = await self._complete(task, messages, response_format=schema)
        try:
            return schema.model_validate_json(content)
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
        content, model = await self._complete(task, retry_messages, response_format=schema)
        try:
            return schema.model_validate_json(content)
        except ValidationError as exc:
            raise LLMError(f"{task}: structured output invalid after retry ({model})") from exc

    def _chain(self, config: TaskConfig) -> list[str]:
        models = [config.model, *config.fallbacks]
        available = [m for m in models if provider_of(m) in self._api_keys]
        if not available:
            raise LLMError(f"no API key configured for any model in chain: {models}")
        return available

    async def _complete(
        self, task: str, messages: list[Message], response_format: type[T] | None
    ) -> tuple[str, str]:
        config = self._registry.for_task(task)
        payload = [m.model_dump() for m in messages]
        errors: list[str] = []
        for model in self._chain(config):
            started = time.perf_counter()
            with self._generation(task, model, payload) as generation:
                try:
                    response = await self._completion_fn(
                        model=model,
                        messages=payload,
                        response_format=response_format,
                        timeout=config.timeout_s,
                        max_tokens=config.max_tokens,
                        num_retries=self._num_retries,
                        api_key=self._api_keys[provider_of(model)],
                    )
                    content = response.choices[0].message.content or ""
                except Exception as exc:
                    errors.append(f"{model}: {type(exc).__name__}")
                    log.warning("llm_call_failed", task=task, model=model, error=repr(exc))
                    if generation is not None:
                        generation.update(level="ERROR", status_message=type(exc).__name__)
                    continue

                usage = self._usage(task, model, response, (time.perf_counter() - started) * 1000)
                if generation is not None:
                    generation.update(
                        output=content,
                        usage_details={"input": usage.input_tokens, "output": usage.output_tokens},
                        cost_details={"total": usage.cost_usd},
                    )
            if self._usage_sink:
                self._usage_sink(usage)
            return content, model
        raise LLMError(f"{task}: all models failed: {'; '.join(errors)}")

    def _generation(self, task: str, model: str, payload: list[dict[str, Any]]) -> Any:
        if self._tracer is None:
            return nullcontext(None)
        return self._tracer.generation(task, model=model, input=payload)

    @staticmethod
    def _usage(task: str, model: str, response: Any, latency_ms: float) -> LLMUsage:
        tokens = getattr(response, "usage", None)
        try:
            cost = float(litellm.completion_cost(completion_response=response, model=model))
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
