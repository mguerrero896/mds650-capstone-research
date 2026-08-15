"""Target-blind scope checks for Massive B1Q independent replication."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from mds650.b1v3_confirmation import canonical_sha256, sha256_file

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import acquire_b1_independent_replication_b1q as acquisition  # noqa: E402
import run_b1_calibration_20d as legacy_b1q  # noqa: E402


def test_run_contract_accepts_only_hash_bound_target_free_origins(tmp_path: Path) -> None:
    origins = pl.DataFrame(
        {
            "origin_id": ["AAPL:2024-12-10T14:35:00+00:00"],
            "asset": ["AAPL"],
            "session_date": ["2024-12-10"],
            "forecast_origin_utc": [datetime(2024, 12, 10, 14, 35, tzinfo=UTC)],
            "spot": [247.0],
            "session_segment": ["first"],
        }
    )
    origins_path = tmp_path / "origins.parquet"
    origins.write_parquet(origins_path)
    base: dict[str, object] = {
        "status": "PASS_TARGET_BLIND_BASE_PREDICTORS",
        "target_blind": True,
        "outcome_read_count": 0,
        "safe_to_read_outcomes": False,
        "preregistration_sha256": "a" * 64,
        "session_count": 1,
        "assets": ["AAPL"],
        "origin_count": 1,
        "outputs": {"b1_origins": {"sha256": sha256_file(origins_path)}},
    }
    base["manifest_sha256"] = canonical_sha256(base)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(base), encoding="utf-8")

    acquisition.validate_b1q_run_contract(
        base_manifest_path=manifest_path,
        origins_path=origins_path,
        preregistration_sha256="a" * 64,
        sessions=("2024-12-10",),
        assets=("AAPL",),
        expected_origin_count=1,
    )


def test_legacy_b1q_final_parquet_is_atomically_promoted(tmp_path: Path) -> None:
    """A completed B1Q table must appear only after its temporary file closes."""
    target = tmp_path / "b1_iv_attempts_20d.parquet"
    frame = pl.DataFrame({"origin_id": ["one"], "iv": [0.25]})

    legacy_b1q._write_parquet_atomic(frame, target)

    assert target.is_file()
    assert not target.with_suffix(target.suffix + ".part").exists()
    assert pl.read_parquet(target).equals(frame)


def test_b1q_summary_metadata_uses_observed_session_count() -> None:
    """A 30-session replication must not retain legacy 20/60-session labels."""
    assert legacy_b1q._run_metadata(30) == {
        "status": "PASS_B1Q_RECOMPUTATION",
        "scope": "TARGET_BLIND_30_SESSIONS",
    }
