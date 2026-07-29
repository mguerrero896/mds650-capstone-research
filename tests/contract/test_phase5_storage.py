"""Fail-closed storage and reuse contracts for Phase 5."""

from __future__ import annotations

import importlib
import json
import sys
from collections import namedtuple
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SESSION_MANIFEST = ROOT / "artifacts" / "phase5" / "study_sessions_90.json"
REUSED_MANIFEST = ROOT / "artifacts" / "phase5" / "reused_25_session_manifest.json"
GIB = 1024**3
sys.path.insert(0, str(ROOT / "scripts"))
import build_b2_calibration_20d as b2_builder  # noqa: E402
import download_calibration_20d as downloader  # noqa: E402
import run_b1_calibration_20d as b1_builder  # noqa: E402


def _storage() -> object:
    return importlib.import_module("mds650.phase5_storage")


def test_build_config_selects_only_55_missing_development_sessions() -> None:
    manifest = json.loads(SESSION_MANIFEST.read_text(encoding="utf-8"))
    development = [date.fromisoformat(value) for value in manifest["development"]]
    reused = frozenset(development[-25:])

    config = _storage().build_phase5_storage_config(
        manifest,
        reused_dates=reused,
        data_root=Path("D:/MDS650"),
        projected_peak_additional_bytes=100 * GIB,
    )

    assert len(config.sessions) == 55
    assert config.sessions[0] == date(2026, 3, 24)
    assert config.sessions[-1] == date(2026, 6, 10)
    assert set(config.sessions).isdisjoint(config.excluded_dates)
    assert config.raw_root == Path("D:/MDS650/raw/full_tape")
    assert config.manifest_root == Path("D:/MDS650/manifests/full_tape")


def test_build_holdout_config_selects_exact_ten_sessions() -> None:
    manifest = json.loads(SESSION_MANIFEST.read_text(encoding="utf-8"))

    config = _storage().build_phase5_holdout_storage_config(
        manifest,
        data_root=Path("D:/MDS650/data/phase5_holdout"),
        projected_peak_additional_bytes=20 * GIB,
    )

    assert tuple(day.isoformat() for day in config.sessions) == tuple(
        manifest["holdout"]
    )
    assert config.excluded_dates == frozenset(
        date.fromisoformat(value) for value in manifest["development"]
    )
    assert config.raw_root == Path(
        "D:/MDS650/data/phase5_holdout/raw/full_tape"
    )
    assert config.event_root == Path(
        "D:/MDS650/data/phase5_holdout/data/option_events"
    )


def test_build_holdout_config_rejects_manifest_hash_mismatch() -> None:
    manifest = json.loads(SESSION_MANIFEST.read_text(encoding="utf-8"))
    manifest["holdout_count"] = 9

    with pytest.raises(ValueError, match="SESSION_MANIFEST_HASH_MISMATCH"):
        _storage().build_phase5_holdout_storage_config(
            manifest,
            data_root=Path("D:/MDS650/data/phase5_holdout"),
            projected_peak_additional_bytes=20 * GIB,
        )


def test_downloader_loads_exact_missing_development_allowlist(tmp_path: Path) -> None:
    config = downloader.load_phase5_development_config(
        session_manifest_path=SESSION_MANIFEST,
        reused_manifest_path=REUSED_MANIFEST,
        output_root=tmp_path,
        projected_peak_additional_bytes=150 * GIB,
    )

    assert len(config.sessions) == 55
    assert config.sessions[0] == date(2026, 3, 24)
    assert config.sessions[-1] == date(2026, 6, 10)
    assert config.data_root == tmp_path
    assert set(config.sessions).isdisjoint(config.excluded_dates)


def test_downloader_loads_exact_holdout_allowlist(tmp_path: Path) -> None:
    config = downloader.load_phase5_holdout_config(
        session_manifest_path=SESSION_MANIFEST,
        output_root=tmp_path,
        projected_peak_additional_bytes=20 * GIB,
    )

    assert len(config.sessions) == 10
    assert config.sessions[0] == date(2026, 7, 20)
    assert config.sessions[-1] == date(2026, 7, 31)
    assert config.data_root == tmp_path
    assert set(config.sessions).isdisjoint(config.excluded_dates)


def test_downloader_rejects_untrusted_reused_manifest(tmp_path: Path) -> None:
    reused = json.loads(REUSED_MANIFEST.read_text(encoding="utf-8"))
    reused["status"] = "FAIL"
    tampered = tmp_path / "reused.json"
    tampered.write_text(json.dumps(reused), encoding="utf-8")

    with pytest.raises(ValueError, match="REUSED_SESSION_MANIFEST_NOT_PASS"):
        downloader.load_phase5_development_config(
            session_manifest_path=SESSION_MANIFEST,
            reused_manifest_path=tampered,
            output_root=tmp_path,
            projected_peak_additional_bytes=150 * GIB,
        )


def test_downloader_rejects_reused_manifest_hash_mismatch(tmp_path: Path) -> None:
    reused = json.loads(REUSED_MANIFEST.read_text(encoding="utf-8"))
    reused["source_preserved"] = False
    tampered = tmp_path / "reused.json"
    tampered.write_text(json.dumps(reused), encoding="utf-8")

    with pytest.raises(ValueError, match="REUSED_SESSION_MANIFEST_HASH_MISMATCH"):
        downloader.load_phase5_development_config(
            session_manifest_path=SESSION_MANIFEST,
            reused_manifest_path=tampered,
            output_root=tmp_path,
            projected_peak_additional_bytes=150 * GIB,
        )


def test_storage_config_rejects_holdout_date() -> None:
    with pytest.raises(ValueError, match="HOLDOUT_DATE_IN_SESSION_ALLOWLIST"):
        _storage().Phase5StorageConfig(
            sessions=(date(2026, 7, 20),),
            excluded_dates=frozenset({date(2026, 7, 20)}),
            data_root=Path("D:/MDS650"),
            minimum_free_bytes=80 * GIB,
            projected_peak_additional_bytes=1,
        )


def test_storage_config_rejects_floor_below_80_gib() -> None:
    with pytest.raises(ValueError, match="MINIMUM_FREE_SPACE_BELOW_80_GIB"):
        _storage().Phase5StorageConfig(
            sessions=(date(2026, 3, 24),),
            excluded_dates=frozenset(),
            data_root=Path("D:/MDS650"),
            minimum_free_bytes=79 * GIB,
            projected_peak_additional_bytes=1,
        )


def test_storage_preflight_probes_write_and_peak_floor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(
        _storage().shutil,
        "disk_usage",
        lambda _path: usage(500 * GIB, 200 * GIB, 300 * GIB),
    )
    config = _storage().Phase5StorageConfig(
        sessions=(date(2026, 3, 24),),
        excluded_dates=frozenset(),
        data_root=tmp_path,
        minimum_free_bytes=80 * GIB,
        projected_peak_additional_bytes=100 * GIB,
    )

    evidence = _storage().storage_preflight(config)

    assert evidence["write_probe_pass"] is True
    assert evidence["projected_minimum_free_bytes"] == 200 * GIB
    assert evidence["free_space_pass"] is True
    assert evidence["data_root"] == "MDS650_DATA_ROOT"


def test_storage_preflight_fails_before_peak_below_floor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(
        _storage().shutil,
        "disk_usage",
        lambda _path: usage(500 * GIB, 350 * GIB, 150 * GIB),
    )
    config = _storage().Phase5StorageConfig(
        sessions=(date(2026, 3, 24),),
        excluded_dates=frozenset(),
        data_root=tmp_path,
        minimum_free_bytes=80 * GIB,
        projected_peak_additional_bytes=80 * GIB,
    )

    with pytest.raises(RuntimeError, match="PROJECTED_MINIMUM_FREE_SPACE_BELOW_FLOOR"):
        _storage().storage_preflight(config)


def test_reusable_session_requires_matching_raw_hash(tmp_path: Path) -> None:
    raw = tmp_path / "full_tape.zip"
    manifest = tmp_path / "session.json"
    raw.write_bytes(b"immutable-provider-evidence")
    expected = _storage().sha256_file(raw)
    manifest.write_text(
        json.dumps({"status": "PASS", "sha256": expected}),
        encoding="utf-8",
    )

    assert _storage().verify_reusable_session(raw, manifest, expected) is True
    raw.write_bytes(b"changed")
    with pytest.raises(RuntimeError, match="REUSABLE_RAW_HASH_MISMATCH"):
        _storage().verify_reusable_session(raw, manifest, expected)


def test_downloader_rejects_date_outside_explicit_config(tmp_path: Path) -> None:
    config = _storage().Phase5StorageConfig(
        sessions=(date(2026, 3, 24),),
        excluded_dates=frozenset(),
        data_root=tmp_path,
        minimum_free_bytes=80 * GIB,
        projected_peak_additional_bytes=1,
    )

    with pytest.raises(RuntimeError, match="SESSION_NOT_IN_EXPLICIT_ALLOWLIST"):
        downloader.filter_session(
            date(2026, 3, 25),
            tmp_path / "not-opened.zip",
            None,
            config,
        )


def test_b1_and_b2_builders_expose_explicit_roots_and_allowlists(tmp_path: Path) -> None:
    sessions = (date(2026, 3, 24), date(2026, 3, 25))
    b2_config = b2_builder.B2BuildConfig(
        output_root=tmp_path / "b2",
        event_root=tmp_path / "events",
        download_manifest=tmp_path / "batch.json",
        sessions=sessions,
    )
    b1_config = b1_builder.B1BuildConfig(
        output_root=tmp_path / "b1",
        cache_root=tmp_path / "massive",
        sessions=tuple(day.isoformat() for day in sessions),
    )

    assert b2_config.sessions == sessions
    assert b2_config.event_root == tmp_path / "events"
    assert b1_config.sessions == ("2026-03-24", "2026-03-25")
    assert b1_config.cache_root == tmp_path / "massive"


def test_verified_copy_is_idempotent_and_hash_addressed(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    destination = tmp_path / "nested" / "destination.bin"
    source.write_bytes(b"retained-evidence")
    expected = _storage().sha256_file(source)

    first = _storage().copy_verified_file(source, destination, expected)
    second = _storage().copy_verified_file(source, destination, expected)

    assert first["status"] == "COPIED_AND_VERIFIED"
    assert second["status"] == "REUSED_VERIFIED_DESTINATION"
    assert first["sha256"] == second["sha256"] == expected
    assert destination.read_bytes() == source.read_bytes()


def test_verified_copy_rejects_untrusted_source_hash(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"unexpected")

    with pytest.raises(RuntimeError, match="SOURCE_HASH_MISMATCH"):
        _storage().copy_verified_file(source, tmp_path / "destination.bin", "0" * 64)
