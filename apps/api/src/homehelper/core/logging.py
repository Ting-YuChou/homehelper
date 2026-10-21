"""JSON logging via structlog. Every line carries the request's `trace_id` (bound in middleware)."""

import logging
import re
import sys
from typing import Any

import structlog
from structlog.typing import EventDict, WrappedLogger

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"(?<!\w)\+?\d[\d\s().-]{7,}\d(?!\w)")


def redact_pii(text: str) -> str:
    return _PHONE.sub("[phone]", _EMAIL.sub("[email]", text))


def _redact_pii(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
    for key, value in event_dict.items():
        if isinstance(value, str):
            event_dict[key] = redact_pii(value)
    return event_dict


def _add_severity(_: WrappedLogger, method_name: str, event_dict: EventDict) -> EventDict:
    # Cloud Logging reads `severity` from JSON payloads.
    event_dict["severity"] = method_name.upper()
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    numeric_level = logging.getLevelNamesMapping().get(level.upper(), logging.INFO)
    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        _add_severity,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        _redact_pii,
        structlog.processors.JSONRenderer(),
    ]
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.PrintLoggerFactory(sys.stdout),
        cache_logger_on_first_use=True,
    )
    # Route stdlib loggers (uvicorn, sqlalchemy, ...) through the same level.
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=numeric_level, force=True)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
