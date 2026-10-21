"""Pure ASGI middleware (not BaseHTTPMiddleware) so SSE responses stream without buffering."""

import time

import structlog
from starlette.routing import Match, Router
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from homehelper.core.logging import get_logger
from homehelper.core.tracing import Tracer, coerce_trace_id

TRACE_HEADER = b"x-request-id"
UNTRACED_PATHS = frozenset({"/healthz", "/readyz"})
UNMATCHED_ROUTE = "unmatched-route"

log = get_logger(__name__)


def route_template(router: Router, scope: Scope) -> str:
    """The matched route's path template (`/v1/conversations/{id}`), for low-cardinality names."""
    partial: str | None = None
    for route in router.routes:
        match, _ = route.matches(scope)
        if match == Match.FULL:
            return getattr(route, "path", UNMATCHED_ROUTE)
        if match == Match.PARTIAL and partial is None:
            partial = getattr(route, "path", None)  # path matched, method did not (405)
    return partial or UNMATCHED_ROUTE


class TraceMiddleware:
    """Assigns a trace id per request, binds it to logs, echoes it in `X-Request-ID`, and opens a
    Langfuse trace for non-health requests."""

    def __init__(self, app: ASGIApp, tracer: Tracer, router: Router) -> None:
        self.app = app
        self.tracer = tracer
        self.router = router

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = dict(scope["headers"]).get(TRACE_HEADER, b"").decode("latin-1")
        trace_id = coerce_trace_id(incoming)
        path: str = scope["path"]
        method: str = scope["method"]
        route = route_template(self.router, scope)
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
                # Request bodies are not captured here; turn handlers set the user message and
                # reply as the root observation's input/output.
                with self.tracer.trace(
                    f"{method} {route}", trace_id, input={"method": method, "route": route}
                ) as span:
                    try:
                        await self.app(scope, receive, send_with_trace_id)
                    except Exception as exc:
                        if span is not None:
                            span.update(level="ERROR", status_message=type(exc).__name__)
                        raise
                    if span is not None:
                        span.update(
                            output={"status_code": status_code},
                            level="ERROR" if status_code >= 500 else None,
                        )
        finally:
            log.info(
                "request",
                method=method,
                path=path,
                route=route,
                status_code=status_code,
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
            )
