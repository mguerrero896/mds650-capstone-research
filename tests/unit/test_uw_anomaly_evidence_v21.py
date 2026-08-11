"""Focused target-blind tests for the UW anomaly evidence sidecar."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from scripts.audit_uw_anomaly_evidence_v21 import main

from mds650.provider_timing_v21 import B2_FEATURE_COLUMNS, canonical_sha256
from mds650.uw_anomaly_evidence_v21 import (
    build_uw_anomaly_evidence_v21,
    validate_uw_anomaly_evidence_v21,
    write_uw_anomaly_evidence_v21,
)


def test_session_wide_delayed_created_at_zero_is_confounding_not_no_activity(
    tmp_path: Path,
) -> None:
    """A delayed nonempty source cannot make a canonical zero mean no activity."""
    event_root, matrix_root = _roots(tmp_path)
    _write_events(
        event_root,
        date="2025-10-20",
        asset="AAPL",
        executed=("2025-10-20T13:35:00Z", "2025-10-20T14:00:00Z"),
        created=("2025-10-20T19:46:00Z", "2025-10-20T19:47:00Z"),
        event_ids=("trade-id-must-not-leak-1", "trade-id-must-not-leak-2"),
    )
    _write_b2_rows(
        matrix_root,
        date="2025-10-20",
        asset="AAPL",
        rows=2,
        zero=True,
    )

    evidence = build_uw_anomaly_evidence_v21(
        event_root=event_root,
        matrix_root=matrix_root,
        session_dates=("2025-10-20",),
        raw_assets=("AAPL",),
    )

    row = evidence["canonical_rows"][0]
    assert evidence["activity_availability_gate"] == "FAIL"
    assert row["canonical_value_coding"] == "ZERO"
    assert row["availability_indicator_status"] == "INDICATOR_ABSENT"
    assert row["source_temporal_state"] == "SESSION_WIDE_CREATED_AT_DELAY_OBSERVED"
    assert row["zero_interpretation"] == "CONFOUNDED_BY_DELAY"
    assert row["zero_can_mean_no_activity"] is False
    assert "trade-id-must-not-leak" not in json.dumps(evidence)


def test_source_unavailable_zero_fails_closed(tmp_path: Path) -> None:
    """A zero row with no Full Tape partition is unavailable, never no activity."""
    event_root, matrix_root = _roots(tmp_path)
    _write_b2_rows(
        matrix_root,
        date="2025-10-21",
        asset="AAPL",
        rows=1,
        zero=True,
    )

    evidence = build_uw_anomaly_evidence_v21(
        event_root=event_root,
        matrix_root=matrix_root,
        session_dates=("2025-10-21",),
        raw_assets=("AAPL",),
    )

    row = evidence["canonical_rows"][0]
    assert evidence["activity_availability_gate"] == "FAIL"
    assert row["source_status"] == "SOURCE_UNAVAILABLE"
    assert row["canonical_value_coding"] == "ZERO"
    assert row["zero_interpretation"] == "SOURCE_UNAVAILABLE"
    assert row["zero_can_mean_no_activity"] is False


def test_canonical_rows_distinguish_missing_and_excluded_from_zero(tmp_path: Path) -> None:
    """Null features and absent assets retain distinct, nonzero classifications."""
    event_root, matrix_root = _roots(tmp_path)
    _write_events(
        event_root,
        date="2025-10-22",
        asset="AAPL",
        executed=("2025-10-22T13:35:00Z",),
        created=("2025-10-22T13:35:01Z",),
    )
    _write_events(
        event_root,
        date="2025-10-22",
        asset="QQQ",
        executed=("2025-10-22T13:35:00Z",),
        created=("2025-10-22T13:35:01Z",),
    )
    _write_b2_rows(
        matrix_root,
        date="2025-10-22",
        asset="AAPL",
        rows=1,
        zero=False,
        missing_feature="total_premium_5m",
    )

    evidence = build_uw_anomaly_evidence_v21(
        event_root=event_root,
        matrix_root=matrix_root,
        session_dates=("2025-10-22",),
        raw_assets=("AAPL", "QQQ"),
    )

    by_asset = {row["asset"]: row for row in evidence["canonical_rows"]}
    assert by_asset["AAPL"]["canonical_value_coding"] == "MISSING"
    assert by_asset["AAPL"]["availability_indicator_status"] == "INDICATOR_ABSENT"
    assert by_asset["QQQ"]["canonical_value_coding"] == "EXCLUDED"
    assert by_asset["QQQ"]["row_presence_status"] == "EXCLUDED"
    assert by_asset["QQQ"]["zero_interpretation"] == "NOT_APPLICABLE"


def test_evidence_is_deterministic_schema_valid_and_sanitised(tmp_path: Path) -> None:
    """The JSON sidecar is hash-bound, valid, and contains no local source paths."""
    event_root, matrix_root = _roots(tmp_path)
    _write_events(
        event_root,
        date="2025-10-23",
        asset="AAPL",
        executed=("2025-10-23T13:35:00Z",),
        created=("2025-10-23T13:35:01Z",),
        event_ids=("trade-id-must-not-leak",),
    )
    _write_b2_rows(
        matrix_root,
        date="2025-10-23",
        asset="AAPL",
        rows=1,
        zero=False,
    )

    first = build_uw_anomaly_evidence_v21(
        event_root=event_root,
        matrix_root=matrix_root,
        session_dates=("2025-10-23",),
        raw_assets=("AAPL",),
    )
    second = build_uw_anomaly_evidence_v21(
        event_root=event_root,
        matrix_root=matrix_root,
        session_dates=("2025-10-23",),
        raw_assets=("AAPL",),
    )
    output = tmp_path / "uw_anomaly_evidence_v21.json"

    validate_uw_anomaly_evidence_v21(first)
    digest = write_uw_anomaly_evidence_v21(output_path=output, evidence=first)

    assert first == second
    assert json.loads(output.read_text(encoding="utf-8"))["artifact_sha256"] == digest
    serialized = output.read_text(encoding="utf-8")
    assert str(tmp_path) not in serialized
    assert "D:\\" not in serialized
    assert "trade-id-must-not-leak" not in serialized


def test_individual_row_hash_tampering_fails_after_outer_hash_recomputed(tmp_path: Path) -> None:
    """Internal traceability hashes remain binding even if an outer digest is recomputed."""
    event_root, matrix_root = _roots(tmp_path)
    _write_events(
        event_root,
        date="2025-10-23",
        asset="AAPL",
        executed=("2025-10-23T13:35:00Z",),
        created=("2025-10-23T13:35:01Z",),
    )
    _write_b2_rows(matrix_root, date="2025-10-23", asset="AAPL", rows=1, zero=False)
    evidence = build_uw_anomaly_evidence_v21(
        event_root=event_root,
        matrix_root=matrix_root,
        session_dates=("2025-10-23",),
        raw_assets=("AAPL",),
    )

    tampered = deepcopy(evidence)
    tampered["source_incidents"][0]["source_incident_sha256"] = "0" * 64
    tampered["artifact_sha256"] = canonical_sha256(
        {key: value for key, value in tampered.items() if key != "artifact_sha256"}
    )

    with pytest.raises(ValueError, match="UW_ANOMALY_V21_SOURCE_INCIDENT_HASH_MISMATCH"):
        validate_uw_anomaly_evidence_v21(tampered)


def test_canonical_row_hash_tampering_fails_after_outer_hash_recomputed(tmp_path: Path) -> None:
    """Canonical-row traceability remains binding independently of the outer digest."""
    event_root, matrix_root = _roots(tmp_path)
    _write_events(
        event_root,
        date="2025-10-23",
        asset="AAPL",
        executed=("2025-10-23T13:35:00Z",),
        created=("2025-10-23T13:35:01Z",),
    )
    _write_b2_rows(matrix_root, date="2025-10-23", asset="AAPL", rows=1, zero=False)
    evidence = build_uw_anomaly_evidence_v21(
        event_root=event_root,
        matrix_root=matrix_root,
        session_dates=("2025-10-23",),
        raw_assets=("AAPL",),
    )

    tampered = deepcopy(evidence)
    tampered["canonical_rows"][0]["canonical_row_sha256"] = "0" * 64
    tampered["artifact_sha256"] = canonical_sha256(
        {key: value for key, value in tampered.items() if key != "artifact_sha256"}
    )

    with pytest.raises(ValueError, match="UW_ANOMALY_V21_CANONICAL_ROW_HASH_MISMATCH"):
        validate_uw_anomaly_evidence_v21(tampered)


def test_cli_writes_only_sanitised_target_free_evidence(tmp_path: Path) -> None:
    """The reproducible CLI writes a Schema-valid artifact without raw paths."""
    event_root, matrix_root = _roots(tmp_path)
    _write_events(
        event_root,
        date="2025-10-24",
        asset="AAPL",
        executed=("2025-10-24T13:35:00Z",),
        created=("2025-10-24T13:35:01Z",),
    )
    _write_b2_rows(
        matrix_root,
        date="2025-10-24",
        asset="AAPL",
        rows=1,
        zero=False,
    )
    output = tmp_path / "artifact.json"

    status = main(
        [
            "--event-root",
            str(event_root),
            "--matrix-root",
            str(matrix_root),
            "--output",
            str(output),
            "--session-date",
            "2025-10-24",
            "--asset",
            "AAPL",
        ]
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert status == 0
    assert payload["schema_version"] == "uw-anomaly-evidence-v2.1"
    assert payload["no_provider_http_requests_performed"] is True
    assert str(event_root) not in json.dumps(payload)


def _roots(tmp_path: Path) -> tuple[Path, Path]:
    """Create isolated roots matching the acquired-source directory shape."""
    event_root = tmp_path / "events"
    matrix_root = tmp_path / "b2"
    event_root.mkdir()
    matrix_root.mkdir()
    return event_root, matrix_root


def _write_events(
    root: Path,
    *,
    date: str,
    asset: str,
    executed: tuple[str, ...],
    created: tuple[str, ...],
    event_ids: tuple[str, ...] | None = None,
) -> None:
    """Write a timestamp-only Full Tape fixture plus an ignored identifier column."""
    path = root / f"date={date}" / f"asset={asset}" / "events.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    ids = (
        event_ids
        if event_ids is not None
        else tuple(f"fixture-{index}" for index in range(len(executed)))
    )
    table = pa.table(
        {
            "id": list(ids),
            "executed_at": pa.array(
                [_utc(value) for value in executed], type=pa.timestamp("us", tz="UTC")
            ),
            "created_at": pa.array(
                [_utc(value) for value in created], type=pa.timestamp("us", tz="UTC")
            ),
        }
    )
    pq.write_table(table, path)


def _write_b2_rows(
    root: Path,
    *,
    date: str,
    asset: str,
    rows: int,
    zero: bool,
    missing_feature: str | None = None,
) -> None:
    """Write canonical-shaped B2 fixture rows without targets or market data."""
    path = root / "primary_5m_60s" / f"date={date}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    features: dict[str, list[float | None]] = {}
    for column in B2_FEATURE_COLUMNS:
        values: list[float | None] = [0.0 if zero else 1.0] * rows
        if column == missing_feature:
            values[0] = None
        features[column] = values
    table = pa.table(
        {
            "origin_id": [f"origin-{index}" for index in range(rows)],
            "asset": [asset] * rows,
            "session_date": [date] * rows,
            "forecast_origin_utc": pa.array(
                [_utc(f"{date}T13:35:00Z")] * rows, type=pa.timestamp("us", tz="UTC")
            ),
            "b2v2_cutoff_utc": pa.array(
                [_utc(f"{date}T13:34:00Z")] * rows, type=pa.timestamp("us", tz="UTC")
            ),
            "b2v2_max_created_at_utc": pa.array(
                [None if zero else _utc(f"{date}T13:34:30Z") for _ in range(rows)],
                type=pa.timestamp("us", tz="UTC"),
            ),
            **features,
        }
    )
    pq.write_table(table, path)


def _utc(value: str) -> datetime:
    """Parse a compact UTC fixture timestamp."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
