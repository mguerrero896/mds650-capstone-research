"""Artifact and schema tests for the one-read B1v3 runner."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl
import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from run_b1v3_confirmation_once import (  # noqa: E402
    _recovery_authorization_valid,
    _result_document,
    _write_bytes_exclusive,
    _write_json_exclusive,
    _write_parquet_exclusive,
)

from mds650.b1v3_confirmation import validate_confirmation_plan_schema  # noqa: E402
from mds650.study_design import canonical_sha256  # noqa: E402

_SHA = "a" * 64
_ASSETS = ("AAPL", "AMZN", "META", "MSFT", "NVDA", "TSLA")


def _manifest() -> dict[str, str]:
    return {"manifest_sha256": _SHA}


def _access_ledgers() -> tuple[dict[str, Any], dict[str, Any]]:
    frozen: dict[str, Any] = {
        "status": "METHOD_FROZEN_BEFORE_CONFIRMATION",
        "safe_to_evaluate_b1v3": "YES",
        "outcome_read_count": 1,
        "training_read_count": 1,
        "confirmation_read_count": 0,
        "evaluation_attempt_count": 0,
        "results_inspected": False,
        "common_panel_sha256": "1" * 64,
        "preregistration_manifest_sha256": "2" * 64,
    }
    frozen["manifest_sha256"] = canonical_sha256(frozen)
    consumed = {
        **{key: value for key, value in frozen.items() if key != "manifest_sha256"},
        "status": "CONFIRMATION_EVALUATION_IN_PROGRESS",
        "outcome_read_count": 2,
        "confirmation_read_count": 1,
        "evaluation_attempt_count": 1,
    }
    consumed["manifest_sha256"] = canonical_sha256(consumed)
    return frozen, consumed


def _panel() -> pl.DataFrame:
    rows: list[dict[str, Any]] = []
    for role, start, count in (
        ("development", datetime(2024, 8, 1, tzinfo=UTC), 60),
        ("confirmation", datetime(2024, 11, 1, tzinfo=UTC), 30),
    ):
        for day in range(count):
            session_date = (start + timedelta(days=day)).date().isoformat()
            for asset in _ASSETS:
                origin = datetime.fromisoformat(f"{session_date}T15:00:00+00:00")
                rows.append(
                    {
                        "origin_id": f"{asset}|{origin.isoformat()}",
                        "asset": asset,
                        "session_date": session_date,
                        "forecast_origin_utc": origin,
                        "role": role,
                        "rv30": 0.001,
                    }
                )
    return pl.DataFrame(rows)


def _scientific_result() -> dict[str, Any]:
    claim = {
        "status": "GLOBAL_EDGE_NOT_CONFIRMED",
        "mde": 0.001,
        "conditions": {"gamma_estimate_positive": False},
        "failed_conditions": ["gamma_estimate_positive"],
    }
    return {
        "metrics": [],
        "global": {},
        "global_holm": {"delta_b1v3": 1.0, "delta_b2": 1.0},
        "stability": [],
        "timing": [],
        "claims": {"delta_b1v3": claim, "delta_b2": claim},
        "decision": "GLOBAL_EDGE_NOT_CONFIRMED",
        "all_signs_retained": True,
    }


def test_result_document_is_self_hashed_schema_valid_and_sign_complete(
    tmp_path: Path,
) -> None:
    panel = _panel()
    forecasts = pl.DataFrame({"origin_id": ["one"]})
    authorization = {
        "manifest_sha256": _SHA,
        "confirmation_code_sha256": "b" * 64,
        "uv_lock_sha256": "c" * 64,
    }
    result = _result_document(
        preregistration=_manifest(),
        method_freeze=_manifest(),
        frozen_access=_manifest(),
        authorization=authorization,
        common_manifest=_manifest(),
        timing_manifest=_manifest(),
        quality_report=_manifest(),
        primary_panel=panel,
        primary_forecasts=forecasts,
        timing_forecasts=forecasts,
        primary_panel_sha256="1" * 64,
        primary_forecasts_sha256="2" * 64,
        timing_forecasts_sha256="3" * 64,
        evaluation=_scientific_result(),
    )

    validate_confirmation_plan_schema(
        result,
        ROOT / "specs/001-pit-options-rv30/contracts/b1v3-confirmation-result-v1.schema.json",
    )
    assert result["sample"]["training_sessions"] == 60
    assert result["sample"]["confirmation_sessions"] == 30
    assert result["all_signs_retained"] is True
    assert len(result["manifest_sha256"]) == 64
    assert len(_write_json_exclusive(tmp_path / "result.json", result)) == 64


def test_final_writers_are_exclusive_and_sanitized(tmp_path: Path) -> None:
    json_path = tmp_path / "result.json"
    markdown_path = tmp_path / "report.md"
    parquet_path = tmp_path / "forecasts.parquet"
    frame = pl.DataFrame({"origin_id": ["one"], "forecast": [0.1]})

    assert len(_write_json_exclusive(json_path, {"status": "PASS"})) == 64
    assert len(_write_bytes_exclusive(markdown_path, b"# Safe report\n")) == 64
    assert len(_write_parquet_exclusive(parquet_path, frame)) == 64
    with pytest.raises(ValueError, match="B1V3_CONFIRMATION_OUTPUT_EXISTS"):
        _write_json_exclusive(json_path, {"status": "PASS"})
    with pytest.raises(ValueError, match="B1V3_CONFIRMATION_OUTPUT_EXISTS"):
        _write_parquet_exclusive(parquet_path, frame)
    with pytest.raises(ValueError, match="B1V3_CONFIRMATION_OUTPUT_HYGIENE_INVALID"):
        _write_bytes_exclusive(tmp_path / "unsafe.md", b"C:/Users/person/private")
    with pytest.raises(ValueError, match="B1V3_CONFIRMATION_OUTPUT_HYGIENE_INVALID"):
        _write_bytes_exclusive(tmp_path / "secret.txt", b"Authorization: Basic secret")


def test_recovery_accepts_only_the_exact_consumed_one_read_ledger() -> None:
    frozen, consumed = _access_ledgers()

    assert _recovery_authorization_valid(frozen, consumed)
    tampered = {**consumed, "evaluation_attempt_count": 2}
    tampered["manifest_sha256"] = canonical_sha256(
        {key: value for key, value in tampered.items() if key != "manifest_sha256"}
    )
    assert not _recovery_authorization_valid(frozen, tampered)
