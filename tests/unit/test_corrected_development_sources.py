"""TDD coverage for exact, target-free corrected-development sources."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest
from jsonschema import Draft202012Validator

from mds650.corrected_development_sources import (
    B1Q_EXOGENOUS_INPUT_PROVENANCE_UNRESOLVED,
    build_exact_development_origins,
    build_source_coverage_ledger,
    prepare_b1q_source,
    validate_source_coverage_ledger,
)
from mds650.study_design import canonical_sha256

ROOT = Path(__file__).resolve().parents[2]


def _source_hashes() -> dict[str, str]:
    """Return deterministic placeholder digests for target-free source identities."""
    return {
        "b1q_source": "a" * 64,
        "b2_full_tape_manifest": "b" * 64,
        "fmp_source": "c" * 64,
        "study_manifest": "d" * 64,
    }


def _b1_source_row(
    origin: dict[str, object],
    *,
    rate_source_date: str,
    include_exogenous_evidence: bool = True,
) -> dict[str, object]:
    """Return one minimal, target-free B1Q source state for a synthetic origin."""
    origin_timestamp = origin["forecast_origin_utc"]
    assert isinstance(origin_timestamp, datetime)
    row: dict[str, object] = {
        "origin_id": origin["origin_id"],
        "asset": origin["asset"],
        "session_date": origin["session_date"],
        "forecast_origin_utc": origin_timestamp,
        "rate": 0.04,
        "rate_source_date": rate_source_date,
        "dividend_yield": 0.0,
        "dividend_assumption": "NO_PRE_ORIGIN_DIVIDEND_Q_ZERO",
        "b1a_complete": True,
        "b1b_complete": False,
        "b1c_complete": False,
        "b1q_atm_iv": 0.2,
        "b1q_skew": None,
        "b1q_term_structure": None,
        "b1q_max_sip_timestamp_ns": int(origin_timestamp.timestamp() * 1_000_000_000),
        "b1q_quote_not_after_origin": True,
        "b1q_pit_evidence_valid": True,
    }
    if include_exogenous_evidence:
        available_at = origin_timestamp - timedelta(days=1)
        row.update(
            {
                "rate_source_available_at_utc": available_at,
                "rate_source_payload_sha256": "e" * 64,
                "dividend_source_available_at_utc": available_at,
                "dividend_source_payload_sha256": "f" * 64,
            }
        )
    return row


def test_exact_origin_grid_matches_phase5_rv30_spacing() -> None:
    """A regular XNYS session retains 71 five-minute RV30-safe origins."""
    origins = build_exact_development_origins(("2026-03-24",), assets=("AAPL",))

    assert origins.height == 71
    assert origins.row(0, named=True)["forecast_origin_utc"] == datetime(
        2026, 3, 24, 13, 35, tzinfo=UTC
    )
    assert origins.row(-1, named=True)["forecast_origin_utc"] == datetime(
        2026, 3, 24, 19, 25, tzinfo=UTC
    )


def test_same_day_rate_provenance_nulls_the_b1q_state() -> None:
    """A rate dated on the origin session cannot enter a B1Q predictor row."""
    origins = build_exact_development_origins(("2026-03-24",), assets=("AAPL",)).head(1)
    source_row = _b1_source_row(origins.row(0, named=True), rate_source_date="2026-03-24")
    source = pl.DataFrame([source_row])

    prepared = prepare_b1q_source(origins, source)
    row = prepared.row(0, named=True)

    assert row["b1q_source_missing_reason"] == B1Q_EXOGENOUS_INPUT_PROVENANCE_UNRESOLVED
    assert row["b1q_atm_iv"] is None
    assert row["b1q_skew"] is None
    assert row["b1q_term_structure"] is None
    assert row["b1q_max_sip_timestamp_ns"] is None
    assert row["b1a_complete"] is False
    assert row["b1q_pit_evidence_valid"] is False


def test_prior_rate_without_timestamped_payload_evidence_nulls_the_b1q_state() -> None:
    """A prior calendar date alone cannot establish B1Q exogenous provenance."""
    origins = build_exact_development_origins(("2026-03-24",), assets=("AAPL",)).head(1)
    source = pl.DataFrame(
        [
            _b1_source_row(
                origins.row(0, named=True),
                rate_source_date="2026-03-23",
                include_exogenous_evidence=False,
            )
        ]
    )

    prepared = prepare_b1q_source(origins, source)
    row = prepared.row(0, named=True)

    assert row["b1q_source_missing_reason"] == B1Q_EXOGENOUS_INPUT_PROVENANCE_UNRESOLVED
    assert row["b1q_exogenous_provenance_verified"] is False
    assert row["b1q_atm_iv"] is None


def test_missing_retained_b1q_source_is_not_carried_forward() -> None:
    """An unresolved retained cache date stays null rather than using an earlier B1Q row."""
    all_origins = build_exact_development_origins(("2026-03-24", "2026-03-25"), assets=("AAPL",))
    retained_origin = all_origins.filter(pl.col("session_date") == "2026-03-25").head(1)
    origins = pl.concat([all_origins.head(1), retained_origin])
    source_row = _b1_source_row(origins.row(0, named=True), rate_source_date="2026-03-23")
    source = pl.DataFrame([source_row])

    prepared = prepare_b1q_source(
        origins,
        source,
        retained_cache_asset_dates=frozenset({("AAPL", "2026-03-25")}),
    )
    retained = prepared.filter(pl.col("session_date") == "2026-03-25").row(0, named=True)

    assert retained["b1q_source_missing_reason"] == B1Q_EXOGENOUS_INPUT_PROVENANCE_UNRESOLVED
    assert retained["b1q_atm_iv"] is None
    assert retained["b1q_max_sip_timestamp_ns"] is None
    assert retained["b1q_quote_not_after_origin"] is False


def test_source_coverage_ledger_blocks_an_unresolved_b1q_input() -> None:
    """A B1Q provenance failure prevents target binding even with B0 and B2 present."""
    origins = build_exact_development_origins(("2026-03-24",), assets=("AAPL",))
    source = pl.DataFrame(
        [
            _b1_source_row(row, rate_source_date="2026-03-24")
            for row in origins.iter_rows(named=True)
        ]
    )
    prepared = prepare_b1q_source(origins, source)
    source_dates = pl.DataFrame({"asset": ["AAPL"], "session_date": ["2026-03-24"]})

    ledger = build_source_coverage_ledger(
        origins,
        b0_asset_dates=source_dates,
        b2_asset_dates=source_dates,
        b1q_source=prepared,
        source_hashes=_source_hashes(),
    )

    assert ledger["status"] == "BLOCKED_SOURCE_COVERAGE"
    assert ledger["components"]["B0"]["status"] == "PASS"
    assert ledger["components"]["B2"]["status"] == "PASS"
    assert ledger["components"]["B1Q"]["unresolved_origin_count"] == 71
    assert ledger["target_binding_permitted"] is False


def test_passing_source_coverage_ledger_is_hashed_and_schema_valid() -> None:
    """A fully present, pre-origin source ledger has a deterministic contract identity."""
    origins = build_exact_development_origins(("2026-03-24",), assets=("AAPL",))
    source = pl.DataFrame(
        [
            _b1_source_row(row, rate_source_date="2026-03-23")
            for row in origins.iter_rows(named=True)
        ]
    )
    prepared = prepare_b1q_source(origins, source)
    source_dates = pl.DataFrame({"asset": ["AAPL"], "session_date": ["2026-03-24"]})

    ledger = build_source_coverage_ledger(
        origins,
        b0_asset_dates=source_dates,
        b2_asset_dates=source_dates,
        b1q_source=prepared,
        source_hashes=_source_hashes(),
    )
    schema = json.loads(
        (
            ROOT
            / "specs"
            / "001-pit-options-rv30"
            / "contracts"
            / "corrected-development-source-coverage-v1.schema.json"
        ).read_text(encoding="utf-8")
    )

    unsigned = {key: value for key, value in ledger.items() if key != "ledger_sha256"}
    assert ledger["status"] == "PASS_SOURCE_COVERAGE"
    assert ledger["ledger_sha256"] == canonical_sha256(unsigned)
    assert list(Draft202012Validator(schema).iter_errors(ledger)) == []


def test_source_coverage_ledger_rejects_an_unbound_input_digest() -> None:
    """A source ledger cannot claim a malformed input hash as reproducible evidence."""
    origins = build_exact_development_origins(("2026-03-24",), assets=("AAPL",)).head(1)
    source = pl.DataFrame(
        [_b1_source_row(origins.row(0, named=True), rate_source_date="2026-03-23")]
    )
    prepared = prepare_b1q_source(origins, source)
    source_dates = pl.DataFrame({"asset": ["AAPL"], "session_date": ["2026-03-24"]})

    with pytest.raises(ValueError, match="CORRECTED_DEVELOPMENT_SOURCE_HASH_INVALID"):
        build_source_coverage_ledger(
            origins,
            b0_asset_dates=source_dates,
            b2_asset_dates=source_dates,
            b1q_source=prepared,
            source_hashes={"b1q_source": "not-a-digest"},
        )


def test_source_coverage_ledger_rejects_a_tampered_self_hash() -> None:
    """Schema validation fails closed if the declared ledger identity changes."""
    origins = build_exact_development_origins(("2026-03-24",), assets=("AAPL",)).head(1)
    source = pl.DataFrame(
        [_b1_source_row(origins.row(0, named=True), rate_source_date="2026-03-23")]
    )
    prepared = prepare_b1q_source(origins, source)
    source_dates = pl.DataFrame({"asset": ["AAPL"], "session_date": ["2026-03-24"]})
    ledger = build_source_coverage_ledger(
        origins,
        b0_asset_dates=source_dates,
        b2_asset_dates=source_dates,
        b1q_source=prepared,
        source_hashes=_source_hashes(),
    )
    ledger["ledger_sha256"] = "0" * 64
    schema_path = (
        ROOT
        / "specs"
        / "001-pit-options-rv30"
        / "contracts"
        / "corrected-development-source-coverage-v1.schema.json"
    )

    with pytest.raises(
        ValueError,
        match="CORRECTED_DEVELOPMENT_SOURCE_COVERAGE_SELF_HASH_MISMATCH",
    ):
        validate_source_coverage_ledger(ledger, schema_path)
