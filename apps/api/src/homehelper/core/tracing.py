"""Langfuse tracing. A no-op when Langfuse keys are not set, so tests and CI need no account."""

import json
import re
import uuid
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from typing import Any

from langfuse import Langfuse, propagate_attributes
from langfuse.types import (
    MaskOtelSpansParams,
    MaskOtelSpansResult,
    OtelSpanIdentifier,
    OtelSpanPatch,
)
from opentelemetry import trace as otel_trace
from opentelemetry.sdk.trace.export import SpanExporter

from homehelper.core.config import Settings
from homehelper.core.logging import get_logger, redact_pii

# Langfuse (OpenTelemetry) trace ids are 32 lowercase hex chars.
_TRACE_ID = re.compile(r"^[0-9a-f]{32}$")

log = get_logger(__name__)


def new_trace_id() -> str:
    return uuid.uuid4().hex


def coerce_trace_id(candidate: str | None) -> str:
    """Reuse an incoming id only if it is a valid trace id; never trust arbitrary header text."""
    if candidate and _TRACE_ID.fullmatch(candidate):
        return candidate
    return new_trace_id()


def _redact_json_strings(value: Any) -> Any:
    if isinstance(value, str):
        return redact_pii(value)
    if isinstance(value, list):
        return [_redact_json_strings(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact_json_strings(item) for key, item in value.items()}
    return value


def _redact_attribute(value: str) -> str:
    # Langfuse v5 stores input/output/metadata as JSON-encoded strings. Redact inside the decoded
    # structure so the result stays valid JSON; fall back to plain-text redaction otherwise.
    try:
        decoded = json.loads(value)
    except ValueError:
        return redact_pii(value)
    if isinstance(decoded, dict | list | str):
        return json.dumps(_redact_json_strings(decoded), ensure_ascii=False)
    return value


def mask_pii_spans(*, params: MaskOtelSpansParams) -> MaskOtelSpansResult:
    """Redact emails and phone numbers from span attributes before export (spec §18.1).

    Must never raise: Langfuse drops the whole export batch if this hook fails.
    """
    patches: dict[OtelSpanIdentifier, OtelSpanPatch | None] = {}
    try:
        for identifier, span in params.spans.items():
            updates: dict[str, str] = {}
            for key, value in span.attributes.items():
                if isinstance(value, str):
                    redacted = _redact_attribute(value)
                    if redacted != value:
                        updates[key] = redacted
            if updates:
                patches[identifier] = OtelSpanPatch(set_attributes=updates)
    except Exception as exc:
        log.warning("trace_masking_failed", error=repr(exc))
    return MaskOtelSpansResult(span_patches=patches)


class Tracer:
    def __init__(self, settings: Settings, *, span_exporter: SpanExporter | None = None) -> None:
        """`span_exporter` overrides the Langfuse OTLP exporter (tests use an in-memory one)."""
        self._client: Langfuse | None = None
        self._release = settings.release_id
        if settings.tracing_enabled:
            self._client = Langfuse(
                public_key=settings.langfuse_public_key,
                secret_key=settings.langfuse_secret_key.get_secret_value(),
                base_url=settings.langfuse_base_url,
                environment=settings.app_env,
                release=settings.release_id,
                mask_otel_spans=mask_pii_spans,
                span_exporter=span_exporter,
            )

    @property
    def enabled(self) -> bool:
        return self._client is not None

    @contextmanager
    def trace(
        self,
        name: str,
        trace_id: str,
        *,
        session_id: str | None = None,
        user_id: str | None = None,
        tags: list[str] | None = None,
        input: Any = None,
    ) -> Iterator[Any]:
        """Open the root span of a trace. Yields the Langfuse span, or None when disabled.

        `name` becomes the trace name, so it must be low-cardinality (a route template or a
        journey name, never a raw path with ids). Use `rename` when it is only known later.
        """
        if self._client is None:
            with nullcontext(None) as span:
                yield span
            return
        with (
            self._client.start_as_current_observation(
                name=name, trace_context={"trace_id": trace_id}, input=input
            ) as span,
            propagate_attributes(
                trace_name=name,
                session_id=session_id,
                user_id=user_id,
                tags=[f"release:{self._release}", *(tags or [])],
            ),
        ):
            yield span

    @contextmanager
    def generation(self, name: str, *, model: str, input: Any = None) -> Iterator[Any]:
        """A child LLM-call observation under the current span. Yields None when disabled."""
        if self._client is None:
            with nullcontext(None) as span:
                yield span
            return
        with self._client.start_as_current_observation(
            name=name, as_type="generation", model=model, input=input
        ) as span:
            yield span

    @contextmanager
    def span(self, name: str, *, input: Any = None, tags: list[str] | None = None) -> Iterator[Any]:
        """A child span under the current one. `tags` are added to the trace from here on.
        Yields None when disabled."""
        if self._client is None:
            with nullcontext(None) as span:
                yield span
            return
        tagged = propagate_attributes(tags=tags) if tags else nullcontext()
        with tagged, self._client.start_as_current_observation(name=name, input=input) as span:
            yield span

    @contextmanager
    def turn(
        self,
        name: str,
        *,
        session_id: str,
        user_id: str | None = None,
        tags: list[str] | None = None,
        input: Any = None,
    ) -> Iterator[Any]:
        """One agent turn: a child span of the request's trace when there is one (the API),
        otherwise a trace of its own (evals, scripts). Yields None when disabled."""
        if self._client is None:
            with nullcontext(None) as span:
                yield span
            return
        if otel_trace.get_current_span().get_span_context().is_valid:
            with (
                propagate_attributes(session_id=session_id, user_id=user_id, tags=tags),
                self._client.start_as_current_observation(name=name, input=input) as span,
            ):
                yield span
            return
        with self.trace(
            name, new_trace_id(), session_id=session_id, user_id=user_id, tags=tags, input=input
        ) as span:
            yield span

    @staticmethod
    def rename(span: Any, name: str) -> None:
        """Rename the root span and its trace. Call while `span` is still the current span."""
        if span is None:
            return
        span.update(name=name)
        with propagate_attributes(trace_name=name):
            pass  # sets the trace name on the current (root) span

    def flush(self) -> None:
        if self._client is not None:
            self._client.flush()

    def shutdown(self) -> None:
        if self._client is not None:
            self._client.shutdown()
