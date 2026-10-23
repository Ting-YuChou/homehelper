import json
import logging

import pytest

from homehelper.core.logging import configure_logging, get_logger, redact_pii
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


def _lines(capsys: pytest.CaptureFixture[str]) -> list[dict[str, object]]:
    return [json.loads(line) for line in capsys.readouterr().out.splitlines() if line]


def test_log_lines_carry_cloud_logging_severity_and_release(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("INFO", release_id="main-abc1234")
    log = get_logger("test")
    log.warning("careful")
    try:
        raise ValueError("boom")
    except ValueError:
        log.exception("failed")
    lines = _lines(capsys)
    assert [line["severity"] for line in lines] == ["WARNING", "ERROR"]  # not "EXCEPTION"
    assert all(line["release"] == "main-abc1234" for line in lines)


def test_stdlib_and_uvicorn_logs_are_json_too(capsys: pytest.CaptureFixture[str]) -> None:
    logging.getLogger("uvicorn.error").addHandler(logging.StreamHandler())  # as uvicorn does
    configure_logging("INFO", release_id="dev")
    logging.getLogger("uvicorn.error").error("worker crashed for %s", "a@b.example")
    [line] = _lines(capsys)
    assert line["severity"] == "ERROR"
    assert line["event"] == "worker crashed for [email]"
    assert line["logger"] == "uvicorn.error" and line["release"] == "dev"
