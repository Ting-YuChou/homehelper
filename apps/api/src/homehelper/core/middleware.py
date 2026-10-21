"""Pure ASGI middleware (not BaseHTTPMiddleware) so SSE responses stream without buffering."""

import time

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from homehelper.core.logging import get_logger
from homehelper.core.tracing import Tracer, coerce_trace_id

TRACE_HEADER = b"x-request-id"
UNTRACED_PATHS = frozenset({"/healthz", "/readyz"})
PENDING_ROUTE = "http-request"
UNMATCHED_ROUTE = "unmatched-route"

log = get_logger(__name__)


def route_template(scope: Scope) -> str:
    """The matched route's path template (`/v1/conversations/{id}`), for low-cardinality names.

    The router stores the matched route in the shared scope, so this is only meaningful after the
    app has handled the request. Unmatched paths (404) have no route.
    """
    return getattr(scope.get("route"), "path", None) or UNMATCHED_ROUTE


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
                # The route is only known after routing, so the trace is renamed at the end.
                # Request bodies are not captured here; turn handlers set the user message and
                # reply as the root observation's input/output.
                with self.tracer.trace(f"{method} {PENDING_ROUTE}", trace_id) as span:
                    error: Exception | None = None
                    try:
                        await self.app(scope, receive, send_with_trace_id)
                    except Exception as exc:
                        error = exc
                        raise
                    finally:
                        if span is not None:
                            route = route_template(scope)
                            self.tracer.rename(span, f"{method} {route}")
                            span.update(
                                input={"method": method, "route": route},
                                output={"status_code": status_code},
                                level="ERROR" if error or status_code >= 500 else None,
                                status_message=type(error).__name__ if error else None,
                            )
        finally:
            log.info(
                "request",
                method=method,
                path=path,
                route=route_template(scope),
                status_code=status_code,
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
            )
