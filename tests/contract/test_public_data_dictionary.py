"""Contract checks for the observed-schema data dictionary."""

from pathlib import Path

ROOT = Path(__file__).parents[2]
DICTIONARY = ROOT / "docs" / "data_dictionary.md"
ARCHITECTURE = ROOT / "docs" / "architecture.md"


def test_dictionary_covers_six_observed_components_and_pit_rules() -> None:
    """The public dictionary must expose all six requested components."""
    text = DICTIONARY.read_text(encoding="utf-8")
    for component in (
        "Underlying 1-minute OHLCV",
        "Structured earnings",
        "Unusual option events",
        "Ordinary option state",
        "Contract trades",
        "Consolidated contract quotes",
    ):
        assert component in text
    assert "available_at_utc" in text
    assert "exactly thirty future closes" in text
    assert "silent forward-fill are forbidden" in text


def test_architecture_keeps_colab_as_orchestration_only() -> None:
    """Colab must call the local package rather than duplicate production logic."""
    text = ARCHITECTURE.read_text(encoding="utf-8")
    assert "Colab is orchestration and\npresentation only" in text
    assert "authorized_for_backfill=false" in text
    assert "Delta_Q = QLIKE(B1) - QLIKE(B2)" in text
