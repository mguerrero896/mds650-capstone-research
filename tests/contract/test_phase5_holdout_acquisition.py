"""Fail-closed acquisition contract for the prospective Phase 5 holdout."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from mds650.holdout import (
    EXPECTED_HOLDOUT_SESSIONS,
    authorize_holdout_read,
)
from mds650.study_design import canonical_sha256

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import acquire_phase5_holdout as acquisition  # noqa: E402

SESSION_MANIFEST = ROOT / "artifacts" / "phase5" / "study_sessions_90.json"
AFTER_HOLDOUT = datetime(2026, 7, 31, 20, 1, tzinfo=UTC)


def _self_hash(payload: dict[str, Any]) -> dict[str, Any]:
    result = {key: value for key, value in payload.items() if key != "manifest_sha256"}
    result["manifest_sha256"] = canonical_sha256(result)
    return result


def _method_freeze() -> dict[str, Any]:
    return _self_hash(
        {
            "schema_version": "phase5-method-freeze-1.0",
            "status": "FROZEN_AFTER_DEVELOPMENT_BEFORE_HOLDOUT",
            "holdout_reads": 0,
            "input_hashes": {"preregistration.json": "1" * 64},
            "holdout_hyperparameters": [
                {
                    "information_set": "B0",
                    "model_role": "gamma_glm_confirmatory",
                    "parameters": {"alpha": 0.1},
                }
            ],
        }
    )


def test_acquisition_denied_before_complete_holdout() -> None:
    sessions = json.loads(SESSION_MANIFEST.read_text(encoding="utf-8"))

    with pytest.raises(PermissionError, match="HOLDOUT_PERIOD_INCOMPLETE"):
        acquisition.validate_acquisition_authority(
            sessions,
            _method_freeze(),
            datetime(2026, 7, 31, 19, 59, tzinfo=UTC),
        )


def test_acquisition_authority_requires_exact_frozen_ten_sessions() -> None:
    sessions = json.loads(SESSION_MANIFEST.read_text(encoding="utf-8"))
    sessions["holdout"] = sessions["holdout"][:-1]
    sessions["holdout_count"] = 9
    sessions["manifest_sha256"] = canonical_sha256(
        {key: value for key, value in sessions.items() if key != "manifest_sha256"}
    )

    with pytest.raises(PermissionError, match="HOLDOUT_SESSION_SET_MISMATCH"):
        acquisition.validate_acquisition_authority(
            sessions,
            _method_freeze(),
            AFTER_HOLDOUT,
        )


def test_sealed_ledger_is_accepted_without_reading_holdout() -> None:
    sessions = json.loads(SESSION_MANIFEST.read_text(encoding="utf-8"))
    method_freeze = _method_freeze()
    ledger = acquisition.build_holdout_access_ledger(
        session_manifest=sessions,
        method_freeze=method_freeze,
        session_statuses=[
            {
                "session_date": day,
                "status": "PASS",
                "full_tape_sha256": str(index).zfill(64),
            }
            for index, day in enumerate(EXPECTED_HOLDOUT_SESSIONS, start=1)
        ],
        panel_sha256="2" * 64,
        stability_panel_sha256="3" * 64,
        acquisition_manifest_sha256="4" * 64,
        release_gates={
            "provider_source_hashes_valid": True,
            "common_panel_valid": True,
            "leakage_tests_passed": True,
            "full_test_suite_green": True,
        },
        acquired_at_utc=AFTER_HOLDOUT,
    )

    assert ledger["status"] == "ACQUIRED_NOT_READ"
    assert ledger["holdout_reads"] == 0
    assert ledger["authorized_at_utc"] is None
    assert ledger["manifest_sha256"] == canonical_sha256(
        {key: value for key, value in ledger.items() if key != "manifest_sha256"}
    )
    authorized = authorize_holdout_read(
        ledger,
        method_freeze,
        AFTER_HOLDOUT,
    )
    assert authorized["holdout_reads"] == 1


def test_sealed_ledger_rejects_failed_quality_gate() -> None:
    sessions = json.loads(SESSION_MANIFEST.read_text(encoding="utf-8"))
    gates = {
        "provider_source_hashes_valid": True,
        "common_panel_valid": True,
        "leakage_tests_passed": False,
        "full_test_suite_green": True,
    }

    with pytest.raises(ValueError, match="HOLDOUT_RELEASE_GATES_FAILED"):
        acquisition.build_holdout_access_ledger(
            session_manifest=sessions,
            method_freeze=_method_freeze(),
            session_statuses=[
                {"session_date": day, "status": "PASS"} for day in EXPECTED_HOLDOUT_SESSIONS
            ],
            panel_sha256="2" * 64,
            stability_panel_sha256="3" * 64,
            acquisition_manifest_sha256="4" * 64,
            release_gates=gates,
            acquired_at_utc=AFTER_HOLDOUT,
        )
