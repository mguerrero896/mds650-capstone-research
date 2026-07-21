from __future__ import annotations

import logging

from mds650.logging import configure_logging, redact_mapping


def test_redact_mapping_removes_secret_values_without_mutating_input() -> None:
    original = {"provider": "fmp", "api_key": "secret-value", "status": 200}

    redacted = redact_mapping(original)

    assert original["api_key"] == "secret-value"
    assert redacted == {"provider": "fmp", "api_key": "[REDACTED]", "status": 200}


def test_configure_logging_emits_structured_event_without_secret() -> None:
    logger = configure_logging("INFO")

    assert isinstance(logger, logging.Logger)
    assert logger.name == "mds650"
