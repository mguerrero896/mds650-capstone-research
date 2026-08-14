"""Target-blind resumability contracts for the B1v3 Full Tape acquisition."""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pytest

from mds650.b1v3_confirmation import canonical_sha256
from mds650.phase5_storage import GIB, Phase5StorageConfig

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import acquire_b1v3_confirmation_full_tape as acquisition  # noqa: E402


def _plan() -> dict[str, object]:
    plan: dict[str, object] = {
        "status": "PASS_PRISTINE_60_30_FROZEN",
        "target_blind": True,
        "safe_to_acquire": True,
        "safe_to_read_outcomes": False,
        "outcome_read_count": 0,
        "training_sessions": ["2024-08-02"],
        "confirmation_sessions": ["2024-08-05"],
    }
    plan["plan_sha256"] = canonical_sha256(plan)
    return plan


def _checkpoint(plan: dict[str, object]) -> dict[str, object]:
    plan_hash = str(plan["plan_sha256"])
    record: dict[str, object] = {
        "status": "PASS",
        "session_date": "2024-08-02",
        "source_kind": "AUTHENTICATED_DOWNLOAD",
        "confirmation_plan_sha256": plan_hash,
        "session_contract_sha256": acquisition.session_contract_sha256(
            "2024-08-02", plan_hash
        ),
        "raw_sha256": "a" * 64,
        "raw_bytes": 1,
        "parquet_files": [
            {
                "relative_path": (
                    "data/option_events/date=2024-08-02/asset=AAPL/events.parquet"
                ),
                "bytes": 1,
                "sha256": "b" * 64,
            }
        ],
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
        "target_outcome_read": False,
        "oos_read_count": 0,
    }
    record["checkpoint_sha256"] = canonical_sha256(record)
    return record


def test_pending_sessions_accepts_only_plan_bound_self_hashed_checkpoints() -> None:
    plan = _plan()
    record = _checkpoint(plan)

    assert acquisition.pending_sessions(plan, [record]) == ["2024-08-05"]
    record["raw_bytes"] = 2
    assert acquisition.pending_sessions(plan, [record]) == [
        "2024-08-02",
        "2024-08-05",
    ]


def test_pending_sessions_rejects_duplicate_checkpoint_date() -> None:
    plan = _plan()
    record = _checkpoint(plan)

    with pytest.raises(RuntimeError, match="B1V3_ACQUISITION_DUPLICATE_CHECKPOINT"):
        acquisition.pending_sessions(plan, [record, record])


def test_acquire_session_is_resumable_after_verified_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan()
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    calls = {"downloads": 0}

    def fake_download(day: date, _key: str, destination: Path) -> dict[str, object]:
        calls["downloads"] += 1
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"immutable-zip")
        return {
            "http_status": 200,
            "attempts": 1,
            "download_seconds": 0.01,
            "bytes": destination.stat().st_size,
            "sha256": acquisition.sha256_file(destination),
            "request_id": "fixture",
        }

    def fake_filter(
        day: date,
        _zip_path: Path,
        _expected_fields: set[str] | None,
        config: Phase5StorageConfig,
    ) -> dict[str, object]:
        target = (
            config.event_root
            / f"date={day.isoformat()}"
            / "asset=AAPL"
            / "events.parquet"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"parquet")
        return {
            "schema_fields": ["created_at", "id"],
            "schema_fingerprint": "c" * 64,
            "rows_seen": 1,
            "rows_retained": 1,
            "duplicate_event_ids": 0,
            "parquet_bytes": target.stat().st_size,
            "filter_seconds": 0.01,
        }

    monkeypatch.setattr(acquisition, "PLAN_PATH", plan_path)
    monkeypatch.setattr(acquisition, "CHECKPOINT_ROOT", tmp_path / "checkpoints")
    monkeypatch.setattr(acquisition.downloader, "_stream_download", fake_download)
    monkeypatch.setattr(acquisition.downloader, "filter_session", fake_filter)
    monkeypatch.setattr(acquisition.downloader, "_secret", lambda _name: "fixture")
    monkeypatch.setattr(acquisition, "storage_preflight", lambda _config: {})
    config = Phase5StorageConfig(
        sessions=(date(2024, 8, 2),),
        excluded_dates=frozenset(),
        data_root=tmp_path / "data",
        minimum_free_bytes=80 * GIB,
        projected_peak_additional_bytes=1,
    )
    config.data_root.mkdir()

    first = acquisition.acquire_session("2024-08-02", config)
    second = acquisition.acquire_session("2024-08-02", config)

    assert first["checkpoint_sha256"] == second["checkpoint_sha256"]
    assert second["reused_existing"] is True
    assert calls["downloads"] == 1


def test_cli_requires_explicit_resume_flag() -> None:
    with pytest.raises(SystemExit, match="0"):
        acquisition.main(["--help"])
