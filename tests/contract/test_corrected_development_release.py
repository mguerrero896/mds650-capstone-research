"""Contract tests for the corrected-development release manifest."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest
from jsonschema import Draft202012Validator

from mds650.corrected_development_release import (
    FROZEN_B2_FEATURES,
    assert_safe_corrected_development_paths,
    build_corrected_development_release,
    prepare_corrected_development_panel,
    validate_corrected_development_release,
)
from mds650.study_design import build_study_sessions

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = (
    ROOT
    / "specs"
    / "001-pit-options-rv30"
    / "contracts"
    / "corrected-development-release-v1.schema.json"
)


def test_release_manifest_is_schema_valid_deterministic_and_legacy_oos_closed() -> None:
    """A target-free release binds the 80-session identity without opening outcomes."""
    development, holdout = _study_sessions()
    prepared = prepare_corrected_development_panel(
        panel=_eligible_panel(development),
        development_sessions=development,
        holdout_sessions=holdout,
    )
    kwargs = {
        "prepared": prepared,
        "source_hashes": _source_hashes(),
        "output_hashes": _output_hashes(),
        "source_locations": {
            "predictor_panel": "D:/MDS650/phase6/derived/target_blind_v24/panel.parquet",
            "corrected_panel": "D:/MDS650/phase6/derived/corrected_development_v1/panel.parquet",
            "corrected_common": "D:/MDS650/phase6/derived/corrected_development_v1/common.parquet",
        },
        "release_id": "corrected-development-v1-20260812",
    }

    first = build_corrected_development_release(**kwargs)
    second = build_corrected_development_release(**kwargs)

    assert first == second
    assert first["status"] == "TARGET_BLIND_READY"
    assert first["gates"]["safe_to_evaluate_corrected_development"] == "NO"
    assert first["gates"]["safe_to_reconcile_existing_results"] == "NO"
    assert first["gates"]["safe_to_open_or_evaluate_oos"] == "NO"
    assert first["no_target_or_metric_payload_read_during_predictor_build"] is True
    assert first["model_fit_performed"] is False
    assert first["output"] == _output_hashes()
    validate_corrected_development_release(first, SCHEMA_PATH)

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    assert not list(Draft202012Validator(schema).iter_errors(first))


def test_release_rejects_gate_escalation_and_personal_or_secret_like_paths() -> None:
    """The release schema and path guard refuse an OOS escalation before output exists."""
    development, holdout = _study_sessions()
    prepared = prepare_corrected_development_panel(
        panel=_eligible_panel(development),
        development_sessions=development,
        holdout_sessions=holdout,
    )
    release = build_corrected_development_release(
        prepared=prepared,
        source_hashes=_source_hashes(),
        output_hashes=_output_hashes(),
        source_locations={
            "predictor_panel": "D:/MDS650/phase6/derived/target_blind_v24/panel.parquet",
            "corrected_panel": "D:/MDS650/phase6/derived/corrected_development_v1/panel.parquet",
            "corrected_common": "D:/MDS650/phase6/derived/corrected_development_v1/common.parquet",
        },
        release_id="corrected-development-v1-20260812",
    )
    release["gates"]["safe_to_open_or_evaluate_oos"] = "YES"

    with pytest.raises(ValueError, match="CORRECTED_DEVELOPMENT_RELEASE_SCHEMA_VIOLATION"):
        validate_corrected_development_release(release, SCHEMA_PATH)

    with pytest.raises(ValueError, match="CORRECTED_DEVELOPMENT_UNSAFE_PATH:output_root"):
        assert_safe_corrected_development_paths(
            {
                "artifact_root": ROOT / "artifacts" / "corrected_development_v1",
                "output_root": Path(r"C:\\Users\\mguer\\Desktop"),
            }
        )


def _study_sessions() -> tuple[list[str], list[str]]:
    sessions = build_study_sessions(
        "XNYS",
        development_end=datetime(2026, 7, 17, tzinfo=UTC).date(),
        development_count=80,
        holdout_count=10,
    )
    return sessions["development"], sessions["holdout"]


def _eligible_panel(development: list[str]) -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    for index, session_date in enumerate(development):
        origin = datetime.fromisoformat(f"{session_date}T14:00:00+00:00")
        row: dict[str, object] = {
            "origin_id": f"AAPL|{session_date}|{index:03d}",
            "asset": "AAPL",
            "session_date": session_date,
            "forecast_origin_utc": origin,
            "forecast_origin_ns": int(origin.timestamp() * 1_000_000_000),
            "b0v2_max_predictor_available_at_utc": origin,
            "max_sip_timestamp_ns": int(origin.timestamp() * 1_000_000_000),
            "b2v2_cutoff_utc": origin,
            "b2v2_max_created_at_utc": origin,
            "b2v2_availability_eligible": True,
            "b2v2_availability_status": "PIT_USABLE_ELIGIBLE_ACTIVITY",
            "b2v2_predictor_missing_reason": None,
            "b2v2_predictor_complete": True,
            "common_predictor_complete": True,
        }
        for feature in FROZEN_B2_FEATURES:
            row[feature] = 1.0
        rows.append(row)
    return pl.DataFrame(rows, strict=False)


def _source_hashes() -> dict[str, str]:
    return {
        "target_blind_predictor_manifest_sha256": "a" * 64,
        "b2_availability_sidecar_sha256": "b" * 64,
        "pit_reconciliation_gate_sha256": "c" * 64,
        "massive_reselection_sha256": "d" * 64,
        "development_source_manifest_sha256": "e" * 64,
    }


def _output_hashes() -> dict[str, int | str]:
    return {
        "panel_sha256": "f" * 64,
        "common_complete_sha256": "0" * 64,
        "panel_row_count": 80,
        "common_complete_row_count": 80,
    }
