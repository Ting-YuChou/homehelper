"""Pure ASGI middleware (not BaseHTTPMiddleware) so SSE responses stream without buffering."""

import time

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from homehelper.core.logging import get_logger
from homehelper.core.tracing import Tracer, coerce_trace_id

TRACE_HEADER = b"x-request-id"
UNTRACED_PATHS = frozenset({"/healthz", "/readyz"})

log = get_logger(__name__)


class TraceMiddleware:
    """Assigns a trace id per request, binds it to logs, echoes it in `X-Request-ID`, and opens a
    Langfuse trace for non-health requests."""

    def __init__(self, app: ASGIApp, tracer: Tracer) -> None:
        self.app = app
        self.tracer = tracer

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = dict(scope["headers"]).get(TRACE_HEADER, b"").decode("latin-1")
        trace_id = coerce_trace_id(incoming)
        path: str = scope["path"]
        method: str = scope["method"]
        status_code = 500

        async def send_with_trace_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                message.setdefault("headers", [])
                message["headers"].append((TRACE_HEADER, trace_id.encode()))
            await send(message)

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(trace_id=trace_id)
        started = time.perf_counter()
        try:
            if path in UNTRACED_PATHS:
                await self.app(scope, receive, send_with_trace_id)
            else:
                with self.tracer.trace(f"{method} {path}", trace_id, tags=["channel:web"]) as span:
                    await self.app(scope, receive, send_with_trace_id)
                    if span is not None:
                        span.update(output={"status_code": status_code})
        finally:
            log.info(
                "request",
                method=method,
                path=path,
                status_code=status_code,
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
            )
