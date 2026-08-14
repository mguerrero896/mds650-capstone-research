"""Massive shifted-cutoff attempt materialization for B1v3."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import mds650.provider_timing_v21 as timing
from mds650.b1v3_massive_sensitivity import (
    reselected_attempt_row,
    write_massive_reselected_attempts,
)


def _attempt() -> dict[str, Any]:
    origin_ns = 1_700_000_000_000_000_000
    return {
        "origin_id": "AAPL:origin",
        "asset": "AAPL",
        "session_date": "2024-08-02",
        "forecast_origin_ns": origin_ns,
        "contract": "O:AAPL240830C00200000",
        "source_request_hash": "a" * 64,
        "spot": 200.0,
        "strike": 200.0,
        "dte": 28,
        "rate": 0.05,
        "dividend_yield": 0.0,
        "option_type": "call",
        "sip_timestamp": origin_ns,
        "sequence_number": 1,
        "bid": 5.0,
        "ask": 5.2,
        "midpoint": 5.1,
        "relative_spread": 0.2 / 5.1,
        "quote_age_seconds": 0.0,
        "iv_success": True,
        "iv": 0.2,
        "failure_reason": None,
    }


def test_reselected_attempt_uses_shifted_cutoff_and_recomputes_iv() -> None:
    row = _attempt()
    origin_ns = int(row["forecast_origin_ns"])
    quote = (origin_ns - 61_000_000_000, 9, 5.0, 5.2)

    output = reselected_attempt_row(row, quote=quote, cutoff_seconds=60)

    assert output["quote_cutoff_seconds"] == 60
    assert output["sip_timestamp"] == quote[0]
    assert output["sequence_number"] == 9
    assert output["quote_age_seconds"] == pytest.approx(1.0)
    assert output["iv_success"] is True
    assert isinstance(output["iv"], float)


def test_reselected_attempt_marks_no_quote_and_invalid_last_spread() -> None:
    row = _attempt()
    missing = reselected_attempt_row(row, quote=None, cutoff_seconds=300)
    invalid = reselected_attempt_row(
        row,
        quote=(int(row["forecast_origin_ns"]) - 60_000_000_000, 2, 5.2, 5.1),
        cutoff_seconds=60,
    )

    assert missing["failure_reason"] == "NO_QUOTE_AT_OR_BEFORE_CUTOFF"
    assert missing["iv_success"] is False
    assert missing["sip_timestamp"] is None
    assert invalid["failure_reason"] == "INVALID_SELECTED_NBBO"
    assert invalid["iv_success"] is False


def test_reselected_attempt_rejects_future_quote_and_unregistered_cutoff() -> None:
    row = _attempt()
    cutoff_ns = int(row["forecast_origin_ns"]) - 60_000_000_000

    with pytest.raises(ValueError, match="B1V3_SENSITIVITY_FUTURE_QUOTE"):
        reselected_attempt_row(
            row,
            quote=(cutoff_ns + 1, 1, 5.0, 5.2),
            cutoff_seconds=60,
        )
    with pytest.raises(ValueError, match="B1V3_SENSITIVITY_CUTOFF_INVALID"):
        reselected_attempt_row(row, quote=None, cutoff_seconds=30)


def _write_attempts(path: Path, rows: list[dict[str, object]]) -> None:
    pq.write_table(pa.Table.from_pylist(rows), path)


def _install_valid_cache_stubs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(timing, "_massive_cache_index", lambda _root: {})
    monkeypatch.setattr(
        timing,
        "_load_and_validate_massive_cache",
        lambda **_kwargs: (
            "OK",
            [(1_699_999_600_000_000_000, 7, 5.0, 5.2)],
        ),
    )
    monkeypatch.setattr(
        timing,
        "_select_prepared_quote",
        lambda quotes, cutoff_ns: max(
            (quote for quote in quotes if quote[0] <= cutoff_ns),
            default=None,
        ),
    )


def test_write_massive_reselected_attempts_streams_and_preserves_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = tmp_path / "attempts.parquet"
    cache_root = tmp_path / "cache"
    output = tmp_path / "out" / "shifted.parquet"
    cache_root.mkdir()
    first = _attempt()
    second = {**_attempt(), "origin_id": "AAPL:later"}
    second["forecast_origin_ns"] = int(first["forecast_origin_ns"]) + 60_000_000_000
    third = {
        **_attempt(),
        "origin_id": "MSFT:origin",
        "asset": "MSFT",
        "contract": "O:MSFT240830C00400000",
        "source_request_hash": "b" * 64,
    }
    _write_attempts(attempts, [first, second, third])
    _install_valid_cache_stubs(monkeypatch)

    summary = write_massive_reselected_attempts(
        attempts_path=attempts,
        cache_root=cache_root,
        output_path=output,
        cutoff_seconds=60,
        batch_size=1,
    )

    result = pq.read_table(output).to_pylist()
    assert summary["status"] == "PASS_TARGET_BLIND_MASSIVE_RESELECTION"
    assert summary["attempt_count"] == 3
    assert summary["asset_day_count"] == 2
    assert summary["contract_day_count"] == 2
    assert summary["cache_decode_count"] == 2
    assert summary["selected_quote_count"] == 3
    assert summary["no_quote_count"] == 0
    assert summary["iv_success_count"] == 3
    assert summary["max_asset_day_rows"] == 2
    assert summary["input_sha256"] != summary["output_sha256"]
    assert len(result) == 3
    assert {row["quote_cutoff_seconds"] for row in result} == {60}


@pytest.mark.parametrize(
    ("cutoff", "batch_size", "error"),
    [
        (30, 1, "B1V3_SENSITIVITY_CUTOFF_INVALID"),
        (60, 0, "B1V3_SENSITIVITY_BATCH_SIZE_INVALID"),
    ],
)
def test_writer_rejects_invalid_controls(
    tmp_path: Path,
    cutoff: int,
    batch_size: int,
    error: str,
) -> None:
    with pytest.raises(ValueError, match=error):
        write_massive_reselected_attempts(
            attempts_path=tmp_path / "missing.parquet",
            cache_root=tmp_path,
            output_path=tmp_path / "output.parquet",
            cutoff_seconds=cutoff,
            batch_size=batch_size,
        )


def test_writer_rejects_missing_paths_and_output_conflict(tmp_path: Path) -> None:
    attempts = tmp_path / "attempts.parquet"
    cache_root = tmp_path / "cache"
    output = tmp_path / "output.parquet"
    with pytest.raises(FileNotFoundError, match="ATTEMPTS_MISSING"):
        write_massive_reselected_attempts(
            attempts_path=attempts,
            cache_root=cache_root,
            output_path=output,
            cutoff_seconds=60,
        )
    _write_attempts(attempts, [_attempt()])
    with pytest.raises(FileNotFoundError, match="CACHE_ROOT_MISSING"):
        write_massive_reselected_attempts(
            attempts_path=attempts,
            cache_root=cache_root,
            output_path=output,
            cutoff_seconds=60,
        )
    cache_root.mkdir()
    output.touch()
    with pytest.raises(ValueError, match="OUTPUT_CONFLICT"):
        write_massive_reselected_attempts(
            attempts_path=attempts,
            cache_root=cache_root,
            output_path=output,
            cutoff_seconds=60,
        )


def test_writer_rejects_schema_forbidden_and_empty_inputs(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    invalid = tmp_path / "invalid.parquet"
    forbidden = tmp_path / "forbidden.parquet"
    empty = tmp_path / "empty.parquet"
    _write_attempts(invalid, [{"asset": "AAPL"}])
    _write_attempts(forbidden, [{**_attempt(), "rv30": 1.0}])
    empty_schema = pa.Table.from_pylist([_attempt()]).schema
    pq.write_table(pa.Table.from_pylist([], schema=empty_schema), empty)
    with pytest.raises(ValueError, match="ATTEMPT_SCHEMA_INVALID"):
        write_massive_reselected_attempts(
            attempts_path=invalid,
            cache_root=cache_root,
            output_path=tmp_path / "invalid-output.parquet",
            cutoff_seconds=60,
        )
    with pytest.raises(ValueError, match="FORBIDDEN_COLUMN:rv30"):
        write_massive_reselected_attempts(
            attempts_path=forbidden,
            cache_root=cache_root,
            output_path=tmp_path / "forbidden-output.parquet",
            cutoff_seconds=60,
        )
    with pytest.raises(ValueError, match="EMPTY_INPUT"):
        write_massive_reselected_attempts(
            attempts_path=empty,
            cache_root=cache_root,
            output_path=tmp_path / "empty-output.parquet",
            cutoff_seconds=60,
        )


def test_writer_fails_closed_on_noncontiguous_and_ambiguous_attempts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    _install_valid_cache_stubs(monkeypatch)
    noncontiguous = tmp_path / "noncontiguous.parquet"
    middle = {**_attempt(), "asset": "MSFT", "contract": "O:MSFT240830C00400000"}
    _write_attempts(noncontiguous, [_attempt(), middle, _attempt()])
    with pytest.raises(ValueError, match="ASSET_DAY_NONCONTIGUOUS"):
        write_massive_reselected_attempts(
            attempts_path=noncontiguous,
            cache_root=cache_root,
            output_path=tmp_path / "noncontiguous-output.parquet",
            cutoff_seconds=60,
            batch_size=1,
        )

    ambiguous = tmp_path / "ambiguous.parquet"
    _write_attempts(
        ambiguous,
        [_attempt(), {**_attempt(), "source_request_hash": "c" * 64}],
    )
    with pytest.raises(ValueError, match="SOURCE_HASH_AMBIGUOUS"):
        write_massive_reselected_attempts(
            attempts_path=ambiguous,
            cache_root=cache_root,
            output_path=tmp_path / "ambiguous-output.parquet",
            cutoff_seconds=60,
        )


def test_writer_fails_closed_on_invalid_cache_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = tmp_path / "attempts.parquet"
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    _write_attempts(attempts, [_attempt()])
    monkeypatch.setattr(timing, "_massive_cache_index", lambda _root: {})
    monkeypatch.setattr(
        timing,
        "_load_and_validate_massive_cache",
        lambda **_kwargs: ("CACHE_INVALID", []),
    )
    with pytest.raises(ValueError, match="CACHE_INVALID:CACHE_INVALID"):
        write_massive_reselected_attempts(
            attempts_path=attempts,
            cache_root=cache_root,
            output_path=tmp_path / "output.parquet",
            cutoff_seconds=60,
        )


def test_reselected_attempt_handles_invalid_origin_nonfinite_and_invalid_iv_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValueError, match="ORIGIN_INVALID"):
        reselected_attempt_row(
            {**_attempt(), "forecast_origin_ns": None},
            quote=None,
            cutoff_seconds=60,
        )
    row = _attempt()
    origin_ns = int(row["forecast_origin_ns"])
    monkeypatch.setattr(timing, "_iv_from_reselected_quote", lambda **_kw: None)
    output = reselected_attempt_row(
        row,
        quote=(origin_ns - 60_000_000_000, 1, float("nan"), 5.2),
        cutoff_seconds=60,
    )
    assert output["midpoint"] is None
    assert output["relative_spread"] is None
    assert output["iv_success"] is False
    assert output["failure_reason"] == "IV_RESULT_INVALID"
