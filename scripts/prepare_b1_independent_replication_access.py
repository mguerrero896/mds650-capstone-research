"""Validate all target-blind gates and seal one replication-read token."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mds650.b1_replication_access import (  # noqa: E402
    build_pre_read_quality_and_access,
)


def _arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    data = Path("D:/MDS650/b1_diagnostic_replication")
    artifacts = ROOT / "artifacts/b1_diagnostic_replication"
    panel = artifacts / "panel"
    parser.add_argument(
        "--preregistration",
        type=Path,
        default=artifacts / "preregistration/preregistration.json",
    )
    parser.add_argument(
        "--method-freeze",
        type=Path,
        default=artifacts / "method_freeze/method_freeze.json",
    )
    parser.add_argument(
        "--provider-report",
        type=Path,
        default=artifacts / "provider_preflight/provider_preflight_report.json",
    )
    parser.add_argument(
        "--market-report",
        type=Path,
        default=artifacts / "provider_preflight/market_controls/provider_preflight_report.json",
    )
    parser.add_argument(
        "--full-tape-manifest",
        type=Path,
        default=artifacts / "acquisition/full_tape_acquisition_manifest.json",
    )
    parser.add_argument(
        "--base-manifest", type=Path, default=panel / "base_predictor_manifest.json"
    )
    parser.add_argument(
        "--b1-source-manifest", type=Path, default=panel / "b1q_source_manifest.json"
    )
    parser.add_argument(
        "--b1-feature-manifest",
        type=Path,
        default=data / "predictors/b1v3_source_bound/cutoff_0s/b1v3_manifest.json",
    )
    parser.add_argument(
        "--b2-manifest", type=Path, default=panel / "b2_predictor_manifest.json"
    )
    parser.add_argument(
        "--common-manifest", type=Path, default=panel / "common_predictor_manifest.json"
    )
    parser.add_argument(
        "--timing-predictor-manifest",
        type=Path,
        default=panel / "timing_predictor_manifest.json",
    )
    parser.add_argument(
        "--timing-common-manifest",
        type=Path,
        default=panel / "timing_common_manifest.json",
    )
    parser.add_argument("--output-root", type=Path, default=artifacts / "access")
    parser.add_argument("--minimum-free-gib", type=float, default=80.0)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _arguments(argv)
    contracts = ROOT / "specs/001-pit-options-rv30/contracts"
    data = Path("D:/MDS650/b1_diagnostic_replication")
    predictors = data / "predictors"
    timing_common_root = predictors / "timing_common"
    code_paths = (
        ROOT / "src/mds650/b1_replication_access.py",
        ROOT / "src/mds650/b1_replication_evaluation.py",
        ROOT / "src/mds650/b1v3_confirmation_evaluation.py",
        ROOT / "src/mds650/b1v3_confirmation_run.py",
        ROOT / "scripts/run_b1_independent_replication_once.py",
    )
    quality, access = build_pre_read_quality_and_access(
        preregistration_path=args.preregistration,
        preregistration_schema_path=contracts
        / "b1-independent-replication-preregistration-v1.schema.json",
        method_freeze_path=args.method_freeze,
        method_freeze_schema_path=contracts
        / "b1-independent-replication-method-freeze-v1.schema.json",
        provider_report_path=args.provider_report,
        market_report_path=args.market_report,
        provider_report_schema_path=contracts / "b1v3-provider-preflight-report-v2.schema.json",
        full_tape_manifest_path=args.full_tape_manifest,
        full_tape_schema_path=contracts
        / "b1-independent-replication-full-tape-v1.schema.json",
        base_manifest_path=args.base_manifest,
        base_schema_path=contracts / "b1-independent-replication-base-v1.schema.json",
        b1_source_manifest_path=args.b1_source_manifest,
        b1_source_schema_path=contracts
        / "b1-independent-replication-b1q-source-v1.schema.json",
        b1_inventory_path=data / "evidence/b1q_raw_payload_inventory.parquet",
        b1_feature_manifest_path=args.b1_feature_manifest,
        b1_feature_schema_path=contracts
        / "b1v3-target-blind-source-bound-manifest-v2.schema.json",
        b2_manifest_path=args.b2_manifest,
        b2_schema_path=contracts / "b1-independent-replication-b2-v1.schema.json",
        common_manifest_path=args.common_manifest,
        common_schema_path=contracts / "b1-independent-replication-common-v1.schema.json",
        timing_predictor_manifest_path=args.timing_predictor_manifest,
        timing_predictor_schema_path=contracts
        / "b1-independent-replication-timing-predictors-v1.schema.json",
        timing_common_manifest_path=args.timing_common_manifest,
        timing_common_schema_path=contracts
        / "b1-independent-replication-timing-common-v1.schema.json",
        training_timing_manifest_path=ROOT
        / "artifacts/b1v3_confirmation_panel/timing_panel_manifest.json",
        training_timing_schema_path=contracts
        / "b1v3-confirmation-timing-panels-v1.schema.json",
        origins_path=predictors / "forecast_origins_target_blind.parquet",
        b0_path=predictors / "b0_target_blind.parquet",
        b1_path=predictors / "b1v3_source_bound/cutoff_0s/b1v3_features.parquet",
        b2_path=predictors / "b2/b2_primary_target_blind.parquet",
        common_panel_path=predictors / "common_predictor_panel.parquet",
        timing_panel_paths={
            variant: timing_common_root
            / variant.lower()
            / "common_predictor_panel.parquet"
            for variant in (
                "FMP_DELAY_2_MINUTES",
                "MASSIVE_CUTOFF_60_SECONDS",
                "MASSIVE_CUTOFF_300_SECONDS",
                "UW_CREATED_AT_120_SECONDS",
                "UW_CREATED_AT_300_SECONDS",
            )
        },
        training_timing_panel_paths={
            variant: Path("D:/MDS650/b1v3_confirmation/predictors/timing/common")
            / f"{variant}.parquet"
            for variant in (
                "FMP_DELAY_2_MINUTES",
                "MASSIVE_CUTOFF_60_SECONDS",
                "MASSIVE_CUTOFF_300_SECONDS",
                "UW_CREATED_AT_120_SECONDS",
                "UW_CREATED_AT_300_SECONDS",
            )
        },
        fmp_bars_path=predictors / "underlying_1min_target_blind.parquet",
        training_snapshot_path=data / "method/development_training_panel.parquet",
        code_paths=code_paths,
        uv_lock_path=ROOT / "uv.lock",
        data_root=data,
        quality_path=args.output_root / "quality_report.json",
        quality_schema_path=contracts
        / "b1-independent-replication-quality-v1.schema.json",
        access_path=args.output_root / "access_ledger_frozen.json",
        access_schema_path=contracts
        / "b1-independent-replication-access-v1.schema.json",
        minimum_free_gib=args.minimum_free_gib,
    )
    print(
        json.dumps(
            {
                "quality_status": quality["status"],
                "access_status": access["status"],
                "available_read_tokens": access["available_read_tokens"],
                "replication_target_read_count": 0,
                "quality_manifest_sha256": quality["manifest_sha256"],
                "access_manifest_sha256": access["manifest_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
