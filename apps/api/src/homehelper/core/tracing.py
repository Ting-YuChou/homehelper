"""Langfuse tracing. A no-op when Langfuse keys are not set, so tests and CI need no account."""

import re
import uuid
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from typing import Any

from langfuse import Langfuse, propagate_attributes

from homehelper.core.config import Settings

# Langfuse (OpenTelemetry) trace ids are 32 lowercase hex chars.
_TRACE_ID = re.compile(r"^[0-9a-f]{32}$")


def new_trace_id() -> str:
    return uuid.uuid4().hex


def coerce_trace_id(candidate: str | None) -> str:
    """Reuse an incoming id only if it is a valid trace id; never trust arbitrary header text."""
    if candidate and _TRACE_ID.fullmatch(candidate):
        return candidate
    return new_trace_id()


class Tracer:
    def __init__(self, settings: Settings) -> None:
        self._client: Langfuse | None = None
        self._environment = settings.app_env
        self._release = settings.release_id
        if settings.tracing_enabled:
            self._client = Langfuse(
                public_key=settings.langfuse_public_key,
                secret_key=settings.langfuse_secret_key.get_secret_value(),
                host=settings.langfuse_host,
                environment=settings.app_env,
                release=settings.release_id,
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
        """Open the root span of a trace. Yields the Langfuse span, or None when disabled."""
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

    def flush(self) -> None:
        if self._client is not None:
            self._client.flush()

    def shutdown(self) -> None:
        if self._client is not None:
            self._client.shutdown()
