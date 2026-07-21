"""Structured standard-library logging with conservative secret redaction."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from typing import Any

_SECRET_KEY = re.compile(r"(api[_-]?key|token|authorization|password|secret)", re.I)
_SECRET_TEXT = re.compile(
    r"((?:api[_-]?key|token|authorization|password|secret)\s*[:=]\s*)([^\s,;]+)",
    re.I,
)


def redact_mapping(values: Mapping[str, object]) -> dict[str, object]:
    """Return a shallow mapping copy with secret-like fields redacted.

    Parameters
    ----------
    values:
        Mapping of structured log fields. The input is never mutated.

    Returns
    -------
    dict[str, object]
        Copy with values for secret-like keys replaced by ``"[REDACTED]"``.

    Examples
    --------
    ``redact_mapping({"api_key": "x"}) == {"api_key": "[REDACTED]"}``.
    """
    return {
        key: "[REDACTED]" if _SECRET_KEY.search(key) else value
        for key, value in values.items()
    }


class _JsonFormatter(logging.Formatter):
    """Serialize log records as compact JSON without arbitrary extras."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": _SECRET_TEXT.sub(r"\1[REDACTED]", record.getMessage()),
        }
        event = getattr(record, "event", None)
        fields = getattr(record, "fields", None)
        if event is not None:
            payload["event"] = event
        if isinstance(fields, Mapping):
            payload["fields"] = redact_mapping(fields)
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)


class _SecretRedactionFilter(logging.Filter):
    """Prevent formatter input from carrying a clear-text secret token."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _SECRET_TEXT.sub(r"\1[REDACTED]", record.getMessage())
        record.args = ()
        return True


def configure_logging(level: str = "INFO") -> logging.Logger:
    """Configure and return the package logger.

    Parameters
    ----------
    level:
        Standard logging level name. Invalid names raise ``ValueError``.

    Returns
    -------
    logging.Logger
        The configured ``mds650`` logger with one redacting stream handler.

    Raises
    ------
    ValueError
        If ``level`` is not a valid logging level name.
    """
    numeric_level = logging.getLevelNamesMapping().get(level.upper())
    if not isinstance(numeric_level, int):
        raise ValueError("LOG_LEVEL_INVALID")
    logger = logging.getLogger("mds650")
    logger.setLevel(numeric_level)
    logger.propagate = False
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(_JsonFormatter())
        handler.addFilter(_SecretRedactionFilter())
        logger.addHandler(handler)
    return logger
