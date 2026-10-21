import pytest

from homehelper.core.logging import redact_pii
from homehelper.core.tracing import Tracer, coerce_trace_id
from tests.conftest import make_settings


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("contact jane.doe+x@example.co.uk now", "contact [email] now"),
        ("call +1 (415) 555-0100 today", "call [phone] today"),
        ("model WM3400CW error OE", "model WM3400CW error OE"),
    ],
)
def test_redact_pii(text: str, expected: str) -> None:
    assert redact_pii(text) == expected


def test_coerce_trace_id() -> None:
    valid = "a" * 32
    assert coerce_trace_id(valid) == valid
    for bad in (None, "", "A" * 32, "a" * 31, "not-a-trace-id"):
        coerced = coerce_trace_id(bad)
        assert coerced != bad
        assert len(coerced) == 32


def test_tracer_is_noop_without_keys() -> None:
    tracer = Tracer(make_settings())
    assert not tracer.enabled
    with tracer.trace("noop", "b" * 32) as span:
        assert span is None
    tracer.flush()
    tracer.shutdown()
