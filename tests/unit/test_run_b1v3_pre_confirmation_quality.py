"""Pre-confirmation quality-gate contracts for B1v3."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from run_b1v3_pre_confirmation_quality import (  # noqa: E402
    _assert_target_blind_panel,
    build_quality_document,
)

from mds650.b1v3_confirmation import validate_confirmation_plan_schema  # noqa: E402
from mds650.study_design import canonical_sha256  # noqa: E402

_GATES = (
    "focused_tests",
    "full_tests",
    "ruff",
    "mypy",
    "coverage",
    "json_schema",
    "no_leakage",
    "hygiene",
    "deterministic_replay",
    "clean_install",
    "spec_kit",
    "disk_gate",
)


def test_quality_document_requires_every_gate_and_validates_schema() -> None:
    evidence = {name: "a" * 64 for name in _GATES}
    document = build_quality_document(
        preregistration_manifest_sha256="1" * 64,
        method_freeze_manifest_sha256="2" * 64,
        common_panel_sha256="3" * 64,
        timing_panel_manifest_sha256="4" * 64,
        gate_evidence=evidence,
    )

    validate_confirmation_plan_schema(
        document,
        ROOT / "specs/001-pit-options-rv30/contracts/b1v3-pre-confirmation-quality-v1.schema.json",
    )
    assert document["status"] == "PASS_B1V3_PRE_CONFIRMATION_QUALITY"
    assert set(document["gates"]) == set(_GATES)
    assert document["manifest_sha256"] == canonical_sha256(
        {key: value for key, value in document.items() if key != "manifest_sha256"}
    )
    with pytest.raises(ValueError, match="B1V3_QUALITY_GATE_SET_INVALID"):
        build_quality_document(
            preregistration_manifest_sha256="1" * 64,
            method_freeze_manifest_sha256="2" * 64,
            common_panel_sha256="3" * 64,
            timing_panel_manifest_sha256="4" * 64,
            gate_evidence={name: "a" * 64 for name in _GATES[:-1]},
        )


def test_target_blind_gate_rejects_outcomes_and_future_source_times() -> None:
    origin = datetime(2024, 8, 2, 15, tzinfo=UTC)
    safe = pl.DataFrame(
        {
            "origin_id": ["AAPL|one"],
            "forecast_origin_utc": [origin],
            "forecast_origin_ns": [int(origin.timestamp() * 1_000_000_000)],
            "max_predictor_available_at_utc": [origin],
            "max_sip_timestamp_ns": [int((origin - timedelta(seconds=1)).timestamp() * 1e9)],
            "b2v2_max_created_at_utc": [origin - timedelta(seconds=61)],
            "b2v2_cutoff_utc": [origin - timedelta(seconds=60)],
        }
    )

    _assert_target_blind_panel(safe)
    with pytest.raises(ValueError, match="B1V3_QUALITY_OUTCOME_COLUMN_FORBIDDEN"):
        _assert_target_blind_panel(safe.with_columns(pl.lit(0.1).alias("rv30")))
    with pytest.raises(ValueError, match="B1V3_QUALITY_FUTURE_B2_RECORD"):
        _assert_target_blind_panel(
            safe.with_columns(
                (pl.col("b2v2_cutoff_utc") + pl.duration(seconds=1)).alias(
                    "b2v2_max_created_at_utc"
                )
            )
        )
