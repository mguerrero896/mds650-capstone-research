"""TDD contract tests for fail-closed settings."""

from __future__ import annotations

import pytest

from mds650.config import ResearchSettings
from mds650.errors import ResearchOnlyViolation, SecretPresenceError


def test_provider_secret_presence_never_returns_secret_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Presence reporting exposes booleans only, never credential material."""
    monkeypatch.setenv("UNUSUALWHALES_API_KEY", "uw-test-secret")
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    monkeypatch.setenv("MASSIVE_API_KEY", "massive-test-secret")
    monkeypatch.setenv("FMP_API_KEY", "fmp-test-secret")

    settings = ResearchSettings()

    assert settings.secret_presence() == {
        "UNUSUALWHALES_API_KEY": True,
        "MASSIVE_API_KEY": True,
        "FMP_API_KEY": True,
    }
    assert "secret" not in repr(settings.secret_presence()).lower()


def test_missing_provider_secret_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing provider key blocks requests with a stable error code."""
    monkeypatch.delenv("UNUSUALWHALES_API_KEY", raising=False)
    monkeypatch.setenv("MASSIVE_API_KEY", "massive-test-secret")
    monkeypatch.setenv("FMP_API_KEY", "fmp-test-secret")

    settings = ResearchSettings()

    with pytest.raises(SecretPresenceError, match="UNUSUALWHALES_API_KEY"):
        settings.require_provider_secrets()


def test_live_mutation_mode_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Research-only mode cannot be disabled by an accidental default change."""
    monkeypatch.setenv("MDS650_RESEARCH_ONLY", "false")

    with pytest.raises(ResearchOnlyViolation, match="RESEARCH_ONLY_REQUIRED"):
        ResearchSettings()
