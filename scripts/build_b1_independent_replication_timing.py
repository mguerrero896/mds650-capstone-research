"""Build all preregistered target-blind timing views for the replication."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from build_b1v3_target_blind import build_target_blind_package  # noqa: E402

from mds650.b1_replication_timing import (  # noqa: E402
    build_replication_timing_common_artifacts,
    finalize_replication_timing_predictors,
    materialize_replication_timing_attempts,
)


def _arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    data = Path("D:/MDS650/b1_diagnostic_replication")
    contracts = ROOT / "specs/001-pit-options-rv30/contracts"
    panel_artifacts = ROOT / "artifacts/b1_diagnostic_replication/panel"
    parser.add_argument(
        "--preregistration",
        type=Path,
        default=ROOT / "artifacts/b1_diagnostic_replication/preregistration/preregistration.json",
    )
    parser.add_argument(
        "--base-manifest", type=Path, default=panel_artifacts / "base_predictor_manifest.json"
    )
    parser.add_argument(
        "--base-schema",
        type=Path,
        default=contracts / "b1-independent-replication-base-v1.schema.json",
    )
    parser.add_argument(
        "--source-manifest", type=Path, default=panel_artifacts / "b1q_source_manifest.json"
    )
    parser.add_argument(
        "--source-schema",
        type=Path,
        default=contracts / "b1-independent-replication-b1q-source-v1.schema.json",
    )
    parser.add_argument(
        "--source-inventory",
        type=Path,
        default=data / "evidence/b1q_raw_payload_inventory.parquet",
    )
    parser.add_argument(
        "--primary-attempts",
        type=Path,
        default=data / "tmp/b1q_acquisition_v1/b1_iv_attempts_20d.parquet",
    )
    parser.add_argument(
        "--origins",
        type=Path,
        default=data / "predictors/forecast_origins_target_blind.parquet",
    )
    parser.add_argument(
        "--fmp-bars",
        type=Path,
        default=data / "predictors/underlying_1min_target_blind.parquet",
    )
    parser.add_argument("--cache-root", type=Path, default=data / "cache/massive")
    parser.add_argument(
        "--design",
        type=Path,
        default=ROOT
        / "docs/superpowers/specs/2026-08-15-b1-diagnosis-independent-replication-design.md",
    )
    parser.add_argument(
        "--derived-source-schema",
        type=Path,
        default=contracts / "b1-independent-replication-derived-b1q-source-v1.schema.json",
    )
    parser.add_argument(
        "--b1-feature-schema",
        type=Path,
        default=contracts / "b1v3-target-blind-source-bound-manifest-v2.schema.json",
    )
    parser.add_argument(
        "--timing-predictor-schema",
        type=Path,
        default=contracts / "b1-independent-replication-timing-predictors-v1.schema.json",
    )
    parser.add_argument(
        "--timing-common-schema",
        type=Path,
        default=contracts / "b1-independent-replication-timing-common-v1.schema.json",
    )
    parser.add_argument(
        "--fmp-delay2-manifest",
        type=Path,
        default=panel_artifacts / "b0_delay2_manifest.json",
    )
    parser.add_argument(
        "--b2-manifest", type=Path, default=panel_artifacts / "b2_predictor_manifest.json"
    )
    parser.add_argument(
        "--primary-common-manifest",
        type=Path,
        default=panel_artifacts / "common_predictor_manifest.json",
    )
    parser.add_argument("--output-root", type=Path, default=data / "predictors/timing")
    parser.add_argument(
        "--timing-predictor-manifest",
        type=Path,
        default=panel_artifacts / "timing_predictor_manifest.json",
    )
    parser.add_argument(
        "--timing-common-manifest",
        type=Path,
        default=panel_artifacts / "timing_common_manifest.json",
    )
    parser.add_argument("--minimum-free-gib", type=float, default=80.0)
    parser.add_argument("--batch-size", type=int, default=65_536)
    parser.add_argument(
        "--resume-from-timing-predictors",
        action="store_true",
        help=(
            "Reuse already sealed timing predictor artifacts and rebuild only "
            "the downstream common panels. All hashes are revalidated."
        ),
    )
    return parser.parse_args(argv)


def _path(record: Mapping[str, Any], key: str) -> Path:
    value = record.get(key)
    if not isinstance(value, Path):
        raise ValueError("B1_REPLICATION_TIMING_INTERNAL_PATH_INVALID")
    return value


def _existing_variant_paths(output_root: Path) -> dict[str, dict[str, Path]]:
    roots = {
        "FMP_DELAY_2_MINUTES": output_root / "fmp_delay_2",
        "MASSIVE_CUTOFF_60_SECONDS": output_root / "massive/cutoff_60",
        "MASSIVE_CUTOFF_300_SECONDS": output_root / "massive/cutoff_300",
    }
    result: dict[str, dict[str, Path]] = {}
    for variant, root in roots.items():
        record = {
            "attempts": root / "attempts.parquet",
            "source": root / "derived_source_manifest.json",
            "features": root / "features/b1v3_features.parquet",
            "coverage": root / "features/b1v3_coverage.json",
            "manifest": root / "features/b1v3_manifest.json",
        }
        if not all(path.is_file() for path in record.values()):
            raise ValueError(f"B1_REPLICATION_TIMING_RESUME_INPUT_MISSING:{variant}")
        result[variant] = record
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = _arguments(argv)
    contracts = ROOT / "specs/001-pit-options-rv30/contracts"
    if args.resume_from_timing_predictors:
        variant_paths = _existing_variant_paths(args.output_root)
        decoded = json.loads(args.timing_predictor_manifest.read_text(encoding="utf-8"))
        if not isinstance(decoded, dict):
            raise ValueError("B1_REPLICATION_TIMING_RESUME_MANIFEST_INVALID")
        predictor_manifest = decoded
    else:
        materialized = materialize_replication_timing_attempts(
            preregistration_path=args.preregistration,
            base_manifest_path=args.base_manifest,
            base_schema_path=args.base_schema,
            source_manifest_path=args.source_manifest,
            source_schema_path=args.source_schema,
            source_inventory_path=args.source_inventory,
            primary_attempts_path=args.primary_attempts,
            origins_path=args.origins,
            fmp_bars_path=args.fmp_bars,
            cache_root=args.cache_root,
            output_root=args.output_root,
            derived_schema_path=args.derived_source_schema,
            derivation_code_path=ROOT / "src/mds650/b1v3_massive_sensitivity.py",
            batch_size=args.batch_size,
        )
        variant_paths = {}
        variant_cutoffs = {
            "FMP_DELAY_2_MINUTES": 0,
            "MASSIVE_CUTOFF_60_SECONDS": 60,
            "MASSIVE_CUTOFF_300_SECONDS": 300,
        }
        for variant, cutoff in variant_cutoffs.items():
            record = cast(Mapping[str, Any], materialized[variant])
            attempts_path = _path(record, "attempts_path")
            source_path = _path(record, "source_manifest_path")
            feature_root = attempts_path.parent / "features"
            build = build_target_blind_package(
                input_path=attempts_path,
                design_path=args.design,
                output_root=feature_root,
                manifest_schema_path=args.b1_feature_schema,
                source_binding_manifest_path=source_path,
                source_binding_schema_path=args.derived_source_schema,
                source_inventory_path=args.source_inventory,
                quote_cutoff_seconds=cutoff,
                minimum_free_gib=args.minimum_free_gib,
                batch_size=args.batch_size,
            )
            variant_paths[variant] = {
                "attempts": attempts_path,
                "source": source_path,
                "features": build.features_path,
                "coverage": build.coverage_path,
                "manifest": build.manifest_path,
            }
        predictor_manifest = finalize_replication_timing_predictors(
            preregistration_path=args.preregistration,
            base_manifest_path=args.base_manifest,
            source_manifest_path=args.source_manifest,
            source_inventory_path=args.source_inventory,
            fmp_delay2_manifest_path=args.fmp_delay2_manifest,
            variant_paths=variant_paths,
            output_path=args.timing_predictor_manifest,
            schema_path=args.timing_predictor_schema,
            orchestrator_code_path=Path(__file__),
        )
    b2_root = args.output_root.parent / "b2"
    primary_b1 = args.output_root.parent / "b1v3_source_bound/cutoff_0s/b1v3_features.parquet"
    common_manifest = build_replication_timing_common_artifacts(
        preregistration_path=args.preregistration,
        primary_common_manifest_path=args.primary_common_manifest,
        base_manifest_path=args.base_manifest,
        base_schema_path=args.base_schema,
        b1_feature_manifest_path=args.output_root.parent
        / "b1v3_source_bound/cutoff_0s/b1v3_manifest.json",
        b1_feature_schema_path=args.b1_feature_schema,
        fmp_delay2_manifest_path=args.fmp_delay2_manifest,
        fmp_delay2_schema_path=contracts / "b1-independent-replication-fmp-delay2-v1.schema.json",
        timing_predictor_manifest_path=args.timing_predictor_manifest,
        b2_manifest_path=args.b2_manifest,
        origins_path=args.origins,
        primary_b0_path=args.output_root.parent / "b0_target_blind.parquet",
        fmp_delay2_b0_path=args.output_root.parent / "b0_delay2_target_blind.parquet",
        primary_b1_path=primary_b1,
        timing_b1_paths={name: paths["features"] for name, paths in variant_paths.items()},
        primary_b2_path=b2_root / "b2_primary_target_blind.parquet",
        uw_b2_paths={
            "UW_CREATED_AT_120_SECONDS": (b2_root / "b2_latency_5m_120s_target_blind.parquet"),
            "UW_CREATED_AT_300_SECONDS": (b2_root / "b2_latency_5m_300s_target_blind.parquet"),
        },
        output_root=args.output_root.parent / "timing_common",
        manifest_path=args.timing_common_manifest,
        schema_path=args.timing_common_schema,
    )
    print(
        json.dumps(
            {
                "status": common_manifest["status"],
                "timing_predictor_manifest_sha256": predictor_manifest["manifest_sha256"],
                "timing_common_manifest_sha256": common_manifest["manifest_sha256"],
                "variant_count": len(common_manifest["variants"]),
                "outcome_read_count": 0,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
