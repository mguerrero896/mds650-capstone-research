"""Re-entry and allow-list contracts for Phase 6 acquisition."""

from __future__ import annotations

import importlib
import json
import sys
from datetime import date
from pathlib import Path

import pytest

from mds650.phase5_storage import GIB, Phase5StorageConfig
from mds650.study_design import canonical_sha256

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
acquisition = importlib.import_module("acquire_phase6")


def _preregistration() -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "fixture",
        "sessions": [{"session_date": "2025-07-07", "role": "warmup"}],
    }
    payload["manifest_sha256"] = canonical_sha256(payload)
    return payload


def _record(preregistration: dict[str, object]) -> dict[str, object]:
    preregistration_hash = str(preregistration["manifest_sha256"])
    record: dict[str, object] = {
        "status": "PASS",
        "session_date": "2025-07-07",
        "preregistration_sha256": preregistration_hash,
        "session_contract_sha256": canonical_sha256(
            {
                "session_date": "2025-07-07",
                "preregistration_sha256": preregistration_hash,
            }
        ),
        "raw_sha256": "a" * 64,
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
    }
    record["checkpoint_sha256"] = canonical_sha256(record)
    return record


def test_pending_sessions_reuses_only_matching_hashes() -> None:
    preregistration = _preregistration()
    record = _record(preregistration)
    manifest = {"sessions": [record]}

    assert acquisition.pending_sessions(preregistration, manifest) == []

    record["raw_sha256"] = "b" * 64
    assert acquisition.pending_sessions(preregistration, manifest) == ["2025-07-07"]


def test_pending_sessions_rejects_duplicate_date() -> None:
    preregistration = _preregistration()
    record = _record(preregistration)

    with pytest.raises(RuntimeError, match="PHASE6_ACQUISITION_DUPLICATE"):
        acquisition.pending_sessions(preregistration, {"sessions": [record, record]})


def test_acquisition_rejects_date_outside_allowlist(tmp_path: Path) -> None:
    config = Phase5StorageConfig(
        sessions=(date(2025, 7, 7),),
        excluded_dates=frozenset(),
        data_root=tmp_path,
        minimum_free_bytes=80 * GIB,
        projected_peak_additional_bytes=1,
    )

    with pytest.raises(ValueError, match="PHASE6_SESSION_NOT_AUTHORIZED"):
        acquisition.acquire_session("2025-07-04", config)


def test_acquire_session_is_idempotent_after_verified_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preregistration = _preregistration()
    prereg_path = tmp_path / "preregistration.json"
    prereg_path.write_text(json.dumps(preregistration), encoding="utf-8")
    checkpoints = tmp_path / "checkpoints"
    calls = {"downloads": 0}

    def fake_download(day: date, _key: str, destination: Path) -> dict[str, object]:
        calls["downloads"] += 1
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"immutable-fixture")
        return {
            "http_status": 200,
            "attempts": 1,
            "download_seconds": 0.01,
            "bytes": destination.stat().st_size,
            "sha256": acquisition.sha256_file(destination),
            "endpoint": "SANITIZED_FULL_TAPE_ENDPOINT",
            "request_id": "fixture",
        }

    def fake_filter(
        day: date,
        _zip_path: Path,
        _fields: set[str] | None,
        config: Phase5StorageConfig,
    ) -> dict[str, object]:
        target = (
            config.event_root
            / f"date={day.isoformat()}"
            / "asset=AAPL"
            / "events.parquet"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"parquet-fixture")
        return {
            "session_date": day.isoformat(),
            "schema_fields": ["created_at", "id"],
            "rows_seen": 1,
            "rows_retained": 1,
            "parquet_bytes": target.stat().st_size,
        }

    monkeypatch.setattr(acquisition, "PREREGISTRATION", prereg_path)
    monkeypatch.setattr(acquisition, "CHECKPOINT_ROOT", checkpoints)
    monkeypatch.setattr(acquisition.downloader, "_stream_download", fake_download)
    monkeypatch.setattr(acquisition.downloader, "filter_session", fake_filter)
    monkeypatch.setattr(
        acquisition.downloader, "_secret", lambda _name: "fixture-secret"
    )
    monkeypatch.setattr(acquisition, "storage_preflight", lambda _config: {})
    config = Phase5StorageConfig(
        sessions=(date(2025, 7, 7),),
        excluded_dates=frozenset(),
        data_root=tmp_path / "data",
        minimum_free_bytes=80 * GIB,
        projected_peak_additional_bytes=1,
    )
    config.data_root.mkdir()

    first = acquisition.acquire_session("2025-07-07", config)
    second = acquisition.acquire_session("2025-07-07", config)

    assert first["status"] == second["status"] == "PASS"
    assert first["checkpoint_sha256"] == second["checkpoint_sha256"]
    assert second["reused_existing"] is True
    assert calls["downloads"] == 1
