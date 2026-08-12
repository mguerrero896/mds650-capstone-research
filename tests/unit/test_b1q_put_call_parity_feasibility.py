"""Tests for the target-free B1Q put-call-parity feasibility diagnostic."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import polars as pl
import pytest
from jsonschema import Draft202012Validator

from mds650.b1q_put_call_parity_feasibility import (
    ALLOWED_ATTEMPT_COLUMNS,
    B1Q_PARITY_OUTPUT_CONFLICT,
    assess_put_call_parity_feasibility,
    validate_put_call_parity_feasibility_report,
    write_json_if_new_or_identical,
)
from mds650.study_design import canonical_sha256

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = (
    ROOT
    / "specs"
    / "001-pit-options-rv30"
    / "contracts"
    / "b1q-put-call-parity-feasibility-v1.schema.json"
)


def _row(
    *,
    option_type: str,
    strike: float,
    bid: float,
    ask: float,
    contract_suffix: str,
    sip_timestamp: int = 1_700_000_000_000_000_000,
) -> dict[str, object]:
    """Return one valid, target-free quote attempt fixture."""
    return {
        "asset": "AAPL",
        "session_date": "2026-03-30",
        "origin_id": "AAPL:2026-03-30T16:00:00+00:00",
        "forecast_origin_utc": "2026-03-30T16:00:00+00:00",
        "forecast_origin_ns": 1_774_885_600_000_000_000,
        "expiry": "2026-05-01",
        "strike": strike,
        "option_type": option_type,
        "contract": f"O:AAPL260501{contract_suffix}",
        "sip_timestamp": sip_timestamp,
        "bid": bid,
        "ask": ask,
        "quote_age_seconds": 30.0,
        "relative_spread": 0.02,
    }


def _frame(*, two_strikes: bool, include_forbidden_columns: bool = False) -> pl.DataFrame:
    """Build a fixture with one or two same-expiry put-call pairs."""
    rows = [
        _row(option_type="call", strike=100.0, bid=11.9, ask=12.1, contract_suffix="C00100000"),
        _row(option_type="put", strike=100.0, bid=1.9, ask=2.1, contract_suffix="P00100000"),
    ]
    if two_strikes:
        rows.extend(
            [
                _row(
                    option_type="call",
                    strike=110.0,
                    bid=5.9,
                    ask=6.1,
                    contract_suffix="C00110000",
                ),
                _row(
                    option_type="put",
                    strike=110.0,
                    bid=5.9,
                    ask=6.1,
                    contract_suffix="P00110000",
                ),
            ]
        )
    frame = pl.DataFrame(rows)
    if include_forbidden_columns:
        frame = frame.with_columns(
            pl.lit(0.03).alias("rv30"),
            pl.lit(0.02).alias("qlike"),
            pl.lit("prediction").alias("model_prediction"),
        )
    return frame


def _rehash(report: dict[str, object]) -> None:
    """Refresh a report hash after a deliberate valid-field mutation."""
    unsigned = {key: value for key, value in report.items() if key != "semantic_self_hash"}
    report["semantic_self_hash"] = f"sha256:{canonical_sha256(unsigned)}"


def test_one_strike_pair_is_not_silently_used_as_a_rate_or_dividend_proxy() -> None:
    """One paired strike cannot estimate a discount factor by put-call parity."""
    result = assess_put_call_parity_feasibility(
        _frame(two_strikes=False),
        source_file_sha256="a" * 64,
    )

    assert result["status"] == "INFEASIBLE_WITH_CURRENT_CONTRACT_GRID"
    assert result["origin_count"] == 1
    assert result["origins_with_any_pair"] == 1
    assert result["origins_with_two_strike_expiry"] == 0
    assert result["origins_with_valid_discount_estimate"] == 0
    assert result["method_change_authorized"] is False
    assert result["safe_to_reconcile_existing_results"] == "NO"
    assert result["safe_to_open_or_evaluate_oos"] == "NO"


def test_two_paired_strikes_produce_a_candidate_discount_estimate_without_using_targets() -> None:
    """Two valid paired strikes are the minimum numerical requirement for parity."""
    baseline = assess_put_call_parity_feasibility(
        _frame(two_strikes=True),
        source_file_sha256="b" * 64,
    )
    with_forbidden = assess_put_call_parity_feasibility(
        _frame(two_strikes=True, include_forbidden_columns=True),
        source_file_sha256="b" * 64,
    )

    assert baseline == with_forbidden
    assert baseline["status"] == "FEASIBLE_CANDIDATE_REQUIRES_METHOD_AMENDMENT"
    assert baseline["origins_with_two_strike_expiry"] == 1
    assert baseline["origins_with_valid_discount_estimate"] == 1
    assert baseline["valid_discount_estimate_median"] == pytest.approx(1.0)
    assert tuple(ALLOWED_ATTEMPT_COLUMNS) == (
        "asset",
        "session_date",
        "origin_id",
        "forecast_origin_utc",
        "forecast_origin_ns",
        "expiry",
        "strike",
        "option_type",
        "contract",
        "sip_timestamp",
        "bid",
        "ask",
        "quote_age_seconds",
        "relative_spread",
    )
    assert baseline["forbidden_target_or_outcome_columns_read"] == []


def test_repeated_target_grid_entries_are_deduplicated_when_quote_identity_is_identical() -> None:
    """The existing grid may repeat a resolved contract; it must not inflate coverage."""
    frame = _frame(two_strikes=True)
    duplicated = pl.concat([frame, frame.head(1)])

    result = assess_put_call_parity_feasibility(
        duplicated,
        source_file_sha256="c" * 64,
    )

    assert result["valid_quote_rows_before_contract_quote_deduplication"] == 5
    assert result["duplicate_contract_quote_records_dropped"] == 1
    assert result["valid_quote_rows"] == 4
    assert result["origins_with_valid_discount_estimate"] == 1


def test_schema_self_hash_and_immutable_writer_are_deterministic(tmp_path: Path) -> None:
    """The report is schema-valid, hash-bound, and cannot be overwritten by drift."""
    result = assess_put_call_parity_feasibility(
        _frame(two_strikes=False),
        source_file_sha256="d" * 64,
    )
    unsigned = dict(result)
    semantic_self_hash = unsigned.pop("semantic_self_hash")
    assert semantic_self_hash == f"sha256:{canonical_sha256(unsigned)}"

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert list(Draft202012Validator(schema).iter_errors(result)) == []

    output = tmp_path / "parity.json"
    assert write_json_if_new_or_identical(output, result) == "CREATED"
    expected_bytes = output.read_bytes()
    assert write_json_if_new_or_identical(output, result) == "IDENTICAL"
    assert output.read_bytes() == expected_bytes

    drift = dict(result)
    drift["interpretation"] = "A different but still sanitized interpretation."
    _rehash(drift)
    with pytest.raises(ValueError, match=B1Q_PARITY_OUTPUT_CONFLICT):
        write_json_if_new_or_identical(output, drift)

    assert (
        hashlib.sha256(output.read_bytes()).hexdigest()
        == hashlib.sha256(expected_bytes).hexdigest()
    )


def test_runtime_validator_rejects_hash_schema_and_sensitive_content_before_a_write() -> None:
    """A report must fail closed even if a caller bypasses the construction helper."""
    report = assess_put_call_parity_feasibility(
        _frame(two_strikes=False),
        source_file_sha256="e" * 64,
    )

    invalid_hash = dict(report)
    invalid_hash["semantic_self_hash"] = "sha256:" + ("0" * 64)
    with pytest.raises(ValueError, match="B1Q_PARITY_REPORT_SELF_HASH_INVALID"):
        validate_put_call_parity_feasibility_report(invalid_hash)

    schema_invalid = dict(report)
    schema_invalid["safe_to_open_or_evaluate_oos"] = "YES"
    _rehash(schema_invalid)
    with pytest.raises(ValueError, match="B1Q_PARITY_REPORT_SCHEMA_INVALID"):
        validate_put_call_parity_feasibility_report(schema_invalid)

    sensitive = dict(report)
    sensitive["interpretation"] = "Authorization: Bearer secret"
    _rehash(sensitive)
    with pytest.raises(ValueError, match="B1Q_PARITY_REPORT_HYGIENE_INVALID"):
        validate_put_call_parity_feasibility_report(sensitive)
