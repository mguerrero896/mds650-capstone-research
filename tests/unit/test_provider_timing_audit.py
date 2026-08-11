"""Unit coverage for the historical Unusual Whales timing audit."""

from __future__ import annotations

import importlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from mds650.provider_timing import (
    HISTORICAL_UW_CLASSIFICATION,
    audit_uw_full_tape,
    summarize_latency_seconds,
)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
audit_script = importlib.import_module("audit_provider_timing")


def test_latency_summary_tracks_completeness_negative_values_and_cutoffs() -> None:
    """The latency summary keeps missingness separate from valid observations."""
    summary = summarize_latency_seconds(
        row_count=9,
        created_at_non_null_count=8,
        executed_at_non_null_count=8,
        latency_seconds=(-1.0, 0.0, 1.0, 5.0, 61.0, 120.0, 300.0),
        percentile_method="exact_fixture",
    )

    assert summary["created_at_missing_count"] == 1
    assert summary["executed_at_missing_count"] == 1
    assert summary["both_timestamps_count"] == 7
    assert summary["negative_latency_count"] == 1
    assert summary["latency_p50_seconds"] == 5.0
    assert summary["latency_within_60_seconds_count"] == 4
    assert summary["latency_within_120_seconds_count"] == 6
    assert summary["latency_within_300_seconds_count"] == 7
    assert summary["percentile_method"] == "exact_fixture"


def test_historical_audit_is_deterministic_and_does_not_emit_physical_paths(
    tmp_path: Path,
) -> None:
    """A local Full Tape replay produces a stable, sanitized audit payload."""
    root = tmp_path / "phase6" / "data" / "option_events"
    _write_events(
        root / "date=2025-07-07" / "asset=AAPL" / "events.parquet",
        created=("2025-07-07T14:30:01Z", "2025-07-07T14:31:04Z"),
        executed=("2025-07-07T14:30:00Z", "2025-07-07T14:31:00Z"),
    )
    _write_events(
        root / "date=2025-07-07" / "asset=MSFT" / "events.parquet",
        created=("2025-07-07T14:30:00Z", None),
        executed=("2025-07-07T14:30:01Z", "2025-07-07T14:31:00Z"),
    )

    first = audit_uw_full_tape({"phase6": root}, sample_size=100, batch_size=2)
    second = audit_uw_full_tape({"phase6": root}, sample_size=100, batch_size=2)

    assert first.payload == second.payload
    assert first.payload["historical_uw_classification"] == HISTORICAL_UW_CLASSIFICATION
    assert first.payload["global"]["negative_latency_count"] == 1
    assert first.payload["global"]["created_at_missing_count"] == 1
    assert len(first.by_session) == 1
    assert len(first.by_asset) == 2
    assert str(tmp_path) not in str(first.payload)


def test_offline_audit_cli_writes_all_required_sanitized_artifacts(tmp_path: Path) -> None:
    """The offline command writes the JSON and three required CSV outputs."""
    phase6 = tmp_path / "phase6" / "data" / "option_events"
    independent = tmp_path / "independent" / "data" / "option_events"
    _write_events(
        phase6 / "date=2025-07-07" / "asset=AAPL" / "events.parquet",
        created=("2025-07-07T14:30:01Z",),
        executed=("2025-07-07T14:30:00Z",),
    )
    _write_events(
        independent / "date=2025-02-25" / "asset=MSFT" / "events.parquet",
        created=("2025-02-25T14:30:01Z",),
        executed=("2025-02-25T14:30:00Z",),
    )
    output = tmp_path / "output"

    assert audit_script.main(
        [
            "--phase6-event-root",
            str(phase6),
            "--independent-event-root",
            str(independent),
            "--output-dir",
            str(output),
            "--sample-size",
            "20",
            "--batch-size",
            "2",
        ]
    ) == 0

    manifest = json.loads(
        (output / "provider_timing_semantics_audit_v1.json").read_text(encoding="utf-8")
    )
    assert manifest["no_provider_http_requests_performed"] is True
    assert str(tmp_path) not in json.dumps(manifest, sort_keys=True)
    assert (output / "uw_historical_latency_summary.csv").is_file()
    assert (output / "uw_historical_latency_by_session.csv").is_file()
    assert (output / "uw_historical_latency_by_asset.csv").is_file()


def test_offline_audit_defaults_to_full_tape_bulk_root_not_panel_data_root() -> None:
    """The auditor never reuses the legacy panel-data root for Full Tape files."""
    args = audit_script.parse_args([])

    assert args.phase6_event_root == Path(r"D:\MDS650\phase6\data\option_events")
    assert args.independent_event_root == Path(
        r"D:\MDS650\independent_replication_30\data\option_events"
    )


def _write_events(
    path: Path,
    *,
    created: tuple[str | None, ...],
    executed: tuple[str | None, ...],
) -> None:
    """Write a minimal UTC Full Tape fixture."""
    path.parent.mkdir(parents=True, exist_ok=True)
    created_values = [_parse_timestamp(value) for value in created]
    executed_values = [_parse_timestamp(value) for value in executed]
    table = pa.table(
        {
            "created_at": pa.array(created_values, type=pa.timestamp("us", tz="UTC")),
            "executed_at": pa.array(executed_values, type=pa.timestamp("us", tz="UTC")),
        }
    )
    pq.write_table(table, path)


def _parse_timestamp(value: str | None) -> datetime | None:
    """Parse a compact ISO UTC fixture timestamp."""
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
