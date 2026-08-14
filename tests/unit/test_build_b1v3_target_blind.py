from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import jsonschema
import polars as pl
import pytest
from scripts.build_b1v3_target_blind import (
    BuildArtifacts,
    build_target_blind_package,
    canonical_sha256,
    sha256_file,
)

from mds650.b1v3 import B1V3_FEATURES

ROOT = Path(__file__).parents[2]
SCHEMA_PATH = (
    ROOT / "specs" / "001-pit-options-rv30" / "contracts" / "b1v3-target-blind-manifest.schema.json"
)
SOURCE_SCHEMA_PATH = (
    ROOT
    / "specs"
    / "001-pit-options-rv30"
    / "contracts"
    / "b1v3-confirmation-b1q-source-v1.schema.json"
)
SOURCE_BOUND_SCHEMA_PATH = (
    ROOT
    / "specs"
    / "001-pit-options-rv30"
    / "contracts"
    / "b1v3-target-blind-source-bound-manifest-v2.schema.json"
)


def _contract(*, expiry: date, strike: float, option_type: str) -> str:
    side = "C" if option_type == "call" else "P"
    strike_code = f"{round(strike * 1_000):08d}"
    return f"O:AAPL{expiry:%y%m%d}{side}{strike_code}"


def _attempts() -> pl.DataFrame:
    session = date(2025, 7, 7)
    first_origin = datetime(2025, 7, 7, 13, 35, tzinfo=UTC)
    expiry_geometry = (
        (date(2025, 7, 18), 11, (99.0, 101.0)),
        (date(2025, 8, 8), 32, (97.5, 99.0, 101.0, 102.5)),
        (date(2025, 10, 17), 102, (99.0, 101.0)),
    )
    rows: list[dict[str, object]] = []
    for origin_offset in range(7):
        origin = first_origin + timedelta(minutes=5 * origin_offset)
        origin_ns = int(origin.timestamp() * 1_000_000_000)
        for expiry, dte, strikes in expiry_geometry:
            for strike in strikes:
                for option_type in ("call", "put"):
                    contract = _contract(
                        expiry=expiry,
                        strike=strike,
                        option_type=option_type,
                    )
                    source_hash = hashlib.sha256(f"{session}|{contract}".encode()).hexdigest()
                    rows.append(
                        {
                            "contract": contract,
                            "expiry": expiry.isoformat(),
                            "strike": strike,
                            "option_type": option_type,
                            "dte": dte,
                            "bucket": "test",
                            "target_moneyness": strike / 100.0,
                            "reference_request_id": "reference-test",
                            "instrument_type": "equity",
                            "asset": "AAPL",
                            "session_date": session.isoformat(),
                            "origin_id": f"AAPL:{origin.isoformat()}",
                            "forecast_origin_utc": origin.isoformat(),
                            "forecast_origin_ns": origin_ns,
                            "spot": 100.0,
                            "moneyness": strike / 100.0,
                            "rate": 0.04,
                            "rate_source_date": "2025-07-03",
                            "dividend_yield": 0.005,
                            "dividend_assumption": "PRE_ORIGIN_TRAILING_DECLARATIONS",
                            "source_request_hash": source_hash,
                            "iv_success": True,
                            "iv": 0.20 + (abs(strike - 100.0) * 0.001),
                            "failure_reason": None,
                            "sip_timestamp": origin_ns - 1_000_000_000,
                            "bid": 1.0,
                            "ask": 1.1,
                            "quote_age_seconds": 1.0,
                            "relative_spread": 0.1 / 1.05,
                            "midpoint": 1.05,
                            "iterations": 12,
                            "lower_bound": 1e-6,
                            "upper_bound": 5.0,
                        }
                    )
    return pl.DataFrame(rows, infer_schema_length=None)


def _inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    attempts_path = tmp_path / "target_free_iv_attempts.parquet"
    design_path = tmp_path / "approved_b1v3_design.md"
    output_root = tmp_path / "package"
    _attempts().write_parquet(attempts_path)
    design_path.write_text("# Approved deterministic B1v3 design\n", encoding="utf-8")
    return attempts_path, design_path, output_root


def _build(tmp_path: Path) -> tuple[Path, Path, Path, BuildArtifacts]:
    attempts_path, design_path, output_root = _inputs(tmp_path)
    result = build_target_blind_package(
        input_path=attempts_path,
        design_path=design_path,
        output_root=output_root,
        manifest_schema_path=SCHEMA_PATH,
        quote_cutoff_seconds=0,
        minimum_free_gib=0.0,
        batch_size=17,
    )
    return attempts_path, design_path, output_root, result


def _source_binding(tmp_path: Path, attempts_path: Path) -> tuple[Path, Path]:
    inventory_path = tmp_path / "b1q_raw_payload_inventory.parquet"
    pl.DataFrame({"cache_file_sha256": ["e" * 64]}).write_parquet(inventory_path)
    attempts = pl.read_parquet(attempts_path)
    document: dict[str, object] = {
        "schema_version": "1.0",
        "status": "PASS_TARGET_BLIND_B1Q_SOURCE_BOUND",
        "plan_sha256": "a" * 64,
        "base_manifest_sha256": "b" * 64,
        "target_blind": True,
        "outcome_read_count": 0,
        "safe_to_read_outcomes": False,
        "scope": {
            "training_session_count": 1,
            "confirmation_session_count": 0,
            "session_count": 1,
            "asset_count": 6,
            "assets": ["AAPL", "AMZN", "META", "MSFT", "NVDA", "TSLA"],
            "origin_count": attempts["origin_id"].n_unique(),
            "origin_identity_sha256": "c" * 64,
        },
        "attempts": {
            "logical_path": (
                "MDS650_B1V3_DATA_ROOT/tmp/b1q_acquisition_v1/"
                "b1_iv_attempts_20d.parquet"
            ),
            "sha256": sha256_file(attempts_path),
            "bytes": attempts_path.stat().st_size,
            "row_count": attempts.height,
            "columns": attempts.columns,
            "unique_request_hash_count": attempts["source_request_hash"].n_unique(),
        },
        "contract_grid": {
            "logical_path": (
                "MDS650_B1V3_DATA_ROOT/cache/massive/"
                "resolved_contracts_b1v3_canonical_spot_v1.json"
            ),
            "schema_version": "b1q-contract-grid-3.0",
            "sha256": "d" * 64,
            "asset_day_count": 1,
            "contract_day_count": attempts["source_request_hash"].n_unique(),
        },
        "raw_payload_binding": {
            "status": "PRESENT_AND_VALIDATED",
            "inventory_logical_path": (
                "MDS650_B1V3_DATA_ROOT/evidence/b1q_raw_payload_inventory.parquet"
            ),
            "inventory_sha256": sha256_file(inventory_path),
            "contract_day_count": attempts["source_request_hash"].n_unique(),
            "cache_bytes": 1,
            "quote_row_count": 1,
            "cache_schema_version": 4,
            "route": "B1Q",
        },
        "pit_invariants": {
            "future_selected_quote_rows": 0,
            "rate_source_strictly_pre_session": True,
            "request_scope_validated": True,
            "pagination_validated": True,
            "duplicate_attempt_identities": 0,
            "duplicate_payload_hashes": 0,
        },
        "security": {
            "secret_values_emitted": False,
            "personal_paths_emitted": False,
        },
    }
    document["manifest_sha256"] = canonical_sha256(document)
    manifest_path = tmp_path / "b1q_source_manifest.json"
    manifest_path.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest_path, inventory_path


def test_build_binds_sources_validates_schema_and_stays_target_blind(
    tmp_path: Path,
) -> None:
    attempts_path, design_path, output_root, result = _build(tmp_path)

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(manifest, schema)

    assert manifest["source"]["sha256"] == sha256_file(attempts_path)
    assert manifest["design"]["sha256"] == sha256_file(design_path)
    assert manifest["manifest_sha256"] == canonical_sha256(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    )
    assert manifest["status"] == "PASS_TARGET_BLIND_TECHNICAL_BUILD"
    assert manifest["safe_to_evaluate_scientifically"] is False
    assert manifest["provenance"]["exogenous_raw_payload_binding"] == "UNRESOLVED"
    assert tuple(manifest["feature_contract"]["features"]) == B1V3_FEATURES
    assert manifest["output"]["row_count"] == 7
    assert manifest["output"]["origin_count"] == 7
    assert result.features_path.parent == output_root

    rendered = json.dumps(manifest, sort_keys=True)
    assert str(tmp_path) not in rendered
    assert "C:\\Users\\" not in rendered
    assert "api_key" not in rendered.lower()
    feature_columns = set(pl.read_parquet(result.features_path).columns)
    assert not {"rv30", "qlike", "prediction", "outcome"} & feature_columns


def test_source_bound_build_resolves_raw_payload_blocker(tmp_path: Path) -> None:
    attempts_path, design_path, output_root = _inputs(tmp_path)
    source_manifest, source_inventory = _source_binding(tmp_path, attempts_path)

    result = build_target_blind_package(
        input_path=attempts_path,
        design_path=design_path,
        output_root=output_root,
        manifest_schema_path=SOURCE_BOUND_SCHEMA_PATH,
        source_binding_manifest_path=source_manifest,
        source_binding_schema_path=SOURCE_SCHEMA_PATH,
        source_inventory_path=source_inventory,
        quote_cutoff_seconds=0,
        minimum_free_gib=0.0,
        batch_size=17,
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    jsonschema.validate(
        manifest,
        json.loads(SOURCE_BOUND_SCHEMA_PATH.read_text(encoding="utf-8")),
    )
    assert manifest["schema_version"] == "2.0"
    assert manifest["status"] == "PASS_TARGET_BLIND_SOURCE_BOUND_TECHNICAL_BUILD"
    assert manifest["provenance"]["exogenous_raw_payload_binding"] == (
        "PRESENT_AND_VALIDATED"
    )
    assert manifest["provenance"]["evaluation_blocker"] is None
    assert manifest["provenance"]["source_binding_manifest_sha256"] == (
        json.loads(source_manifest.read_text(encoding="utf-8"))["manifest_sha256"]
    )
    assert manifest["safe_to_evaluate_scientifically"] is False


def test_source_bound_build_rejects_inventory_hash_drift(tmp_path: Path) -> None:
    attempts_path, design_path, output_root = _inputs(tmp_path)
    source_manifest, source_inventory = _source_binding(tmp_path, attempts_path)
    pl.DataFrame({"tampered": [1]}).write_parquet(source_inventory)

    with pytest.raises(ValueError, match="B1V3_SOURCE_BINDING_INVENTORY_HASH_INVALID"):
        build_target_blind_package(
            input_path=attempts_path,
            design_path=design_path,
            output_root=output_root,
            manifest_schema_path=SOURCE_BOUND_SCHEMA_PATH,
            source_binding_manifest_path=source_manifest,
            source_binding_schema_path=SOURCE_SCHEMA_PATH,
            source_inventory_path=source_inventory,
            minimum_free_gib=0.0,
        )


def test_build_is_byte_identical_on_rerun(tmp_path: Path) -> None:
    attempts_path, design_path, output_root, first = _build(tmp_path)
    before = {
        path.name: sha256_file(path)
        for path in (
            first.features_path,
            first.coverage_path,
            first.manifest_path,
        )
    }

    second = build_target_blind_package(
        input_path=attempts_path,
        design_path=design_path,
        output_root=output_root,
        manifest_schema_path=SCHEMA_PATH,
        quote_cutoff_seconds=0,
        minimum_free_gib=0.0,
        batch_size=11,
    )
    after = {
        path.name: sha256_file(path)
        for path in (
            second.features_path,
            second.coverage_path,
            second.manifest_path,
        )
    }
    assert before == after


def test_build_refuses_conflicting_existing_output(tmp_path: Path) -> None:
    attempts_path, design_path, output_root, result = _build(tmp_path)
    result.coverage_path.write_text('{"tampered":true}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="B1V3_OUTPUT_CONFLICT"):
        build_target_blind_package(
            input_path=attempts_path,
            design_path=design_path,
            output_root=output_root,
            manifest_schema_path=SCHEMA_PATH,
            quote_cutoff_seconds=0,
            minimum_free_gib=0.0,
            batch_size=19,
        )


def test_build_rejects_result_like_input_path(tmp_path: Path) -> None:
    attempts_path, design_path, output_root = _inputs(tmp_path)
    forbidden = tmp_path / "rv30_results.parquet"
    shutil.copyfile(attempts_path, forbidden)

    with pytest.raises(ValueError, match="B1V3_FORBIDDEN_INPUT_PATH"):
        build_target_blind_package(
            input_path=forbidden,
            design_path=design_path,
            output_root=output_root,
            manifest_schema_path=SCHEMA_PATH,
            quote_cutoff_seconds=0,
            minimum_free_gib=0.0,
        )


def test_build_enforces_disk_gate_before_writes(tmp_path: Path) -> None:
    attempts_path, design_path, output_root = _inputs(tmp_path)

    with pytest.raises(ValueError, match="B1V3_DISK_GATE_FAILED"):
        build_target_blind_package(
            input_path=attempts_path,
            design_path=design_path,
            output_root=output_root,
            manifest_schema_path=SCHEMA_PATH,
            quote_cutoff_seconds=0,
            minimum_free_gib=10**12,
        )
    assert not output_root.exists()


def test_build_rejects_noncontiguous_asset_day_source(tmp_path: Path) -> None:
    attempts_path, design_path, output_root = _inputs(tmp_path)
    attempts = pl.read_parquet(attempts_path)
    first = attempts.head(1)
    middle = attempts.head(1).with_columns(
        pl.lit("AMZN").alias("asset"),
        pl.lit("AMZN:2025-07-07T13:35:00+00:00").alias("origin_id"),
    )
    pl.concat([first, middle, attempts.slice(1)]).write_parquet(attempts_path)

    with pytest.raises(ValueError, match="B1V3_SOURCE_ORDER_NOT_CONTIGUOUS"):
        build_target_blind_package(
            input_path=attempts_path,
            design_path=design_path,
            output_root=output_root,
            manifest_schema_path=SCHEMA_PATH,
            quote_cutoff_seconds=0,
            minimum_free_gib=0.0,
            batch_size=13,
        )
