import json
from typing import Any

import pytest
from fastapi import FastAPI
from langfuse.types import MaskOtelSpansParams, OtelSpanData, OtelSpanIdentifier

from homehelper.core.middleware import UNMATCHED_ROUTE, route_template
from homehelper.core.tracing import mask_pii_spans


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
def router() -> Any:
    app = FastAPI()

    @app.get("/v1/conversations/{conversation_id}")
    async def get_conversation(conversation_id: str) -> None: ...

    return app.router


def _scope(method: str, path: str) -> dict[str, Any]:
    return {"type": "http", "method": method, "path": path, "root_path": "", "headers": []}


@pytest.mark.parametrize(
    ("method", "path", "expected"),
    [
        ("GET", "/v1/conversations/abc123", "/v1/conversations/{conversation_id}"),
        ("POST", "/v1/conversations/abc123", "/v1/conversations/{conversation_id}"),
        ("GET", "/nope", UNMATCHED_ROUTE),
    ],
)
def test_route_template_is_low_cardinality(
    router: Any, method: str, path: str, expected: str
) -> None:
    assert route_template(router, _scope(method, path)) == expected
