"""Unit contracts for the source-bound B1v3 base predictor build."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import exchange_calendars as xcals  # type: ignore[import-untyped]
import polars as pl
import pytest

import mds650.b1v3_confirmation_build as build_module
from mds650.b1v3_confirmation import canonical_sha256
from mds650.b1v3_confirmation_build import (
    BasePredictorArtifacts,
    FrozenBuildInputs,
    build_base_predictor_artifacts,
    build_fmp_bar_corpus,
    load_frozen_build_inputs,
)
from mds650.phase6 import B0V2_FEATURES


def _session_arrays() -> tuple[tuple[str, ...], tuple[str, ...]]:
    calendar = xcals.get_calendar("XNYS")
    sessions = tuple(
        value.date().isoformat()
        for value in calendar.sessions_in_range("2024-01-02", "2024-05-10")[:90]
    )
    return sessions[:60], sessions[60:]


def test_real_frozen_inputs_are_accepted() -> None:
    root = Path(__file__).resolve().parents[2]
    inputs = load_frozen_build_inputs(
        root / "artifacts/b1v3_confirmation_plan/confirmation_plan_provider_passed.json",
        root / "artifacts/b1v3_provider_preflight_v2/provider_preflight_report.json",
        root / "artifacts/b1v3_provider_preflight_v2/candidate_preflight_plan.json",
        root / "artifacts/b1v3_confirmation_plan/confirmation_plan.json",
    )

    assert len(inputs.training_sessions) == 60
    assert len(inputs.confirmation_sessions) == 30
    assert len(inputs.all_sessions) == 90
    assert len(inputs.fmp_records) == 720


@pytest.mark.parametrize(
    ("tampered_index", "expected_code"),
    [
        (0, "B1V3_BASE_PLAN_HASH_INVALID"),
        (1, "B1V3_BASE_PROVIDER_REPORT_HASH_INVALID"),
        (2, "B1V3_BASE_PROVIDER_CANDIDATE_PLAN_HASH_INVALID"),
        (3, "B1V3_BASE_SOURCE_CONFIRMATION_PLAN_HASH_INVALID"),
    ],
)
def test_frozen_input_loader_rejects_any_tampered_hash(
    tmp_path: Path,
    tampered_index: int,
    expected_code: str,
) -> None:
    root = Path(__file__).resolve().parents[2]
    paths = [
        root / "artifacts/b1v3_confirmation_plan/confirmation_plan_provider_passed.json",
        root / "artifacts/b1v3_provider_preflight_v2/provider_preflight_report.json",
        root / "artifacts/b1v3_provider_preflight_v2/candidate_preflight_plan.json",
        root / "artifacts/b1v3_confirmation_plan/confirmation_plan.json",
    ]
    copies: list[Path] = []
    for source in paths:
        destination = tmp_path / source.name
        destination.write_bytes(source.read_bytes())
        copies.append(destination)
    document = json.loads(copies[tampered_index].read_text(encoding="utf-8"))
    document["status"] = "TAMPERED"
    copies[tampered_index].write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ValueError, match=expected_code):
        load_frozen_build_inputs(*copies)


def test_one_authenticated_fmp_cache_builds_exact_xnys_grid(tmp_path: Path) -> None:
    day = "2024-08-02"
    opened = datetime(2024, 8, 2, 9, 30)
    payload = [
        {
            "date": (opened + timedelta(minutes=offset)).isoformat(sep=" "),
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 1000,
        }
        for offset in range(390)
    ]
    document: dict[str, Any] = {
        "schema_version": "b1v3-provider-preflight-cache-2.0",
        "provider": "fmp",
        "request_fingerprint": "a" * 64,
        "status_code": 200,
        "payload": payload,
        "response_sha256": "b" * 64,
    }
    document["cache_self_hash"] = canonical_sha256(document)
    cache = tmp_path / "fmp" / day / "AAPL.json"
    cache.parent.mkdir(parents=True)
    cache.write_text(json.dumps(document), encoding="utf-8")
    record = {
        "asset": "AAPL",
        "session_date": day,
        "evidence_key": f"fmp/{day}/AAPL.json",
        "provider": "fmp",
        "pass": True,
        "request_fingerprint": "a" * 64,
        "response_sha256": "b" * 64,
        "exact_session_row_count": 390,
        "returned_row_count": 390,
        "provider_over_return_count": 0,
    }
    inputs = FrozenBuildInputs(
        "c" * 64,
        "d" * 64,
        "e" * 64,
        "f" * 64,
        (day,),
        (),
        (record,),
    )

    frame, records = build_fmp_bar_corpus(inputs, cache_root=tmp_path)

    assert frame.height == 390
    assert frame["bar_timestamp_raw_utc"].min() == datetime(2024, 8, 2, 13, 30, tzinfo=UTC)
    assert records[0]["row_count"] == 390
    assert records[0]["provider_over_return"] is False

    invalid_record = {**record, "evidence_key": "../outside.json"}
    invalid_inputs = FrozenBuildInputs(
        "c" * 64,
        "d" * 64,
        "e" * 64,
        "f" * 64,
        (day,),
        (),
        (invalid_record,),
    )
    with pytest.raises(ValueError, match="B1V3_BASE_FMP_EVIDENCE_KEY_INVALID"):
        build_fmp_bar_corpus(invalid_inputs, cache_root=tmp_path)


def test_base_build_writes_source_bound_outputs_and_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    training, confirmation = _session_arrays()
    inputs = FrozenBuildInputs(
        "a" * 64,
        "b" * 64,
        "c" * 64,
        "d" * 64,
        training,
        confirmation,
        tuple({"asset": "AAPL"} for _ in range(720)),
    )
    origins = pl.DataFrame(
        {
            "origin_id": ["AAPL:1", "AAPL:2"],
            "asset": ["AAPL", "AAPL"],
            "session_date": [training[0], training[0]],
            "forecast_origin_utc": [
                datetime(2024, 1, 2, 14, 35, tzinfo=UTC),
                datetime(2024, 1, 2, 14, 40, tzinfo=UTC),
            ],
            "forecast_origin_ny": [
                datetime(2024, 1, 2, 9, 35, tzinfo=UTC),
                datetime(2024, 1, 2, 9, 40, tzinfo=UTC),
            ],
            "forecast_origin_ns": [1, 2],
            "role": ["training_warmup", "training_warmup"],
            "session_minute": [5, 10],
            "session_tercile": ["first", "first"],
            "session_segment": ["first", "first"],
        }
    )
    bars = pl.DataFrame(
        {
            "asset": ["AAPL", "AAPL"],
            "session_date": [training[0], training[0]],
            "bar_timestamp_raw_utc": origins["forecast_origin_utc"]
            - timedelta(minutes=1),
            "available_at_utc": origins["forecast_origin_utc"],
            "close": [100.0, 101.0],
            "volume": [1000.0, 1000.0],
        }
    )
    spots = origins.select("origin_id").with_columns(
        pl.Series("spot", [100.0, 101.0]),
        pl.Series(
            "spot_bar_timestamp_raw_utc",
            [
                datetime(2024, 1, 2, 14, 34, tzinfo=UTC),
                datetime(2024, 1, 2, 14, 39, tzinfo=UTC),
            ],
        ),
        origins["forecast_origin_utc"].alias("spot_available_at_utc"),
        pl.lit(True).alias("spot_available"),
        pl.lit(None, dtype=pl.String).alias("spot_missing_reason"),
    )
    b0 = origins.select("origin_id").with_columns(
        *[
            pl.lit("AAPL").alias(feature)
            if feature == "b0v2_asset_identity"
            else pl.lit(1.0).alias(feature)
            for feature in B0V2_FEATURES
        ],
        pl.lit(True).alias("b0_complete"),
        pl.lit(None, dtype=pl.String).alias("b0_missing_reason"),
    )

    monkeypatch.setattr(build_module, "build_origin_grid", lambda **_kwargs: origins)
    monkeypatch.setattr(
        build_module,
        "build_fmp_bar_corpus",
        lambda *_args, **_kwargs: (bars, tuple({"ok": True} for _ in range(720))),
    )
    monkeypatch.setattr(build_module, "build_spot_frame", lambda *_args: spots)
    monkeypatch.setattr(build_module, "build_b0_target_blind", lambda *_args: b0)
    output_root = tmp_path / "data"
    manifest = tmp_path / "manifest.json"
    schema = (
        Path(__file__).resolve().parents[2]
        / "specs/001-pit-options-rv30/contracts/"
        "b1v3-confirmation-base-predictors-v1.schema.json"
    )

    first = build_base_predictor_artifacts(
        inputs=inputs,
        fmp_cache_root=tmp_path,
        output_root=output_root,
        manifest_path=manifest,
        manifest_schema_path=schema,
    )
    second = build_base_predictor_artifacts(
        inputs=inputs,
        fmp_cache_root=tmp_path,
        output_root=output_root,
        manifest_path=manifest,
        manifest_schema_path=schema,
    )

    assert isinstance(first, BasePredictorArtifacts)
    assert first.manifest_sha256 == second.manifest_sha256
    document = json.loads(manifest.read_text(encoding="utf-8"))
    assert document["status"] == "PASS_TARGET_BLIND_BASE_PREDICTORS"
    assert document["outcome_read_count"] == 0
    assert document["safe_to_read_outcomes"] is False
    assert document["origin_count"] == 2
    assert all(path.is_file() for path in output_root.glob("*.parquet"))

    pl.DataFrame({"conflict": [1]}).write_parquet(output_root / "b0_target_blind.parquet")
    with pytest.raises(ValueError, match="B1V3_BASE_OUTPUT_CONFLICT"):
        build_base_predictor_artifacts(
            inputs=inputs,
            fmp_cache_root=tmp_path,
            output_root=output_root,
            manifest_path=manifest,
            manifest_schema_path=schema,
        )
