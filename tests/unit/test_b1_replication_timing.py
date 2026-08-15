"""Target-blind timing contracts for the independent replication."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from importlib import import_module
from pathlib import Path
from typing import Any, cast

import polars as pl
import pytest

from mds650.b1_replication_timing import (
    _validate_target_blind_columns,
    build_replication_timing_common_artifacts,
    finalize_replication_timing_predictors,
    materialize_replication_timing_attempts,
    seal_derived_attempt_source,
)
from mds650.b1v3 import B1V3_FEATURES
from mds650.b1v3_confirmation import canonical_sha256, sha256_file
from mds650.phase6 import B0V2_FEATURES
from mds650.study_design import B2_FEATURE_NAMES

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ("AAPL", "AMZN", "META", "MSFT", "NVDA", "TSLA")
TIMING_VARIANTS = (
    "FMP_DELAY_2_MINUTES",
    "MASSIVE_CUTOFF_60_SECONDS",
    "MASSIVE_CUTOFF_300_SECONDS",
)


def _attempt(path: Path, *, sip_timestamp: int = 939_000_000_000) -> None:
    pl.DataFrame(
        {
            "origin_id": ["AAPL:2024-12-10T09:35:00-05:00"],
            "asset": ["AAPL"],
            "session_date": ["2024-12-10"],
            "contract": ["O:AAPL250117C00250000"],
            "source_request_hash": ["a" * 64],
            "forecast_origin_ns": [1_000_000_000_000],
            "sip_timestamp": [sip_timestamp],
            "spot": [250.0],
            "strike": [250.0],
            "dte": [38.0],
            "rate": [0.04],
            "dividend_yield": [0.005],
            "option_type": ["call"],
            "iv_success": [True],
            "iv": [0.25],
            "quote_cutoff_seconds": [60],
        }
    ).write_parquet(path)


def test_target_moneyness_is_design_metadata_not_an_outcome(tmp_path: Path) -> None:
    attempts = tmp_path / "attempts.parquet"
    pl.DataFrame(
        {
            "origin_id": ["AAPL:1"],
            "target_moneyness": [1.0],
        }
    ).write_parquet(attempts)

    assert "target_moneyness" in _validate_target_blind_columns(attempts)


def test_target_blind_column_gate_still_rejects_rv30(tmp_path: Path) -> None:
    attempts = tmp_path / "attempts.parquet"
    pl.DataFrame({"origin_id": ["AAPL:1"], "rv30": [0.1]}).write_parquet(attempts)

    with pytest.raises(ValueError, match="B1_REPLICATION_TIMING_FORBIDDEN_COLUMN"):
        _validate_target_blind_columns(attempts)


def _source(inventory: Path) -> dict[str, object]:
    document: dict[str, object] = {
        "status": "PASS_TARGET_BLIND_B1Q_SOURCE_BOUND",
        "preregistration_manifest_sha256": "b" * 64,
        "base_manifest_sha256": "c" * 64,
        "target_blind": True,
        "outcome_read_count": 0,
        "safe_to_read_outcomes": False,
        "scope": {"replication_session_count": 30, "asset_count": 6},
        "attempts": {"sha256": "d" * 64},
        "raw_payload_binding": {
            "status": "PRESENT_AND_VALIDATED",
            "inventory_sha256": sha256_file(inventory),
            "contract_day_count": 1,
        },
        "pit_invariants": {
            "future_selected_quote_rows": 0,
            "pagination_validated": True,
        },
        "security": {
            "secret_values_emitted": False,
            "personal_paths_emitted": False,
        },
    }
    document["manifest_sha256"] = canonical_sha256(document)
    return document


def _hashed(document: dict[str, object]) -> dict[str, object]:
    document["manifest_sha256"] = canonical_sha256(document)
    return document


def _write_document(path: Path, document: dict[str, object]) -> None:
    path.write_text(json.dumps(document), encoding="utf-8")


def _complete_frames() -> tuple[list[str], pl.DataFrame, pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    sessions = [
        (datetime(2024, 12, 10, tzinfo=UTC) + timedelta(days=index)).date().isoformat()
        for index in range(30)
    ]
    rows = [
        (asset, session, datetime.fromisoformat(f"{session}T15:00:00+00:00"))
        for session in sessions
        for asset in ASSETS
    ]
    origin_ids = [f"{asset}:{session}:15:00" for asset, session, _ in rows]
    origins = pl.DataFrame(
        {
            "origin_id": origin_ids,
            "asset": [asset for asset, _, _ in rows],
            "session_date": [session for _, session, _ in rows],
            "forecast_origin_utc": [origin for _, _, origin in rows],
            "forecast_origin_ns": [
                int(origin.timestamp() * 1_000_000_000) for _, _, origin in rows
            ],
            "role": ["independent_replication"] * len(rows),
            "session_minute": [120] * len(rows),
            "session_tercile": ["middle"] * len(rows),
        }
    )
    b0_values: dict[str, list[object]] = {
        feature: (
            [asset for asset, _, _ in rows]
            if feature == "b0v2_asset_identity"
            else [0.1] * len(rows)
        )
        for feature in B0V2_FEATURES
    }
    b0 = pl.DataFrame(
        {
            "origin_id": origin_ids,
            **b0_values,
            "b0_complete": [True] * len(rows),
            "b0_missing_reason": [None] * len(rows),
            "max_predictor_available_at_utc": [
                origin - timedelta(minutes=1) for _, _, origin in rows
            ],
        }
    )
    b1 = pl.DataFrame(
        {
            "origin_id": origin_ids,
            **{feature: [0.2] * len(rows) for feature in B1V3_FEATURES},
            "b1v3a_complete": [True] * len(rows),
            "b1v3b_complete": [True] * len(rows),
            "b1v3c_complete": [True] * len(rows),
            "max_sip_timestamp_ns": [
                int((origin - timedelta(minutes=1)).timestamp() * 1_000_000_000)
                for _, _, origin in rows
            ],
        }
    )
    b2 = pl.DataFrame(
        {
            "origin_id": origin_ids,
            **{feature: [0.3] * len(rows) for feature in B2_FEATURE_NAMES},
            "b2v2_availability_eligible": [True] * len(rows),
            "b2v2_availability_status": ["ELIGIBLE"] * len(rows),
            "source_temporal_state": ["ON_TIME"] * len(rows),
            "b2v2_max_created_at_utc": [origin - timedelta(minutes=1) for _, _, origin in rows],
            "b2v2_cutoff_utc": [origin - timedelta(minutes=1) for _, _, origin in rows],
        }
    )
    return sessions, origins, b0, b1, b2


def test_seal_derived_attempt_source_binds_inventory_and_cutoff(tmp_path: Path) -> None:
    attempts = tmp_path / "attempts.parquet"
    inventory = tmp_path / "inventory.parquet"
    output = tmp_path / "manifest.json"
    derivation = tmp_path / "derive.py"
    _attempt(attempts)
    inventory.write_bytes(b"inventory")
    derivation.write_text("# target blind\n", encoding="utf-8")
    document = seal_derived_attempt_source(
        variant="MASSIVE_CUTOFF_60_SECONDS",
        attempts_path=attempts,
        original_source=_source(inventory),
        derivation_summary={"attempt_count": 1, "future_quote_count": 0},
        quote_cutoff_seconds=60,
        fmp_delay_minutes=1,
        inventory_path=inventory,
        manifest_path=output,
        schema_path=ROOT / "specs/001-pit-options-rv30/contracts/"
        "b1-independent-replication-derived-b1q-source-v1.schema.json",
        derivation_code_path=derivation,
    )
    assert document["status"] == "PASS_TARGET_BLIND_B1Q_SOURCE_BOUND"
    assert document["outcome_read_count"] == 0
    derivation_document = cast(dict[str, Any], document["derivation"])
    assert derivation_document["quote_cutoff_seconds"] == 60
    assert json.loads(output.read_text(encoding="utf-8")) == document


def test_seal_derived_attempt_source_rejects_quote_after_shifted_cutoff(
    tmp_path: Path,
) -> None:
    attempts = tmp_path / "attempts.parquet"
    inventory = tmp_path / "inventory.parquet"
    derivation = tmp_path / "derive.py"
    _attempt(attempts, sip_timestamp=950_000_000_001)
    inventory.write_bytes(b"inventory")
    derivation.write_text("# target blind\n", encoding="utf-8")
    with pytest.raises(ValueError, match="B1_REPLICATION_TIMING_FUTURE_QUOTE"):
        seal_derived_attempt_source(
            variant="MASSIVE_CUTOFF_60_SECONDS",
            attempts_path=attempts,
            original_source=_source(inventory),
            derivation_summary={},
            quote_cutoff_seconds=60,
            fmp_delay_minutes=1,
            inventory_path=inventory,
            manifest_path=tmp_path / "manifest.json",
            schema_path=ROOT / "specs/001-pit-options-rv30/contracts/"
            "b1-independent-replication-derived-b1q-source-v1.schema.json",
            derivation_code_path=derivation,
        )


def test_finalize_timing_predictors_binds_every_variant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "mds650.b1_replication_timing.validate_confirmation_plan_schema",
        lambda document, schema: None,
    )
    prereg_path = tmp_path / "prereg.json"
    base_path = tmp_path / "base.json"
    source_path = tmp_path / "source.json"
    delay_path = tmp_path / "delay.json"
    inventory = tmp_path / "inventory.parquet"
    orchestrator = tmp_path / "build.py"
    inventory.write_bytes(b"inventory")
    orchestrator.write_text("# target blind\n", encoding="utf-8")
    for path, document in (
        (prereg_path, _hashed({"status": "FROZEN"})),
        (base_path, _hashed({"status": "PASS"})),
        (source_path, _hashed({"status": "PASS"})),
        (delay_path, _hashed({"status": "PASS"})),
    ):
        _write_document(path, document)
    variant_paths: dict[str, dict[str, Path]] = {}
    for variant in TIMING_VARIANTS:
        root = tmp_path / variant
        root.mkdir()
        attempts = root / "attempts.parquet"
        features = root / "features.parquet"
        coverage = root / "coverage.json"
        derived_path = root / "source.json"
        feature_manifest_path = root / "manifest.json"
        attempts.write_bytes(b"attempts")
        features.write_bytes(b"features")
        coverage.write_text("{}", encoding="utf-8")
        derived = _hashed({"status": "PASS", "variant": variant})
        feature_manifest = _hashed(
            {
                "status": "PASS",
                "provenance": {"source_binding_manifest_sha256": derived["manifest_sha256"]},
            }
        )
        _write_document(derived_path, derived)
        _write_document(feature_manifest_path, feature_manifest)
        variant_paths[variant] = {
            "attempts": attempts,
            "source": derived_path,
            "features": features,
            "coverage": coverage,
            "manifest": feature_manifest_path,
        }
    output = tmp_path / "timing_manifest.json"
    document = finalize_replication_timing_predictors(
        preregistration_path=prereg_path,
        base_manifest_path=base_path,
        source_manifest_path=source_path,
        source_inventory_path=inventory,
        fmp_delay2_manifest_path=delay_path,
        variant_paths=variant_paths,
        output_path=output,
        schema_path=tmp_path / "schema.json",
        orchestrator_code_path=orchestrator,
    )
    assert document["status"] == "PASS_TARGET_BLIND_TIMING_PREDICTORS"
    assert set(cast(dict[str, object], document["variants"])) == set(TIMING_VARIANTS)
    assert json.loads(output.read_text(encoding="utf-8")) == document


def test_materialize_timing_attempts_derives_all_registered_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "mds650.b1_replication_timing.validate_confirmation_plan_schema",
        lambda document, schema: None,
    )
    origins_path = tmp_path / "origins.parquet"
    bars_path = tmp_path / "bars.parquet"
    attempts_path = tmp_path / "primary-attempts.parquet"
    inventory_path = tmp_path / "inventory.parquet"
    derivation_path = tmp_path / "derive.py"
    pl.DataFrame({"origin_id": ["AAPL:1"]}).write_parquet(origins_path)
    pl.DataFrame({"bar": [1]}).write_parquet(bars_path)
    _attempt(attempts_path)
    inventory_path.write_bytes(b"inventory")
    derivation_path.write_text("# target blind\n", encoding="utf-8")

    prereg = _hashed(
        {
            "status": "FROZEN_BEFORE_PROVIDER_PAYLOAD",
            "replication_target_reads": 0,
            "result_sign_selection": "PROHIBITED",
        }
    )
    base = _hashed(
        {
            "status": "PASS_TARGET_BLIND_BASE_PREDICTORS",
            "preregistration_sha256": prereg["manifest_sha256"],
            "outputs": {
                "origins": {"sha256": sha256_file(origins_path)},
                "fmp_bars": {"sha256": sha256_file(bars_path)},
            },
        }
    )
    source = _hashed(
        {
            "status": "PASS_TARGET_BLIND_B1Q_SOURCE_BOUND",
            "preregistration_manifest_sha256": prereg["manifest_sha256"],
            "base_manifest_sha256": base["manifest_sha256"],
            "target_blind": True,
            "outcome_read_count": 0,
            "safe_to_read_outcomes": False,
            "scope": {"replication_session_count": 30, "asset_count": 6},
            "attempts": {"sha256": sha256_file(attempts_path)},
            "raw_payload_binding": {
                "status": "PRESENT_AND_VALIDATED",
                "inventory_sha256": sha256_file(inventory_path),
                "contract_day_count": 1,
            },
            "pit_invariants": {
                "future_selected_quote_rows": 0,
                "pagination_validated": True,
            },
            "security": {
                "secret_values_emitted": False,
                "personal_paths_emitted": False,
            },
        }
    )
    prereg_path = tmp_path / "prereg.json"
    base_path = tmp_path / "base.json"
    source_path = tmp_path / "source.json"
    _write_document(prereg_path, prereg)
    _write_document(base_path, base)
    _write_document(source_path, source)

    monkeypatch.setattr(
        "mds650.b1_replication_timing.build_spot_frame",
        lambda bars, origins, delay_minutes: pl.DataFrame(
            {"origin_id": ["AAPL:1"], "spot": [250.0], "spot_available": [True]}
        ),
    )

    def write_fmp(**kwargs: object) -> dict[str, object]:
        _attempt(cast(Path, kwargs["output_path"]))
        return {"attempt_count": 1, "future_quote_count": 0}

    def write_massive(**kwargs: object) -> dict[str, object]:
        outputs = cast(dict[int, Path], kwargs["output_paths"])
        for path in outputs.values():
            path.parent.mkdir(parents=True, exist_ok=True)
        _attempt(outputs[60], sip_timestamp=930_000_000_000)
        _attempt(outputs[300], sip_timestamp=690_000_000_000)
        return {
            "variants": {
                "60": {"attempt_count": 1, "future_quote_count": 0},
                "300": {"attempt_count": 1, "future_quote_count": 0},
            }
        }

    monkeypatch.setattr("mds650.b1_replication_timing.write_fmp_delayed_attempts", write_fmp)
    monkeypatch.setattr(
        "mds650.b1_replication_timing.write_massive_reselected_attempt_variants",
        write_massive,
    )
    result = materialize_replication_timing_attempts(
        preregistration_path=prereg_path,
        base_manifest_path=base_path,
        base_schema_path=tmp_path / "base.schema.json",
        source_manifest_path=source_path,
        source_schema_path=tmp_path / "source.schema.json",
        source_inventory_path=inventory_path,
        primary_attempts_path=attempts_path,
        origins_path=origins_path,
        fmp_bars_path=bars_path,
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "timing",
        derived_schema_path=tmp_path / "derived.schema.json",
        derivation_code_path=derivation_path,
    )
    assert set(result) == set(TIMING_VARIANTS)
    assert all(
        cast(Path, cast(dict[str, object], record)["attempts_path"]).is_file()
        for record in result.values()
    )


def test_build_timing_common_artifacts_preserves_all_registered_views(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "mds650.b1_replication_timing.validate_confirmation_plan_schema",
        lambda document, schema: None,
    )
    sessions, origins, b0, b1, b2 = _complete_frames()
    origins_path = tmp_path / "origins.parquet"
    b0_path = tmp_path / "b0.parquet"
    b1_path = tmp_path / "b1.parquet"
    b2_path = tmp_path / "b2.parquet"
    origins.write_parquet(origins_path)
    b0.write_parquet(b0_path)
    b1.write_parquet(b1_path)
    b2.write_parquet(b2_path)

    prereg = _hashed(
        {
            "status": "FROZEN_BEFORE_PROVIDER_PAYLOAD",
            "replication_target_reads": 0,
            "replication_sessions": sessions,
        }
    )
    primary = _hashed({"status": "PASS_TARGET_BLIND_COMMON_PREDICTOR_PANEL"})
    base = _hashed(
        {
            "status": "PASS_TARGET_BLIND_BASE_PREDICTORS",
            "outputs": {
                "origins": {"sha256": sha256_file(origins_path)},
                "b0": {"sha256": sha256_file(b0_path)},
            },
        }
    )
    b1_manifest = _hashed({"status": "PASS", "output": {"sha256": sha256_file(b1_path)}})
    delay = _hashed({"status": "PASS", "output": {"sha256": sha256_file(b0_path)}})
    timing = _hashed(
        {
            "status": "PASS_TARGET_BLIND_TIMING_PREDICTORS",
            "variants": {
                variant: {"features": {"sha256": sha256_file(b1_path)}}
                for variant in TIMING_VARIANTS
            },
        }
    )
    b2_manifest = _hashed(
        {
            "status": "PASS_TARGET_BLIND_B2_PREDICTORS",
            "variants": {
                variant: {"sha256": sha256_file(b2_path)}
                for variant in (
                    "primary_5m_60s",
                    "latency_5m_120s",
                    "latency_5m_300s",
                )
            },
        }
    )
    documents = {
        "prereg": prereg,
        "primary": primary,
        "base": base,
        "b1": b1_manifest,
        "delay": delay,
        "timing": timing,
        "b2": b2_manifest,
    }
    paths: dict[str, Path] = {}
    for name, document in documents.items():
        path = tmp_path / f"{name}.json"
        _write_document(path, document)
        paths[name] = path
    output_root = tmp_path / "common"
    manifest_path = tmp_path / "timing_common.json"
    result = build_replication_timing_common_artifacts(
        preregistration_path=paths["prereg"],
        primary_common_manifest_path=paths["primary"],
        base_manifest_path=paths["base"],
        base_schema_path=tmp_path / "base.schema.json",
        b1_feature_manifest_path=paths["b1"],
        b1_feature_schema_path=tmp_path / "b1.schema.json",
        fmp_delay2_manifest_path=paths["delay"],
        fmp_delay2_schema_path=tmp_path / "delay.schema.json",
        timing_predictor_manifest_path=paths["timing"],
        b2_manifest_path=paths["b2"],
        origins_path=origins_path,
        primary_b0_path=b0_path,
        fmp_delay2_b0_path=b0_path,
        primary_b1_path=b1_path,
        timing_b1_paths={variant: b1_path for variant in TIMING_VARIANTS},
        primary_b2_path=b2_path,
        uw_b2_paths={
            "UW_CREATED_AT_120_SECONDS": b2_path,
            "UW_CREATED_AT_300_SECONDS": b2_path,
        },
        output_root=output_root,
        manifest_path=manifest_path,
        schema_path=tmp_path / "timing-common.schema.json",
    )
    variants = cast(dict[str, Any], result["variants"])
    assert result["status"] == "PASS_TARGET_BLIND_TIMING_COMMON_PANELS"
    assert set(variants) == {
        *TIMING_VARIANTS,
        "UW_CREATED_AT_120_SECONDS",
        "UW_CREATED_AT_300_SECONDS",
    }
    assert all(
        cast(dict[str, Any], record["technical_acceptance"])["status"] == "PASS"
        for record in variants.values()
    )


@pytest.mark.parametrize(
    "schema_name",
    [
        "b1-independent-replication-derived-b1q-source-v1.schema.json",
        "b1-independent-replication-timing-predictors-v1.schema.json",
        "b1-independent-replication-timing-common-v1.schema.json",
    ],
)
def test_replication_timing_schema_is_valid(schema_name: str) -> None:
    schema = json.loads(
        (ROOT / "specs/001-pit-options-rv30/contracts" / schema_name).read_text(encoding="utf-8")
    )
    jsonschema: Any = import_module("jsonschema")
    jsonschema.Draft202012Validator.check_schema(schema)
