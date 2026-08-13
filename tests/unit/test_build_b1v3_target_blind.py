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
