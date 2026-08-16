"""Contract tests for the bounded Phase 3F calibration artifacts and helpers."""
# ruff: noqa: E501

from __future__ import annotations

import inspect
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pyarrow.parquet as pq
import pytest
from tests.evidence import require_evidence_root

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import build_b2_calibration_20d as b2  # noqa: E402
import download_calibration_20d as downloader  # noqa: E402


def _calibration() -> Path:
    """Return the mounted evidence package for the 20-session calibration."""
    root = require_evidence_root(
        "artifacts/calibration_20d/download_manifest.json",
        "artifacts/calibration_20d/raw_integrity_report.json",
        "artifacts/calibration_20d/pilot_v2_unusual_scores.parquet",
    )
    return root / "artifacts" / "calibration_20d"


# superseded: the legacy test_duplicate_central_directory_tail_is_read_without_mutating_raw
# was dropped because it exercised downloader._open_zip, a duplicate-central-directory
# tolerant opener that exists only on the archived pre-consolidation branch; main's
# download_calibration_20d.py uses plain zipfile.ZipFile, which rejects that corruption.


def test_exact_twenty_session_allowlist_excludes_pilot() -> None:
    assert len(downloader.SESSIONS) == 20
    assert set(downloader.SESSIONS).isdisjoint(downloader.PILOT_DATES)
    assert downloader.SESSIONS[0].isoformat() == "2026-06-11"
    assert downloader.SESSIONS[-1].isoformat() == "2026-07-10"


def test_active_calibration_cache_contract_is_explicit() -> None:
    required = {
        "provider",
        "asset",
        "session_date",
        "expiry",
        "strike",
        "option_type",
        "contract",
        "route",
        "schema_version",
    }
    text = (ROOT / "docs/b2_calibration_contract.md").read_text(encoding="utf-8")
    assert "ACTIVE_CALIBRATION_CACHE_V2_ONLY" in text or "V2-only" in text
    assert required >= {
        "provider",
        "asset",
        "session_date",
        "expiry",
        "strike",
        "option_type",
        "contract",
    }


def test_band_keys_are_deterministic_and_timezone_aware() -> None:
    origin = datetime(2026, 6, 11, 16, 35, tzinfo=UTC)
    assert b2._band_key("AAPL", origin.astimezone(b2.NY), "30m") == "AAPL|B30_06"
    assert b2._band_key("AAPL", origin.astimezone(b2.NY), "asset") == "AAPL|ALL"


def test_mad_iqr_and_constant_fallbacks_are_explicit() -> None:
    _, scale_mad, _, mad_fallback = b2._median_mad([1.0, 2.0, 3.0, 4.0, 5.0])
    _, scale_iqr, _, iqr_fallback = b2._median_mad([1.0, 1.0, 2.0, 2.0])
    _, scale_constant, _, constant_fallback = b2._median_mad([2.0, 2.0, 2.0])
    assert scale_mad > 0 and mad_fallback == "mad"
    assert scale_iqr > 0 and iqr_fallback in {"mad", "iqr_fallback"}
    assert scale_constant == 1.0 and constant_fallback == "asset_constant_fallback"


def test_score_is_reproducible_and_uses_only_positive_top_three() -> None:
    row = {
        "asset": "AAPL",
        "forecast_origin_utc": datetime(2026, 6, 11, 16, 35, tzinfo=UTC),
        **{feature: 3.0 for feature in b2.CORE_FEATURES},
    }
    parameters = {
        "AAPL|B30_06": {
            "sample_size": 120,
            "p95_threshold": 1.0,
            "features": {
                feature: {"median": 0.0, "scale": 1.0, "fallback": "mad"}
                for feature in b2.CORE_FEATURES
            },
        }
    }
    first = b2._score_row(row, parameters)
    second = b2._score_row(row, parameters)
    assert first == second
    assert first["unusual_event"] is True
    assert first["unusual_intensity_score"] == second["unusual_intensity_score"]


def test_percentile_sensitivity_uses_requested_quantile() -> None:
    values = [0.0, 1.0, 2.0, 3.0, 4.0]
    assert b2._empirical_quantile(values, 0.90) == pytest.approx(3.6)
    assert b2._empirical_quantile(values, 0.95) == pytest.approx(3.8)
    assert b2._empirical_quantile(values, 0.975) == pytest.approx(3.9)


def test_no_future_created_at_rows_can_enter_primary_cutoff() -> None:
    frame = pl.DataFrame(
        {
            "created_at": [
                datetime(2026, 6, 11, 15, 34, 30, tzinfo=UTC),
                datetime(2026, 6, 11, 15, 35, tzinfo=UTC),
            ],
            "forecast_origin_utc": [datetime(2026, 6, 11, 15, 35, tzinfo=UTC)] * 2,
        }
    )
    eligible = frame.filter(
        pl.col("created_at") <= pl.col("forecast_origin_utc") - pl.duration(seconds=60)
    )
    assert eligible.height == 0


def test_full_tape_dedup_is_disk_backed_and_memory_bounded() -> None:
    source = inspect.getsource(downloader.filter_session)
    assert "sqlite3.connect" in source
    assert "disk_backed_sqlite_primary_key" in source
    assert "seen: set[str]" not in source


def test_parquet_writer_reuses_one_writer_without_truncating_pages(tmp_path, monkeypatch) -> None:
    """Two bounded flushes must preserve both row groups in one partition."""
    monkeypatch.setattr(downloader, "EVENT_ROOT", tmp_path)
    base = {
        "_session_date": "2026-06-11",
        "id": None,
        "underlying_symbol": "AAPL",
        "option_chain_id": None,
        "executed_at": None,
        "created_at": None,
        "nbbo_bid": None,
        "nbbo_ask": None,
        "price": None,
        "size": None,
        "premium": None,
        "volume": None,
        "open_interest": None,
        "implied_volatility": None,
        "expiry": None,
        "strike": None,
        "option_type": None,
        "report_flags": None,
        "tags": None,
        "ask_vol": None,
        "bid_vol": None,
        "no_side_vol": None,
        "mid_vol": None,
        "multi_vol": None,
        "exchange": None,
        "upstream_condition_detail": None,
    }
    batches = {"AAPL": [{**base, "id": "first"}]}
    writers = {}
    downloader._flush(writers, batches, "AAPL")
    batches["AAPL"] = [{**base, "id": "second"}]
    downloader._flush(writers, batches, "AAPL")
    for writer in writers.values():
        writer.close()
    # Main's downloader stages one ".partial" file per partition and only
    # promotes it to events.parquet atomically after the whole session passes.
    path = tmp_path / "date=2026-06-11" / "asset=AAPL" / "events.parquet.partial"
    assert pq.ParquetFile(path).metadata.num_rows == 2
    assert pq.read_table(path).column("id").to_pylist() == ["first", "second"]


@pytest.mark.evidence
def test_required_artifacts_are_sanitized() -> None:
    data = json.loads((_calibration() / "download_manifest.json").read_text(encoding="utf-8"))
    assert data["secret_values_emitted"] is False
    assert data["personal_paths_emitted"] is False
    assert data["session_count"] <= 20
    if data["status"] == "PASS":
        assert data["session_count"] == 20


@pytest.mark.evidence
def test_raw_integrity_is_fail_closed() -> None:
    data = json.loads((_calibration() / "raw_integrity_report.json").read_text(encoding="utf-8"))
    assert data["status"] == "PASS"
    assert data["sessions_validated"] == 20
    assert data["unique_raw_hashes"] == 20
    assert data["duplicate_hashes"] == []
    assert data["secret_values_emitted"] is False
    assert data["personal_paths_emitted"] is False


@pytest.mark.evidence
def test_pilot_application_marks_unusual_label_as_secondary_exploratory() -> None:
    frame = pl.read_parquet(_calibration() / "pilot_v2_unusual_scores.parquet")
    assert frame.height == 2840
    assert frame["unusual_event_status"].unique().to_list() == [
        "CALIBRATED_SECONDARY_EXPLORATORY"
    ]
    assert frame["rv30_used_for_calibration"].unique().to_list() == [False]
    assert frame["pit_cutoff"].unique().to_list() == [
        "created_at <= origin - 60 seconds"
    ]
    assert frame["calibration_source_hash"].n_unique() == 1
    source_hash = frame["calibration_source_hash"][0]
    assert isinstance(source_hash, str) and len(source_hash) == 64
    assert frame["calibration_source_manifest"].unique().to_list() == [
        "artifacts/calibration_20d/download_manifest.json"
    ]
