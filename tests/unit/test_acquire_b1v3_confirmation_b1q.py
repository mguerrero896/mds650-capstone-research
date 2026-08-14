"""Unit gates for the target-blind B1v3 Massive acquisition launcher."""

from __future__ import annotations

import json
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from mds650.b1v3_confirmation import canonical_sha256, sha256_file
from mds650.b1v3_confirmation_build import B1V3_CANONICAL_ASSETS, FrozenBuildInputs

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import run_b1_calibration_20d as legacy_b1q  # noqa: E402
from acquire_b1v3_confirmation_b1q import validate_b1q_run_contract  # noqa: E402


def _inputs() -> FrozenBuildInputs:
    first = date(2024, 1, 1)
    sessions = tuple((first + timedelta(days=index)).isoformat() for index in range(90))
    return FrozenBuildInputs(
        plan_sha256="a" * 64,
        report_sha256="b" * 64,
        provider_candidate_plan_sha256="c" * 64,
        source_confirmation_plan_sha256="d" * 64,
        training_sessions=sessions[:60],
        confirmation_sessions=sessions[60:],
        fmp_records=(),
    )


def _origins(inputs: FrozenBuildInputs) -> pl.DataFrame:
    rows: list[dict[str, Any]] = []
    for day_index, session_date in enumerate(inputs.all_sessions):
        origin_count = 36 if day_index == 89 else 72
        for asset in B1V3_CANONICAL_ASSETS:
            for origin_index in range(origin_count):
                rows.append(
                    {
                        "origin_id": f"{asset}:{session_date}:{origin_index}",
                        "asset": asset,
                        "session_date": session_date,
                        "forecast_origin_utc": datetime(2024, 1, 1, 14, 35, tzinfo=UTC)
                        + timedelta(minutes=5 * origin_index),
                        "spot": 100.0,
                        "session_segment": "first",
                    }
                )
    return pl.DataFrame(rows)


def _write_base(path: Path, origins_path: Path, inputs: FrozenBuildInputs) -> None:
    document: dict[str, Any] = {
        "status": "PASS_TARGET_BLIND_BASE_PREDICTORS",
        "plan_sha256": inputs.plan_sha256,
        "target_blind": True,
        "outcome_read_count": 0,
        "safe_to_read_outcomes": False,
        "outputs": {"b1_origins": {"sha256": sha256_file(origins_path)}},
    }
    document["manifest_sha256"] = canonical_sha256(document)
    path.write_text(json.dumps(document), encoding="utf-8")


def test_run_contract_accepts_exact_target_blind_90_session_scope(tmp_path: Path) -> None:
    inputs = _inputs()
    origins_path = tmp_path / "origins.parquet"
    _origins(inputs).write_parquet(origins_path)
    base_path = tmp_path / "base.json"
    _write_base(base_path, origins_path, inputs)

    validate_b1q_run_contract(
        inputs=inputs,
        base_manifest_path=base_path,
        origins_path=origins_path,
    )


def test_run_contract_rejects_target_column_even_when_source_hash_is_bound(
    tmp_path: Path,
) -> None:
    inputs = _inputs()
    origins_path = tmp_path / "origins.parquet"
    _origins(inputs).with_columns(pl.lit(1.0).alias("rv30")).write_parquet(origins_path)
    base_path = tmp_path / "base.json"
    _write_base(base_path, origins_path, inputs)

    with pytest.raises(ValueError, match="B1V3_B1Q_ORIGIN_NOT_TARGET_BLIND"):
        validate_b1q_run_contract(
            inputs=inputs,
            base_manifest_path=base_path,
            origins_path=origins_path,
        )


def test_custom_contract_cache_preserves_legacy_resolution_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = legacy_b1q.B1BuildConfig(
        output_root=tmp_path / "out",
        cache_root=tmp_path / "cache",
        sessions=("2024-01-02",),
        contract_cache_filename="resolved_contracts_b1v3_canonical_spot_v1.json",
    )
    origins = pl.DataFrame(
        {"asset": ["AAPL"], "session_date": ["2024-01-02"], "spot": [100.0]}
    )
    monkeypatch.setattr(legacy_b1q.closure, "resolve_contracts", lambda *_args: [])

    result = legacy_b1q._resolve_contracts(origins, "secret-not-emitted", config)

    assert result == {("AAPL", "2024-01-02"): []}
    assert (config.cache_root / config.contract_cache_filename).is_file()
    assert not (config.cache_root / "resolved_contracts_phase6_strict_v3.json").exists()


@pytest.mark.parametrize(
    "filename",
    ["../escape.json", "nested/cache.json", "cache.txt", ""],
)
def test_contract_cache_filename_is_restricted_to_one_json_file(
    tmp_path: Path,
    filename: str,
) -> None:
    with pytest.raises(ValueError, match="B1_CONTRACT_CACHE_FILENAME_INVALID"):
        legacy_b1q.B1BuildConfig(
            output_root=tmp_path,
            cache_root=tmp_path,
            sessions=("2024-01-02",),
            contract_cache_filename=filename,
        )
