import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from langfuse import LangfuseOtelSpanAttributes
from langfuse.types import MaskOtelSpansParams, OtelSpanData, OtelSpanIdentifier
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from homehelper.core.middleware import UNMATCHED_ROUTE
from homehelper.core.tracing import Tracer, mask_pii_spans
from homehelper.main import create_app
from tests.conftest import make_settings


def _span(attributes: dict[str, Any]) -> tuple[OtelSpanIdentifier, OtelSpanData]:
    trace_id, span_id = "a" * 32, "b" * 16
    identifier = OtelSpanIdentifier(trace_id=trace_id, span_id=span_id)
    data = OtelSpanData(
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=None,
        name="GET /v1/meta",
        instrumentation_scope_name="langfuse",
        instrumentation_scope_version=None,
        attributes=attributes,
        resource_attributes={},
    )
    return identifier, data


def test_mask_redacts_plain_and_json_attributes_keeping_json_valid() -> None:
    identifier, data = _span(
        {
            "langfuse.observation.input": json.dumps(
                {"message": "email me at a@b.com or call +1 (415) 555-0100", "count": 12345678901}
            ),
            "plain": "reach a@b.com",
            "untouched": "model WM3400CW, 2026-10-21",
            "number": 42,
        }
    )
    result = mask_pii_spans(params=MaskOtelSpansParams(spans={identifier: data}))

    patch = result.span_patches[identifier]
    assert patch is not None
    updates = dict(patch.set_attributes)
    assert set(updates) == {"langfuse.observation.input", "plain"}
    masked_input = updates["langfuse.observation.input"]
    assert isinstance(masked_input, str)
    assert json.loads(masked_input) == {
        "message": "email me at [email] or call [phone]",
        "count": 12345678901,
    }
    assert updates["plain"] == "reach [email]"


def test_mask_returns_no_patch_when_nothing_changes() -> None:
    identifier, data = _span({"route": "/v1/meta", "date": "2026-10-21"})
    result = mask_pii_spans(params=MaskOtelSpansParams(spans={identifier: data}))
    assert dict(result.span_patches) == {}


def test_mask_never_raises() -> None:
    class Broken:
        def items(self) -> Any:
            raise RuntimeError("boom")

    result = mask_pii_spans(params=MaskOtelSpansParams(spans=Broken()))  # type: ignore[arg-type]
    assert dict(result.span_patches) == {}


@pytest.fixture
async def traced() -> AsyncIterator[tuple[httpx.AsyncClient, InMemorySpanExporter, Tracer]]:
    # Langfuse shares one tracer provider per public key, so each test gets a unique key.
    settings = make_settings(
        langfuse_public_key=f"pk-lf-test-{uuid.uuid4().hex}", langfuse_secret_key="sk-lf-test"
    )
    exporter = InMemorySpanExporter()
    tracer = Tracer(settings, span_exporter=exporter)
    app = create_app(settings, tracer=tracer)

    @app.get("/v1/things/{thing_id}")
    async def get_thing(thing_id: str) -> dict[str, str]:
        return {"id": thing_id}

    @app.get("/v1/boom")
    async def boom() -> None:
        raise RuntimeError("boom")

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, exporter, tracer
    tracer.shutdown()


async def _root_span(
    traced: tuple[httpx.AsyncClient, InMemorySpanExporter, Tracer], method: str, path: str
) -> dict[str, Any]:
    client, exporter, tracer = traced
    await client.request(method, path)
    tracer.flush()
    roots = [span for span in exporter.get_finished_spans() if span.name.startswith(method)]
    assert len(roots) == 1
    return {"name": roots[0].name, **dict(roots[0].attributes or {})}


@pytest.mark.parametrize(
    ("method", "path", "expected"),
    [
        ("GET", "/v1/meta", "GET /v1/meta"),  # route registered via include_router
        ("GET", "/v1/things/abc123", "GET /v1/things/{thing_id}"),
        ("GET", "/nope", f"GET {UNMATCHED_ROUTE}"),
        ("POST", "/v1/meta", "POST /v1/meta"),  # 405 keeps the template
    ],
)
async def test_trace_named_by_route_template(
    traced: tuple[httpx.AsyncClient, InMemorySpanExporter, Tracer],
    method: str,
    path: str,
    expected: str,
) -> None:
    span = await _root_span(traced, method, path)
    assert span["name"] == expected
    assert span[LangfuseOtelSpanAttributes.TRACE_NAME] == expected


async def test_trace_marks_errors(
    traced: tuple[httpx.AsyncClient, InMemorySpanExporter, Tracer],
) -> None:
    span = await _root_span(traced, "GET", "/v1/boom")
    assert span[LangfuseOtelSpanAttributes.OBSERVATION_LEVEL] == "ERROR"
    assert span[LangfuseOtelSpanAttributes.OBSERVATION_STATUS_MESSAGE] == "RuntimeError"


async def test_health_checks_are_not_traced(
    traced: tuple[httpx.AsyncClient, InMemorySpanExporter, Tracer],
) -> None:
    client, exporter, tracer = traced
    await client.get("/healthz")
    tracer.flush()
    assert exporter.get_finished_spans() == ()
