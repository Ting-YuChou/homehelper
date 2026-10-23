"""JSON logging via structlog. Every line carries the request's `trace_id` (bound in middleware)
and the release; stdlib loggers (uvicorn, sqlalchemy, ...) are rendered the same way, so Cloud
Logging reads `severity` from every line."""

import logging
import re
import sys
from typing import Any

import structlog
from structlog.typing import EventDict, WrappedLogger

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
# Phone-shaped digit groups (+1 (415) 555-0100, 0912-345-678); dates and short numbers don't match.
_PHONE = re.compile(
    r"(?<![\w-])(?:\+\d{1,3}[\s.-]?)?(?:\(\d{2,4}\)|\d{2,4})[\s.-]?\d{3,4}[\s.-]?\d{3,4}(?![\w-])"
)


def redact_pii(text: str) -> str:
    return _PHONE.sub("[phone]", _EMAIL.sub("[email]", text))


def _redact_pii(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
    for key, value in event_dict.items():
        if isinstance(value, str):
            event_dict[key] = redact_pii(value)
    return event_dict


# Cloud Logging's severity names, for the method names that differ from them.
_SEVERITY = {"exception": "ERROR", "warn": "WARNING", "msg": "INFO", "fatal": "CRITICAL"}
# uvicorn installs its own handlers (and stops propagation); ours replace them.
_UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


def _add_severity(_: WrappedLogger, method_name: str, event_dict: EventDict) -> EventDict:
    # Cloud Logging reads `severity` from JSON payloads.
    event_dict["severity"] = _SEVERITY.get(method_name, method_name.upper())
    return event_dict


def configure_logging(level: str = "INFO", *, release_id: str | None = None) -> None:
    numeric_level = logging.getLevelNamesMapping().get(level.upper(), logging.INFO)

    def add_release(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
        if release_id is not None:
            event_dict.setdefault("release", release_id)
        return event_dict

    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        _add_severity,
        add_release,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]
    tail: list[Any] = [
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        _redact_pii,
        structlog.processors.JSONRenderer(),
    ]
    structlog.configure(
        processors=[*shared, *tail],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.PrintLoggerFactory(sys.stdout),
        # Not cached: a logger keeps the configuration it was first used with, and this runs
        # again whenever an app or CLI starts (and in tests).
        cache_logger_on_first_use=False,
    )
    # Stdlib records: the message (with its %-args) becomes `event`, plus the logger name.
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=[*shared, structlog.stdlib.add_logger_name],
            processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, *tail],
        )
    )
    logging.basicConfig(handlers=[handler], level=numeric_level, force=True)
    for name in _UVICORN_LOGGERS:
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
