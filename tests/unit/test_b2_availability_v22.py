"""Regression tests for the target-blind B2 availability remediation."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq

from mds650.b2_availability_v22 import build_b2_availability_sidecar
from mds650.provider_timing_v21 import B2_FEATURE_COLUMNS


def _origin(asset: str, minute: int) -> dict[str, object]:
    """Return a target-free five-minute origin fixture."""
    instant = datetime(2025, 10, 20, 13, minute, tzinfo=UTC)
    return {
        "origin_id": f"{asset}:{instant.isoformat()}",
        "asset": asset,
        "session_date": "2025-10-20",
        "forecast_origin_utc": instant,
    }


def _write_origins(path: Path, rows: list[dict[str, object]]) -> None:
    """Write a minimal target-free origin projection."""
    pl.DataFrame(rows).write_parquet(path)


def _matrix_row(origin: dict[str, object], count: float) -> dict[str, object]:
    """Return one canonical B2 raw-activity fixture row."""
    values = {name: 0.0 for name in B2_FEATURE_COLUMNS}
    values["option_trade_count_5m"] = count
    if count:
        values["unique_contract_count_5m"] = count
        values["total_premium_5m"] = 100.0 * count
        values["max_trade_premium_5m"] = 100.0
        values["call_premium_5m"] = 100.0 * count
        values["strike_concentration"] = 1.0
        values["expiry_concentration"] = 1.0
    return {
        **origin,
        "b2v2_cutoff_utc": origin["forecast_origin_utc"],
        "b2v2_max_created_at_utc": None,
        **values,
    }


def _write_matrix(path: Path, rows: list[dict[str, object]]) -> str:
    """Write one canonical raw-activity fixture and return its source hash."""
    pl.DataFrame(rows).write_parquet(path)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_events(path: Path, rows: list[dict[str, object]]) -> None:
    """Write minimal raw Full Tape timestamps for one asset-date fixture."""
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.table(
            {
                "underlying_symbol": pa.array([row["underlying_symbol"] for row in rows]),
                "executed_at": pa.array(
                    [row["executed_at"] for row in rows], type=pa.timestamp("us", tz="UTC")
                ),
                "created_at": pa.array(
                    [row["created_at"] for row in rows], type=pa.timestamp("us", tz="UTC")
                ),
            }
        ),
        path,
    )


def _trace(
    *, canonical_hash: str, state: str, variant: str = "primary_5m_60s"
) -> list[dict[str, object]]:
    """Return a single traceability fixture row."""
    return [
        {
            "canonical_variant": variant,
            "session_date": "2025-10-20",
            "asset": "AAPL",
            "canonical_file_sha256": canonical_hash,
            "source_temporal_state": state,
            "coding_status": "ZERO_CODING_POTENTIALLY_CONFOUNDED"
            if state == "RECORD_CREATION_DELAY_OBSERVED"
            else "NUMERIC_NONZERO_FEATURE_VALUES",
        }
    ]


def test_delayed_raw_trade_cannot_remain_usable_numeric_zero(tmp_path: Path) -> None:
    """A delayed raw candidate must make the corresponding zero row ineligible."""
    late, activity = _origin("AAPL", 35), _origin("AAPL", 45)
    origins_path = tmp_path / "origins.parquet"
    _write_origins(origins_path, [late, activity])
    matrix_path = tmp_path / "matrix" / "primary_5m_60s" / "date=2025-10-20.parquet"
    matrix_path.parent.mkdir(parents=True)
    matrix_hash = _write_matrix(matrix_path, [_matrix_row(late, 0.0), _matrix_row(activity, 1.0)])
    event_path = tmp_path / "events" / "date=2025-10-20" / "asset=AAPL" / "events.parquet"
    _write_events(
        event_path,
        [
            {
                "underlying_symbol": "AAPL",
                "executed_at": datetime(2025, 10, 20, 13, 31, tzinfo=UTC),
                "created_at": datetime(2025, 10, 20, 13, 35, tzinfo=UTC),
            },
            {
                "underlying_symbol": "AAPL",
                "executed_at": datetime(2025, 10, 20, 13, 41, tzinfo=UTC),
                "created_at": datetime(2025, 10, 20, 13, 42, tzinfo=UTC),
            },
        ],
    )

    sidecar, summary = build_b2_availability_sidecar(
        event_root=tmp_path / "events",
        matrix_root=tmp_path / "matrix",
        expected_origins_path=origins_path,
        traceability_rows=_trace(
            canonical_hash=matrix_hash, state="RECORD_CREATION_DELAY_OBSERVED"
        ),
    )

    rows = {row["origin_id"]: row for row in sidecar.to_dicts()}
    assert rows[late["origin_id"]]["row_status"] == "PIT_EXCLUDED_DELAYED_RAW_WINDOW_TRADES"
    assert rows[late["origin_id"]]["eligible_for_corrected_pit_panel"] is False
    assert rows[late["origin_id"]]["delayed_raw_window_trade_count"] == 1
    assert rows[activity["origin_id"]]["row_status"] == "PIT_USABLE_ELIGIBLE_ACTIVITY_DELAY_CONTEXT"
    assert rows[activity["origin_id"]]["eligible_for_corrected_pit_panel"] is True
    assert summary["primary_delayed_raw_zero_exclusion_count"] == 1


def test_clean_zero_without_raw_trade_is_retained_under_registered_proxy(tmp_path: Path) -> None:
    """A clean-source zero remains distinct from a delayed-record zero."""
    origin = _origin("AAPL", 35)
    origins_path = tmp_path / "origins.parquet"
    _write_origins(origins_path, [origin])
    matrix_path = tmp_path / "matrix" / "primary_5m_60s" / "date=2025-10-20.parquet"
    matrix_path.parent.mkdir(parents=True)
    matrix_hash = _write_matrix(matrix_path, [_matrix_row(origin, 0.0)])
    event_root = tmp_path / "events"
    event_root.mkdir()

    sidecar, summary = build_b2_availability_sidecar(
        event_root=event_root,
        matrix_root=tmp_path / "matrix",
        expected_origins_path=origins_path,
        traceability_rows=_trace(canonical_hash=matrix_hash, state="SOURCE_AVAILABLE"),
    )

    row = sidecar.to_dicts()[0]
    assert row["row_status"] == "PIT_USABLE_ZERO_NO_DELAY_INCIDENT"
    assert row["eligible_for_corrected_pit_panel"] is True
    assert row["raw_window_trade_count"] is None
    assert summary["excluded_row_count"] == 0


def test_confounded_nonzero_count_mismatch_fails_closed(tmp_path: Path) -> None:
    """Raw/canonical count disagreement cannot silently enter a corrected panel."""
    origin = _origin("AAPL", 35)
    origins_path = tmp_path / "origins.parquet"
    _write_origins(origins_path, [origin])
    matrix_path = tmp_path / "matrix" / "primary_5m_60s" / "date=2025-10-20.parquet"
    matrix_path.parent.mkdir(parents=True)
    matrix_hash = _write_matrix(matrix_path, [_matrix_row(origin, 2.0)])
    event_path = tmp_path / "events" / "date=2025-10-20" / "asset=AAPL" / "events.parquet"
    _write_events(
        event_path,
        [
            {
                "underlying_symbol": "AAPL",
                "executed_at": datetime(2025, 10, 20, 13, 31, tzinfo=UTC),
                "created_at": datetime(2025, 10, 20, 13, 32, tzinfo=UTC),
            }
        ],
    )

    sidecar, summary = build_b2_availability_sidecar(
        event_root=tmp_path / "events",
        matrix_root=tmp_path / "matrix",
        expected_origins_path=origins_path,
        traceability_rows=_trace(
            canonical_hash=matrix_hash, state="RECORD_CREATION_DELAY_OBSERVED"
        ),
    )

    row = sidecar.to_dicts()[0]
    assert row["row_status"] == "PIT_EXCLUDED_CANONICAL_RAW_COUNT_MISMATCH"
    assert row["eligible_for_corrected_pit_panel"] is False
    assert summary["canonical_raw_count_mismatch_count"] == 1


def test_primary_exclusion_summary_does_not_count_sensitivity_variant(tmp_path: Path) -> None:
    """The named primary count must not absorb a delayed sensitivity exclusion."""
    origin = _origin("AAPL", 35)
    origins_path = tmp_path / "origins.parquet"
    _write_origins(origins_path, [origin])
    primary = tmp_path / "matrix" / "primary_5m_60s" / "date=2025-10-20.parquet"
    primary.parent.mkdir(parents=True)
    primary_hash = _write_matrix(primary, [_matrix_row(origin, 0.0)])
    sensitivity = tmp_path / "matrix" / "latency_5m_120s" / "date=2025-10-20.parquet"
    sensitivity.parent.mkdir(parents=True)
    sensitivity_hash = _write_matrix(sensitivity, [_matrix_row(origin, 0.0)])
    event_path = tmp_path / "events" / "date=2025-10-20" / "asset=AAPL" / "events.parquet"
    _write_events(
        event_path,
        [
            {
                "underlying_symbol": "AAPL",
                "executed_at": datetime(2025, 10, 20, 13, 31, tzinfo=UTC),
                "created_at": datetime(2025, 10, 20, 13, 35, tzinfo=UTC),
            }
        ],
    )

    _, summary = build_b2_availability_sidecar(
        event_root=tmp_path / "events",
        matrix_root=tmp_path / "matrix",
        expected_origins_path=origins_path,
        traceability_rows=[
            *_trace(canonical_hash=primary_hash, state="SOURCE_AVAILABLE"),
            *_trace(
                canonical_hash=sensitivity_hash,
                state="RECORD_CREATION_DELAY_OBSERVED",
                variant="latency_5m_120s",
            ),
        ],
    )

    assert summary["primary_delayed_raw_zero_exclusion_count"] == 0


def test_sidecar_supports_late_high_raw_count_after_small_rows(tmp_path: Path) -> None:
    """Large delayed counts must not overflow Polars' inferred row schema."""
    base = datetime(2025, 10, 20, 13, 0, tzinfo=UTC)
    origins = [
        {
            "origin_id": f"AAPL:{index}",
            "asset": "AAPL",
            "session_date": "2025-10-20",
            "forecast_origin_utc": base + timedelta(minutes=5 * index),
        }
        for index in range(101)
    ]
    origins_path = tmp_path / "origins.parquet"
    _write_origins(origins_path, origins)
    matrix_path = tmp_path / "matrix" / "primary_5m_60s" / "date=2025-10-20.parquet"
    matrix_path.parent.mkdir(parents=True)
    matrix_hash = _write_matrix(matrix_path, [_matrix_row(origin, 0.0) for origin in origins])
    last_origin = origins[-1]["forecast_origin_utc"]
    event_path = tmp_path / "events" / "date=2025-10-20" / "asset=AAPL" / "events.parquet"
    _write_events(
        event_path,
        [
            {
                "underlying_symbol": "AAPL",
                "executed_at": last_origin - timedelta(minutes=4),
                "created_at": last_origin,
            }
            for _ in range(3_056)
        ],
    )

    sidecar, _ = build_b2_availability_sidecar(
        event_root=tmp_path / "events",
        matrix_root=tmp_path / "matrix",
        expected_origins_path=origins_path,
        traceability_rows=_trace(
            canonical_hash=matrix_hash, state="RECORD_CREATION_DELAY_OBSERVED"
        ),
    )

    assert sidecar.height == 101
    assert sidecar.tail(1).item(0, "delayed_raw_window_trade_count") == 3_056


def test_sidecar_rejects_traceability_source_hash_drift(tmp_path: Path) -> None:
    """A sidecar must fail before using a canonical file with a stale trace hash."""
    origin = _origin("AAPL", 35)
    origins_path = tmp_path / "origins.parquet"
    _write_origins(origins_path, [origin])
    matrix_path = tmp_path / "matrix" / "primary_5m_60s" / "date=2025-10-20.parquet"
    matrix_path.parent.mkdir(parents=True)
    _write_matrix(matrix_path, [_matrix_row(origin, 0.0)])

    try:
        build_b2_availability_sidecar(
            event_root=tmp_path / "events",
            matrix_root=tmp_path / "matrix",
            expected_origins_path=origins_path,
            traceability_rows=_trace(canonical_hash="0" * 64, state="SOURCE_AVAILABLE"),
        )
    except ValueError as exc:
        assert str(exc) == "B2_AVAILABILITY_CANONICAL_HASH_MISMATCH"
    else:  # pragma: no cover - explicit failure path assertion
        raise AssertionError("expected canonical-hash validation failure")


def test_confounded_group_with_missing_raw_partition_fails_closed(tmp_path: Path) -> None:
    """A delay-flagged group cannot pass when its raw partition is unavailable."""
    origin = _origin("AAPL", 35)
    origins_path = tmp_path / "origins.parquet"
    _write_origins(origins_path, [origin])
    matrix_path = tmp_path / "matrix" / "primary_5m_60s" / "date=2025-10-20.parquet"
    matrix_path.parent.mkdir(parents=True)
    matrix_hash = _write_matrix(matrix_path, [_matrix_row(origin, 0.0)])

    sidecar, _ = build_b2_availability_sidecar(
        event_root=tmp_path / "events",
        matrix_root=tmp_path / "matrix",
        expected_origins_path=origins_path,
        traceability_rows=_trace(
            canonical_hash=matrix_hash, state="RECORD_CREATION_DELAY_OBSERVED"
        ),
    )

    assert sidecar.item(0, "row_status") == "PIT_EXCLUDED_SOURCE_UNAVAILABLE_OR_SCHEMA_INVALID"
    assert sidecar.item(0, "eligible_for_corrected_pit_panel") is False


def test_clean_source_nonzero_activity_remains_eligible(tmp_path: Path) -> None:
    """A nonzero canonical row with no delay incident stays separately classified."""
    origin = _origin("AAPL", 35)
    origins_path = tmp_path / "origins.parquet"
    _write_origins(origins_path, [origin])
    matrix_path = tmp_path / "matrix" / "primary_5m_60s" / "date=2025-10-20.parquet"
    matrix_path.parent.mkdir(parents=True)
    matrix_hash = _write_matrix(matrix_path, [_matrix_row(origin, 1.0)])

    sidecar, _ = build_b2_availability_sidecar(
        event_root=tmp_path / "events",
        matrix_root=tmp_path / "matrix",
        expected_origins_path=origins_path,
        traceability_rows=_trace(canonical_hash=matrix_hash, state="SOURCE_AVAILABLE"),
    )

    assert sidecar.item(0, "row_status") == "PIT_USABLE_ELIGIBLE_ACTIVITY"
    assert sidecar.item(0, "eligible_for_corrected_pit_panel") is True


def test_missing_created_at_in_confounded_window_is_excluded(tmp_path: Path) -> None:
    """A candidate without the operational availability timestamp cannot pass."""
    origin = _origin("AAPL", 35)
    origins_path = tmp_path / "origins.parquet"
    _write_origins(origins_path, [origin])
    matrix_path = tmp_path / "matrix" / "primary_5m_60s" / "date=2025-10-20.parquet"
    matrix_path.parent.mkdir(parents=True)
    matrix_hash = _write_matrix(matrix_path, [_matrix_row(origin, 0.0)])
    event_path = tmp_path / "events" / "date=2025-10-20" / "asset=AAPL" / "events.parquet"
    _write_events(
        event_path,
        [
            {
                "underlying_symbol": "AAPL",
                "executed_at": datetime(2025, 10, 20, 13, 31, tzinfo=UTC),
                "created_at": None,
            }
        ],
    )

    sidecar, _ = build_b2_availability_sidecar(
        event_root=tmp_path / "events",
        matrix_root=tmp_path / "matrix",
        expected_origins_path=origins_path,
        traceability_rows=_trace(
            canonical_hash=matrix_hash, state="RECORD_CREATION_DELAY_OBSERVED"
        ),
    )

    assert sidecar.item(0, "row_status") == "PIT_EXCLUDED_MISSING_CREATED_AT"
    assert sidecar.item(0, "eligible_for_corrected_pit_panel") is False
