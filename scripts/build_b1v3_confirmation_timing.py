"""Build source-bound target-blind B1v3 provider-timing sensitivity inputs."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from build_b1v3_target_blind import BuildArtifacts, build_target_blind_package  # noqa: E402

from mds650.b1v3_confirmation import (  # noqa: E402
    canonical_sha256,
    sha256_file,
    validate_confirmation_plan_schema,
)
from mds650.b1v3_confirmation_panel import (  # noqa: E402
    build_b0_target_blind,
    build_spot_frame,
)
from mds650.b1v3_massive_sensitivity import (  # noqa: E402
    write_fmp_delayed_attempts,
    write_massive_reselected_attempt_variants,
)

_FORBIDDEN_SERIALIZED = (
    b"c:\\users\\",
    b"c:/users/",
    b"d:\\mds650",
    b"api_key",
    b"apikey",
    b"authorization",
    b"bearer ",
)


def _json_object(path: Path, *, code: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(code) from exc
    if not isinstance(value, dict):
        raise ValueError(code)
    return value


def _validate_self_hash(document: Mapping[str, Any], *, code: str) -> None:
    stored = document.get("manifest_sha256")
    unsigned = {key: value for key, value in document.items() if key != "manifest_sha256"}
    if not isinstance(stored, str) or stored != canonical_sha256(unsigned):
        raise ValueError(code)


def _pretty_json(document: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(document, ensure_ascii=True, allow_nan=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _write_bytes_if_identical(path: Path, payload: bytes, *, code: str) -> str:
    if any(token in payload.lower() for token in _FORBIDDEN_SERIALIZED):
        raise ValueError("B1V3_TIMING_OUTPUT_HYGIENE_INVALID")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise ValueError(f"{code}:{path.name}")
        return sha256_file(path)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".part", dir=path.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return sha256_file(path)


def _write_parquet_if_identical(frame: pl.DataFrame, path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".b1v3-timing-", dir=path.parent) as name:
        candidate = Path(name) / path.name
        frame.write_parquet(candidate, compression="zstd", statistics=True)
        candidate_hash = sha256_file(candidate)
        if path.exists():
            if sha256_file(path) != candidate_hash:
                raise ValueError(f"B1V3_TIMING_OUTPUT_CONFLICT:{path.name}")
            return candidate_hash
        os.replace(candidate, path)
    return candidate_hash


def _file_record(path: Path, logical_path: str) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size <= 0:
        raise ValueError("B1V3_TIMING_OUTPUT_MISSING")
    return {
        "logical_path": logical_path,
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
    }


def _validate_sources(
    *,
    primary_attempts_path: Path,
    source_manifest_path: Path,
    source_manifest_schema_path: Path,
    source_inventory_path: Path,
    base_manifest_path: Path,
    base_manifest_schema_path: Path,
    origins_path: Path,
    fmp_bars_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    source = _json_object(source_manifest_path, code="B1V3_TIMING_B1_SOURCE_INVALID")
    base = _json_object(base_manifest_path, code="B1V3_TIMING_BASE_SOURCE_INVALID")
    validate_confirmation_plan_schema(source, source_manifest_schema_path)
    validate_confirmation_plan_schema(base, base_manifest_schema_path)
    _validate_self_hash(source, code="B1V3_TIMING_B1_SOURCE_HASH_INVALID")
    _validate_self_hash(base, code="B1V3_TIMING_BASE_SOURCE_HASH_INVALID")
    attempts = source.get("attempts")
    raw = source.get("raw_payload_binding")
    outputs = base.get("outputs")
    origins = outputs.get("origins") if isinstance(outputs, dict) else None
    bars = outputs.get("fmp_bars") if isinstance(outputs, dict) else None
    if (
        source.get("status") != "PASS_TARGET_BLIND_B1Q_SOURCE_BOUND"
        or source.get("target_blind") is not True
        or source.get("outcome_read_count") != 0
        or source.get("safe_to_read_outcomes") is not False
        or not isinstance(attempts, dict)
        or attempts.get("sha256") != sha256_file(primary_attempts_path)
        or not isinstance(raw, dict)
        or raw.get("status") != "PRESENT_AND_VALIDATED"
        or raw.get("inventory_sha256") != sha256_file(source_inventory_path)
        or base.get("status") != "PASS_TARGET_BLIND_BASE_PREDICTORS"
        or base.get("target_blind") is not True
        or base.get("outcome_read_count") != 0
        or base.get("safe_to_read_outcomes") is not False
        or source.get("plan_sha256") != base.get("plan_sha256")
        or not isinstance(origins, dict)
        or origins.get("sha256") != sha256_file(origins_path)
        or not isinstance(bars, dict)
        or bars.get("sha256") != sha256_file(fmp_bars_path)
    ):
        raise ValueError("B1V3_TIMING_SOURCE_BINDING_INVALID")
    return source, base


def _checkpoint(
    *,
    path: Path,
    kind: str,
    input_sha256: str,
    summary: Mapping[str, Any],
    outputs: Mapping[str, Path],
) -> dict[str, Any]:
    records = {
        name: {"sha256": sha256_file(output), "bytes": output.stat().st_size}
        for name, output in sorted(outputs.items())
    }
    if path.exists():
        existing = _json_object(path, code="B1V3_TIMING_CHECKPOINT_INVALID")
        _validate_self_hash(existing, code="B1V3_TIMING_CHECKPOINT_HASH_INVALID")
        if (
            existing.get("kind") != kind
            or existing.get("input_sha256") != input_sha256
            or existing.get("outputs") != records
        ):
            raise ValueError("B1V3_TIMING_CHECKPOINT_BINDING_INVALID")
        saved = existing.get("summary")
        if not isinstance(saved, dict):
            raise ValueError("B1V3_TIMING_CHECKPOINT_INVALID")
        return saved
    document: dict[str, Any] = {
        "schema_version": "1.0",
        "kind": kind,
        "input_sha256": input_sha256,
        "summary": dict(summary),
        "outputs": records,
        "target_blind": True,
        "outcome_read_count": 0,
    }
    document["manifest_sha256"] = canonical_sha256(document)
    _write_bytes_if_identical(
        path,
        _pretty_json(document),
        code="B1V3_TIMING_CHECKPOINT_CONFLICT",
    )
    return dict(summary)


def _technical_record(
    build: BuildArtifacts,
    *,
    logical_root: str,
) -> dict[str, Any]:
    return {
        "features": _file_record(
            build.features_path, f"{logical_root}/features/b1v3_features.parquet"
        ),
        "coverage": _file_record(
            build.coverage_path, f"{logical_root}/features/b1v3_coverage.json"
        ),
        "manifest": _file_record(
            build.manifest_path, f"{logical_root}/features/b1v3_manifest.json"
        ),
    }


def build_timing_predictor_package(
    *,
    primary_attempts_path: Path,
    cache_root: Path,
    source_manifest_path: Path,
    source_manifest_schema_path: Path,
    source_inventory_path: Path,
    base_manifest_path: Path,
    base_manifest_schema_path: Path,
    origins_path: Path,
    fmp_bars_path: Path,
    design_path: Path,
    target_blind_manifest_schema_path: Path,
    timing_manifest_schema_path: Path,
    output_root: Path,
    manifest_path: Path,
    minimum_free_gib: float = 80.0,
    batch_size: int = 65_536,
) -> dict[str, Any]:
    """Build all registered predictor-only FMP and Massive timing variants."""
    source, base = _validate_sources(
        primary_attempts_path=primary_attempts_path,
        source_manifest_path=source_manifest_path,
        source_manifest_schema_path=source_manifest_schema_path,
        source_inventory_path=source_inventory_path,
        base_manifest_path=base_manifest_path,
        base_manifest_schema_path=base_manifest_schema_path,
        origins_path=origins_path,
        fmp_bars_path=fmp_bars_path,
    )
    if not design_path.is_file():
        raise ValueError("B1V3_TIMING_DESIGN_MISSING")
    origins = pl.read_parquet(origins_path)
    bars = pl.read_parquet(fmp_bars_path)
    fmp_root = output_root / "fmp_delay_2"
    fmp_spots_path = fmp_root / "spots.parquet"
    fmp_b0_path = fmp_root / "b0.parquet"
    fmp_attempts_path = fmp_root / "attempts.parquet"
    fmp_checkpoint = fmp_root / "derivation_checkpoint.json"
    spots = build_spot_frame(bars, origins, delay_minutes=2)
    if spots.filter(~pl.col("spot_available")).height:
        raise ValueError("B1V3_TIMING_FMP_SPOT_COVERAGE_INVALID")
    b0 = build_b0_target_blind(bars, origins, delay_minutes=2)
    _write_parquet_if_identical(spots, fmp_spots_path)
    _write_parquet_if_identical(b0, fmp_b0_path)
    if fmp_checkpoint.exists():
        fmp_summary = _checkpoint(
            path=fmp_checkpoint,
            kind="FMP_DELAY_2_MINUTES",
            input_sha256=sha256_file(primary_attempts_path),
            summary={},
            outputs={"attempts": fmp_attempts_path},
        )
    else:
        fmp_summary = write_fmp_delayed_attempts(
            attempts_path=primary_attempts_path,
            delayed_spots_path=fmp_spots_path,
            output_path=fmp_attempts_path,
            delay_minutes=2,
            batch_size=batch_size,
        )
        _checkpoint(
            path=fmp_checkpoint,
            kind="FMP_DELAY_2_MINUTES",
            input_sha256=sha256_file(primary_attempts_path),
            summary=fmp_summary,
            outputs={"attempts": fmp_attempts_path},
        )

    massive_root = output_root / "massive"
    massive_outputs = {
        60: massive_root / "cutoff_60" / "attempts.parquet",
        300: massive_root / "cutoff_300" / "attempts.parquet",
    }
    massive_checkpoint = massive_root / "derivation_checkpoint.json"
    if massive_checkpoint.exists():
        massive_summary = _checkpoint(
            path=massive_checkpoint,
            kind="MASSIVE_CUTOFFS_60_300_SECONDS",
            input_sha256=sha256_file(primary_attempts_path),
            summary={},
            outputs={str(key): value for key, value in massive_outputs.items()},
        )
    else:
        massive_summary = write_massive_reselected_attempt_variants(
            attempts_path=primary_attempts_path,
            cache_root=cache_root,
            output_paths=massive_outputs,
            batch_size=batch_size,
        )
        _checkpoint(
            path=massive_checkpoint,
            kind="MASSIVE_CUTOFFS_60_300_SECONDS",
            input_sha256=sha256_file(primary_attempts_path),
            summary=massive_summary,
            outputs={str(key): value for key, value in massive_outputs.items()},
        )

    builds = {
        "FMP_DELAY_2_MINUTES": build_target_blind_package(
            input_path=fmp_attempts_path,
            design_path=design_path,
            output_root=fmp_root / "features",
            manifest_schema_path=target_blind_manifest_schema_path,
            quote_cutoff_seconds=0,
            minimum_free_gib=minimum_free_gib,
            batch_size=batch_size,
        ),
        "MASSIVE_CUTOFF_60_SECONDS": build_target_blind_package(
            input_path=massive_outputs[60],
            design_path=design_path,
            output_root=massive_root / "cutoff_60" / "features",
            manifest_schema_path=target_blind_manifest_schema_path,
            quote_cutoff_seconds=60,
            minimum_free_gib=minimum_free_gib,
            batch_size=batch_size,
        ),
        "MASSIVE_CUTOFF_300_SECONDS": build_target_blind_package(
            input_path=massive_outputs[300],
            design_path=design_path,
            output_root=massive_root / "cutoff_300" / "features",
            manifest_schema_path=target_blind_manifest_schema_path,
            quote_cutoff_seconds=300,
            minimum_free_gib=minimum_free_gib,
            batch_size=batch_size,
        ),
    }
    source_hash = sha256_file(primary_attempts_path)
    massive_variants = massive_summary.get("variants")
    if not isinstance(massive_variants, dict):
        raise ValueError("B1V3_TIMING_MASSIVE_SUMMARY_INVALID")
    fmp_logical = "MDS650_B1V3_DATA_ROOT/predictors/timing/fmp_delay_2"
    massive_logical = "MDS650_B1V3_DATA_ROOT/predictors/timing/massive"
    document: dict[str, Any] = {
        "schema_version": "1.0",
        "status": "PASS_TARGET_BLIND_TIMING_PREDICTORS",
        "target_blind": True,
        "outcome_read_count": 0,
        "safe_to_read_outcomes": False,
        "source_bindings": {
            "plan_sha256": str(source["plan_sha256"]),
            "base_manifest_sha256": str(base["manifest_sha256"]),
            "b1q_source_manifest_sha256": str(source["manifest_sha256"]),
            "primary_attempts_sha256": source_hash,
            "source_inventory_sha256": sha256_file(source_inventory_path),
            "fmp_bars_sha256": sha256_file(fmp_bars_path),
            "origins_sha256": sha256_file(origins_path),
            "design_sha256": sha256_file(design_path),
            "builder_code_sha256": sha256_file(ROOT / "scripts" / "build_b1v3_target_blind.py"),
            "reselection_code_sha256": sha256_file(
                ROOT / "src" / "mds650" / "b1v3_massive_sensitivity.py"
            ),
            "orchestrator_code_sha256": sha256_file(Path(__file__)),
        },
        "variants": {
            "FMP_DELAY_2_MINUTES": {
                "fmp_delay_minutes": 2,
                "spots": _file_record(fmp_spots_path, f"{fmp_logical}/spots.parquet"),
                "b0": _file_record(fmp_b0_path, f"{fmp_logical}/b0.parquet"),
                "attempts": _file_record(fmp_attempts_path, f"{fmp_logical}/attempts.parquet"),
                "attempt_count": int(fmp_summary["attempt_count"]),
                "origin_count": int(fmp_summary["origin_count"]),
                "technical_build": _technical_record(
                    builds["FMP_DELAY_2_MINUTES"], logical_root=fmp_logical
                ),
            },
            "MASSIVE_CUTOFF_60_SECONDS": {
                "quote_cutoff_seconds": 60,
                "attempts": _file_record(
                    massive_outputs[60], f"{massive_logical}/cutoff_60/attempts.parquet"
                ),
                "attempt_count": int(massive_summary["attempt_count"]),
                "cache_decode_count": int(massive_summary["cache_decode_count"]),
                "future_selected_quote_count": 0,
                "technical_build": _technical_record(
                    builds["MASSIVE_CUTOFF_60_SECONDS"],
                    logical_root=f"{massive_logical}/cutoff_60",
                ),
            },
            "MASSIVE_CUTOFF_300_SECONDS": {
                "quote_cutoff_seconds": 300,
                "attempts": _file_record(
                    massive_outputs[300], f"{massive_logical}/cutoff_300/attempts.parquet"
                ),
                "attempt_count": int(massive_summary["attempt_count"]),
                "cache_decode_count": int(massive_summary["cache_decode_count"]),
                "future_selected_quote_count": 0,
                "technical_build": _technical_record(
                    builds["MASSIVE_CUTOFF_300_SECONDS"],
                    logical_root=f"{massive_logical}/cutoff_300",
                ),
            },
        },
        "security": {
            "secret_values_emitted": False,
            "personal_paths_emitted": False,
        },
    }
    for cutoff in ("60", "300"):
        if not isinstance(massive_variants.get(cutoff), dict):
            raise ValueError("B1V3_TIMING_MASSIVE_SUMMARY_INVALID")
    document["manifest_sha256"] = canonical_sha256(document)
    validate_confirmation_plan_schema(document, timing_manifest_schema_path)
    _write_bytes_if_identical(
        manifest_path,
        _pretty_json(document),
        code="B1V3_TIMING_MANIFEST_CONFLICT",
    )
    return document


def _arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    contracts = ROOT / "specs" / "001-pit-options-rv30" / "contracts"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--primary-attempts",
        type=Path,
        default=Path(
            "D:/MDS650/b1v3_confirmation/tmp/b1q_acquisition_v1/b1_iv_attempts_20d.parquet"
        ),
    )
    parser.add_argument(
        "--cache-root",
        type=Path,
        default=Path("D:/MDS650/b1v3_confirmation/cache/massive"),
    )
    parser.add_argument(
        "--source-manifest",
        type=Path,
        default=ROOT / "artifacts" / "b1v3_confirmation_panel" / "b1q_source_manifest.json",
    )
    parser.add_argument(
        "--source-schema",
        type=Path,
        default=contracts / "b1v3-confirmation-b1q-source-v1.schema.json",
    )
    parser.add_argument(
        "--source-inventory",
        type=Path,
        default=Path("D:/MDS650/b1v3_confirmation/evidence/b1q_raw_payload_inventory.parquet"),
    )
    parser.add_argument(
        "--base-manifest",
        type=Path,
        default=ROOT / "artifacts" / "b1v3_confirmation_panel" / "base_predictor_manifest.json",
    )
    parser.add_argument(
        "--base-schema",
        type=Path,
        default=contracts / "b1v3-confirmation-base-predictors-v1.schema.json",
    )
    parser.add_argument(
        "--origins",
        type=Path,
        default=Path(
            "D:/MDS650/b1v3_confirmation/predictors/forecast_origins_target_blind.parquet"
        ),
    )
    parser.add_argument(
        "--fmp-bars",
        type=Path,
        default=Path("D:/MDS650/b1v3_confirmation/predictors/underlying_1min_target_blind.parquet"),
    )
    parser.add_argument(
        "--design",
        type=Path,
        default=ROOT
        / "docs"
        / "superpowers"
        / "specs"
        / "2026-08-14-b1v3-target-blind-replication-design.md",
    )
    parser.add_argument(
        "--target-blind-schema",
        type=Path,
        default=contracts / "b1v3-target-blind-manifest.schema.json",
    )
    parser.add_argument(
        "--timing-schema",
        type=Path,
        default=contracts / "b1v3-confirmation-timing-predictors-v1.schema.json",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("D:/MDS650/b1v3_confirmation/predictors/timing"),
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "artifacts" / "b1v3_confirmation_panel" / "timing_predictor_manifest.json",
    )
    parser.add_argument("--minimum-free-gib", type=float, default=80.0)
    parser.add_argument("--batch-size", type=int, default=65_536)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Build the timing package and print only sanitized identities."""
    args = _arguments(argv)
    document = build_timing_predictor_package(
        primary_attempts_path=args.primary_attempts,
        cache_root=args.cache_root,
        source_manifest_path=args.source_manifest,
        source_manifest_schema_path=args.source_schema,
        source_inventory_path=args.source_inventory,
        base_manifest_path=args.base_manifest,
        base_manifest_schema_path=args.base_schema,
        origins_path=args.origins,
        fmp_bars_path=args.fmp_bars,
        design_path=args.design,
        target_blind_manifest_schema_path=args.target_blind_schema,
        timing_manifest_schema_path=args.timing_schema,
        output_root=args.output_root,
        manifest_path=args.manifest,
        minimum_free_gib=args.minimum_free_gib,
        batch_size=args.batch_size,
    )
    print(
        json.dumps(
            {
                "status": document["status"],
                "manifest_sha256": document["manifest_sha256"],
                "outcome_read_count": document["outcome_read_count"],
                "safe_to_read_outcomes": document["safe_to_read_outcomes"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
