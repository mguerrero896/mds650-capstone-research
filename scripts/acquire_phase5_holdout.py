"""Acquire and seal the prospective Phase 5 holdout without analysing outcomes."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import build_b2_calibration_20d as b2_builder
import build_phase5_common_panel as panel_builder
import build_phase5_stability_inputs as stability_builder
import download_calibration_20d as downloader
import polars as pl
import run_b1_calibration_20d as b1_builder
import run_phase5_holdout as holdout_runner

from mds650.holdout import (
    EXPECTED_HOLDOUT_SESSIONS,
    HOLDOUT_PERIOD_COMPLETE_UTC,
)
from mds650.study_design import canonical_sha256

ROOT = Path(__file__).resolve().parents[1]
PHASE5 = ROOT / "artifacts" / "phase5"
DEFAULT_DATA_ROOT = Path("D:/MDS650/data/phase5_holdout")
DEFAULT_SESSION_MANIFEST = PHASE5 / "study_sessions_90.json"
DEFAULT_METHOD_FREEZE = PHASE5 / "method_freeze.json"
DEFAULT_ACCESS_LEDGER = PHASE5 / "holdout_access_ledger.json"
DEFAULT_ACQUISITION_MANIFEST = PHASE5 / "holdout_acquisition_manifest.json"
DEFAULT_TEST_REPORT = PHASE5 / "holdout_pre_read_test_report.txt"
SHA256_LENGTH = 64


@dataclass(frozen=True)
class HoldoutAcquisitionConfig:
    """Explicit isolated roots for the ten-session holdout acquisition."""

    data_root: Path = DEFAULT_DATA_ROOT
    session_manifest: Path = DEFAULT_SESSION_MANIFEST
    method_freeze: Path = DEFAULT_METHOD_FREEZE
    access_ledger: Path = DEFAULT_ACCESS_LEDGER
    acquisition_manifest: Path = DEFAULT_ACQUISITION_MANIFEST
    test_report: Path = DEFAULT_TEST_REPORT
    projected_peak_additional_bytes: int = 30 * 1024**3

    @property
    def fmp_root(self) -> Path:
        """Return the isolated FMP build root."""
        return self.data_root / "fmp"

    @property
    def b1_root(self) -> Path:
        """Return the isolated B1Q build root."""
        return self.data_root / "b1q"

    @property
    def b1_cache_root(self) -> Path:
        """Return the resumable Massive contract-day cache root."""
        return self.data_root / "cache" / "massive"

    @property
    def panel_path(self) -> Path:
        """Return the sealed common holdout panel path."""
        return self.data_root / "common_holdout_10d.parquet"

    @property
    def stability_path(self) -> Path:
        """Return the sealed target-blind timing sidecar path."""
        return self.data_root / "holdout_stability_inputs_10d.parquet"


DEFAULT_CONFIG = HoldoutAcquisitionConfig()


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"HOLDOUT_JSON_OBJECT_REQUIRED:{path.name}")
    return payload


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _self_hash_valid(payload: Mapping[str, Any]) -> bool:
    expected = payload.get("manifest_sha256")
    unsigned = {
        key: value for key, value in payload.items() if key != "manifest_sha256"
    }
    return isinstance(expected, str) and expected == canonical_sha256(unsigned)


def _valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == SHA256_LENGTH
        and all(character in "0123456789abcdef" for character in value)
    )


def validate_acquisition_authority(
    session_manifest: Mapping[str, Any],
    method_freeze: Mapping[str, Any],
    now_utc: datetime,
) -> None:
    """Fail before any network call unless the frozen holdout is releasable."""
    if now_utc.tzinfo is None or now_utc.utcoffset() is None:
        raise ValueError("HOLDOUT_NOW_MUST_BE_TIMEZONE_AWARE")
    if now_utc.astimezone(UTC) < HOLDOUT_PERIOD_COMPLETE_UTC:
        raise PermissionError("HOLDOUT_PERIOD_INCOMPLETE")
    if not _self_hash_valid(session_manifest):
        raise PermissionError("SESSION_MANIFEST_SELF_HASH_INVALID")
    if list(session_manifest.get("holdout", ())) != list(
        EXPECTED_HOLDOUT_SESSIONS
    ):
        raise PermissionError("HOLDOUT_SESSION_SET_MISMATCH")
    if (
        session_manifest.get("development_count") != 80
        or session_manifest.get("holdout_count") != 10
        or set(session_manifest.get("development", ()))
        & set(session_manifest.get("holdout", ()))
    ):
        raise PermissionError("STUDY_SESSION_PARTITION_INVALID")
    if not _self_hash_valid(method_freeze):
        raise PermissionError("METHOD_FREEZE_SELF_HASH_INVALID")
    if (
        method_freeze.get("status")
        != "FROZEN_AFTER_DEVELOPMENT_BEFORE_HOLDOUT"
        or method_freeze.get("holdout_reads") != 0
        or not method_freeze.get("holdout_hyperparameters")
    ):
        raise PermissionError("METHOD_FREEZE_INVALID")


def build_holdout_access_ledger(
    *,
    session_manifest: Mapping[str, Any],
    method_freeze: Mapping[str, Any],
    session_statuses: Sequence[Mapping[str, Any]],
    panel_sha256: str,
    stability_panel_sha256: str,
    acquisition_manifest_sha256: str,
    release_gates: Mapping[str, bool],
    acquired_at_utc: datetime,
) -> dict[str, Any]:
    """Build the unread, self-hashed ledger consumed by the sole model run."""
    validate_acquisition_authority(
        session_manifest,
        method_freeze,
        acquired_at_utc,
    )
    statuses = [dict(row) for row in session_statuses]
    if (
        [row.get("session_date") for row in statuses]
        != list(EXPECTED_HOLDOUT_SESSIONS)
        or any(row.get("status") != "PASS" for row in statuses)
    ):
        raise ValueError("HOLDOUT_SESSION_EVIDENCE_INCOMPLETE")
    expected_gates = {
        "provider_source_hashes_valid",
        "common_panel_valid",
        "leakage_tests_passed",
        "full_test_suite_green",
    }
    if set(release_gates) != expected_gates or not all(release_gates.values()):
        raise ValueError("HOLDOUT_RELEASE_GATES_FAILED")
    if not all(
        _valid_sha256(value)
        for value in (
            panel_sha256,
            stability_panel_sha256,
            acquisition_manifest_sha256,
        )
    ):
        raise ValueError("HOLDOUT_EVIDENCE_HASH_INVALID")
    preregistration_sha256 = method_freeze.get("input_hashes", {}).get(
        "preregistration.json"
    )
    if not _valid_sha256(preregistration_sha256):
        raise ValueError("PREREGISTRATION_HASH_INVALID")
    ledger: dict[str, Any] = {
        "schema_version": "phase5-holdout-access-1.0",
        "status": "ACQUIRED_NOT_READ",
        "holdout_sessions": list(EXPECTED_HOLDOUT_SESSIONS),
        "session_statuses": statuses,
        "last_session_complete": True,
        "method_freeze_sha256": method_freeze["manifest_sha256"],
        "preregistration_sha256": preregistration_sha256,
        "panel_sha256": panel_sha256,
        "stability_panel_sha256": stability_panel_sha256,
        "acquisition_manifest_sha256": acquisition_manifest_sha256,
        "release_gates": dict(release_gates),
        "holdout_reads": 0,
        "authorized_at_utc": None,
        "acquired_at_utc": acquired_at_utc.astimezone(UTC)
        .isoformat()
        .replace("+00:00", "Z"),
    }
    ledger["manifest_sha256"] = canonical_sha256(ledger)
    return ledger


def _validate_provider_evidence(
    storage: Any,
    fmp_manifest: Mapping[str, Any],
    b1_summary: Mapping[str, Any],
) -> list[dict[str, Any]]:
    batch = _read_json(storage.manifest_root / "batch_manifest.json")
    records = batch.get("sessions")
    if (
        batch.get("status") != "PASS"
        or batch.get("phase") != "5_HOLDOUT"
        or batch.get("session_count") != 10
        or not isinstance(records, list)
    ):
        raise ValueError("HOLDOUT_FULL_TAPE_MANIFEST_INVALID")
    statuses: list[dict[str, Any]] = []
    for expected_day, record in zip(EXPECTED_HOLDOUT_SESSIONS, records, strict=True):
        if (
            not isinstance(record, dict)
            or record.get("session_date") != expected_day
            or record.get("status") != "PASS"
            or not _valid_sha256(record.get("sha256"))
        ):
            raise ValueError("HOLDOUT_FULL_TAPE_SESSION_INVALID")
        raw = storage.raw_root / expected_day / f"full_tape_{expected_day}.zip"
        if not raw.is_file() or _sha256_file(raw) != record["sha256"]:
            raise ValueError(f"HOLDOUT_FULL_TAPE_HASH_MISMATCH:{expected_day}")
        statuses.append(
            {
                "session_date": expected_day,
                "status": "PASS",
                "full_tape_sha256": record["sha256"],
                "raw_bytes": int(record["bytes"]),
            }
        )
    fmp_records = fmp_manifest.get("records")
    if (
        fmp_manifest.get("status") != "PASS"
        or not isinstance(fmp_records, list)
        or len(fmp_records) != 80
        or any(record.get("rows_exact", 0) <= 0 for record in fmp_records)
    ):
        raise ValueError("HOLDOUT_FMP_MANIFEST_INVALID")
    if (
        b1_summary.get("status") != "PASS_B1Q_20_SESSION_RECOMPUTATION"
        or any(b1_summary.get("pit_invariants", {}).values())
        or not all(b1_summary.get("nested_invariants", {}).values())
    ):
        raise ValueError("HOLDOUT_B1Q_SUMMARY_INVALID")
    return statuses


def _build_panel(
    *,
    config: HoldoutAcquisitionConfig,
    storage: Any,
    method_freeze: Mapping[str, Any],
) -> tuple[pl.DataFrame, pl.DataFrame, list[dict[str, Any]]]:
    b2_config = b2_builder.B2BuildConfig(
        output_root=config.fmp_root,
        event_root=storage.event_root,
        download_manifest=storage.manifest_root / "batch_manifest.json",
        sessions=storage.sessions,
    )
    bars = b2_builder._fetch_fmp_bars(b2_config)
    origins_source = b2_builder._build_origins(bars, b2_config)
    b1_config = b1_builder.B1BuildConfig(
        output_root=config.b1_root,
        cache_root=config.b1_cache_root,
        sessions=tuple(day.isoformat() for day in storage.sessions),
        origins_path=config.fmp_root / "b2_calibration_origins.parquet",
    )
    b1_builder.main(b1_config)
    b1_source = pl.read_parquet(config.b1_root / "b1_origin_matrix_20d.parquet")
    batch = _read_json(storage.manifest_root / "batch_manifest.json")
    source_hashes = {
        str(row["session_date"]): str(row["sha256"]) for row in batch["sessions"]
    }
    all_rows, common = panel_builder._new_components(
        origins_source,
        bars,
        b1_source,
        storage.event_root,
        source_hashes,
        frozenset(),
        role="HOLDOUT_SEALED",
        source_cohort="HOLDOUT_10",
    )
    if (
        all_rows.height != 5_680
        or all_rows["origin_id"].n_unique() != all_rows.height
        or sorted(all_rows["session_date"].unique().to_list())
        != list(EXPECTED_HOLDOUT_SESSIONS)
    ):
        raise ValueError("HOLDOUT_NOMINAL_PANEL_SHAPE_INVALID")
    selected = holdout_runner._validate_panel(
        common,
        selected_assets=method_freeze["selected_assets"],
        b2_delay_seconds=int(
            method_freeze["timing"]["b2_primary_delay_seconds"]
        ),
    )
    config.panel_path.parent.mkdir(parents=True, exist_ok=True)
    common.write_parquet(config.panel_path, compression="zstd")
    sidecar, stability_evidence = stability_builder.build_stability_inputs(
        common,
        event_root=storage.event_root,
        selected_assets=method_freeze["selected_assets"],
    )
    holdout_runner._validate_stability_sidecar(
        sidecar,
        primary=selected,
        delays_seconds=(120, 300),
    )
    sidecar.write_parquet(config.stability_path, compression="zstd")
    return common, sidecar, stability_evidence["source_files"]


def _run_full_test_suite(report_path: Path) -> bool:
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    sanitized = (completed.stdout + completed.stderr).replace(
        str(ROOT), "MDS650_REPOSITORY"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(sanitized, encoding="utf-8")
    return completed.returncode == 0


def acquire(
    config: HoldoutAcquisitionConfig = DEFAULT_CONFIG,
    *,
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    """Acquire, validate and seal holdout inputs while preserving zero reads."""
    execution_time = now_utc or datetime.now(UTC)
    sessions = _read_json(config.session_manifest)
    method_freeze = _read_json(config.method_freeze)
    validate_acquisition_authority(sessions, method_freeze, execution_time)
    holdout_runner._validate_source_code_hashes(method_freeze)
    holdout_runner._validate_contract_hashes(method_freeze)
    if config.access_ledger.exists():
        existing = _read_json(config.access_ledger)
        if (
            _self_hash_valid(existing)
            and existing.get("status") == "ACQUIRED_NOT_READ"
            and existing.get("holdout_reads") == 0
            and config.panel_path.is_file()
            and _sha256_file(config.panel_path) == existing.get("panel_sha256")
        ):
            return existing
        raise FileExistsError("HOLDOUT_ACCESS_LEDGER_ALREADY_EXISTS_OR_INVALID")

    storage = downloader.load_phase5_holdout_config(
        session_manifest_path=config.session_manifest,
        output_root=config.data_root,
        projected_peak_additional_bytes=config.projected_peak_additional_bytes,
    )
    downloader.main(storage, phase_label="5_HOLDOUT")
    common, sidecar, event_sources = _build_panel(
        config=config,
        storage=storage,
        method_freeze=method_freeze,
    )
    fmp_manifest = _read_json(config.fmp_root / "fmp_20d_manifest.json")
    b1_summary = _read_json(config.b1_root / "b1_coverage_20d.json")
    session_statuses = _validate_provider_evidence(
        storage,
        fmp_manifest,
        b1_summary,
    )
    selected = common.filter(
        pl.col("asset").is_in(method_freeze["selected_assets"])
    )
    leakage_pass = not (
        selected.filter(
            (pl.col("b0_available_at_utc") > pl.col("forecast_origin_utc"))
            | (
                pl.col("b1q_max_sip_timestamp_ns")
                > pl.col("forecast_origin_utc").dt.epoch("ns")
            )
            | (
                pl.col("b2_max_operational_time").is_not_null()
                & (
                    pl.col("b2_max_operational_time")
                    > pl.col("b2_window_end")
                )
            )
        ).height
    )
    tests_pass = _run_full_test_suite(config.test_report)
    gates = {
        "provider_source_hashes_valid": True,
        "common_panel_valid": selected.height > 0,
        "leakage_tests_passed": leakage_pass,
        "full_test_suite_green": tests_pass,
    }
    if not all(gates.values()):
        raise RuntimeError("HOLDOUT_PRE_READ_RELEASE_GATE_FAILED")
    acquisition_manifest: dict[str, Any] = {
        "schema_version": "phase5-holdout-acquisition-1.0",
        "status": "PASS_ACQUIRED_NOT_ANALYSED",
        "holdout_reads": 0,
        "holdout_sessions": list(EXPECTED_HOLDOUT_SESSIONS),
        "session_statuses": session_statuses,
        "selected_assets": method_freeze["selected_assets"],
        "nominal_origin_count": 5_680,
        "common_origin_count": common.height,
        "selected_common_origin_count": selected.height,
        "panel_sha256": _sha256_file(config.panel_path),
        "stability_panel_sha256": _sha256_file(config.stability_path),
        "event_source_file_count": len(event_sources),
        "fmp_manifest_sha256": _sha256_file(
            config.fmp_root / "fmp_20d_manifest.json"
        ),
        "b1_summary_sha256": _sha256_file(
            config.b1_root / "b1_coverage_20d.json"
        ),
        "test_report_sha256": _sha256_file(config.test_report),
        "method_freeze_sha256": method_freeze["manifest_sha256"],
        "release_gates": gates,
        "outcomes_inspected": False,
        "qlike_computed": False,
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
    }
    acquisition_manifest["manifest_sha256"] = canonical_sha256(
        acquisition_manifest
    )
    _write_json(config.acquisition_manifest, acquisition_manifest)
    ledger = build_holdout_access_ledger(
        session_manifest=sessions,
        method_freeze=method_freeze,
        session_statuses=session_statuses,
        panel_sha256=acquisition_manifest["panel_sha256"],
        stability_panel_sha256=acquisition_manifest[
            "stability_panel_sha256"
        ],
        acquisition_manifest_sha256=acquisition_manifest["manifest_sha256"],
        release_gates=gates,
        acquired_at_utc=execution_time,
    )
    _write_json(config.access_ledger, ledger)
    return ledger


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Acquire and seal the prospective Phase 5 holdout."
    )
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument(
        "--projected-peak-additional-gib",
        type=int,
        default=30,
    )
    return parser.parse_args()


def main() -> None:
    """Run the post-period acquisition without reading model outcomes."""
    arguments = _arguments()
    result = acquire(
        HoldoutAcquisitionConfig(
            data_root=arguments.data_root,
            projected_peak_additional_bytes=(
                arguments.projected_peak_additional_gib * 1024**3
            ),
        )
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "holdout_reads": result["holdout_reads"],
                "manifest_sha256": result["manifest_sha256"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
