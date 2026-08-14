"""Build the source-bound target-blind B0/B1v3a/B2 common predictor panel."""

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

from mds650.b1v3_confirmation_build import load_frozen_build_inputs  # noqa: E402
from mds650.b1v3_confirmation_common import (  # noqa: E402
    build_common_predictor_artifacts,
)


def _arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--plan",
        type=Path,
        default=ROOT
        / "artifacts"
        / "b1v3_confirmation_plan"
        / "confirmation_plan_provider_passed.json",
    )
    parser.add_argument(
        "--provider-report",
        type=Path,
        default=ROOT
        / "artifacts"
        / "b1v3_provider_preflight_v2"
        / "provider_preflight_report.json",
    )
    parser.add_argument(
        "--provider-candidate-plan",
        type=Path,
        default=ROOT
        / "artifacts"
        / "b1v3_provider_preflight_v2"
        / "candidate_preflight_plan.json",
    )
    parser.add_argument(
        "--source-confirmation-plan",
        type=Path,
        default=ROOT
        / "artifacts"
        / "b1v3_confirmation_plan"
        / "confirmation_plan.json",
    )
    parser.add_argument(
        "--base-manifest",
        type=Path,
        default=ROOT
        / "artifacts"
        / "b1v3_confirmation_panel"
        / "base_predictor_manifest.json",
    )
    parser.add_argument(
        "--base-manifest-schema",
        type=Path,
        default=ROOT
        / "specs"
        / "001-pit-options-rv30"
        / "contracts"
        / "b1v3-confirmation-base-predictors-v1.schema.json",
    )
    parser.add_argument(
        "--origins",
        type=Path,
        default=Path(
            "D:/MDS650/b1v3_confirmation/predictors/"
            "forecast_origins_target_blind.parquet"
        ),
    )
    parser.add_argument(
        "--b0",
        type=Path,
        default=Path("D:/MDS650/b1v3_confirmation/predictors/b0_target_blind.parquet"),
    )
    parser.add_argument(
        "--b1-source-manifest",
        type=Path,
        default=ROOT
        / "artifacts"
        / "b1v3_confirmation_panel"
        / "b1q_source_manifest.json",
    )
    parser.add_argument(
        "--b1-source-manifest-schema",
        type=Path,
        default=ROOT
        / "specs"
        / "001-pit-options-rv30"
        / "contracts"
        / "b1v3-confirmation-b1q-source-v1.schema.json",
    )
    parser.add_argument(
        "--b1-source-inventory",
        type=Path,
        default=Path(
            "D:/MDS650/b1v3_confirmation/evidence/"
            "b1q_raw_payload_inventory.parquet"
        ),
    )
    parser.add_argument(
        "--b1-manifest",
        type=Path,
        default=Path(
            "D:/MDS650/b1v3_confirmation/predictors/"
            "b1v3_source_bound/b1v3_manifest.json"
        ),
    )
    parser.add_argument(
        "--b1-manifest-schema",
        type=Path,
        default=ROOT
        / "specs"
        / "001-pit-options-rv30"
        / "contracts"
        / "b1v3-target-blind-source-bound-manifest-v2.schema.json",
    )
    parser.add_argument(
        "--b1",
        type=Path,
        default=Path(
            "D:/MDS650/b1v3_confirmation/predictors/"
            "b1v3_source_bound/b1v3_features.parquet"
        ),
    )
    parser.add_argument(
        "--b2-manifest",
        type=Path,
        default=ROOT
        / "artifacts"
        / "b1v3_confirmation_panel"
        / "b2_predictor_manifest.json",
    )
    parser.add_argument(
        "--b2-manifest-schema",
        type=Path,
        default=ROOT
        / "specs"
        / "001-pit-options-rv30"
        / "contracts"
        / "b1v3-confirmation-b2-predictors-v1.schema.json",
    )
    parser.add_argument(
        "--b2",
        type=Path,
        default=Path(
            "D:/MDS650/b1v3_confirmation/predictors/b2_primary_target_blind.parquet"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "D:/MDS650/b1v3_confirmation/predictors/common_predictor_panel.parquet"
        ),
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT
        / "artifacts"
        / "b1v3_confirmation_panel"
        / "common_predictor_manifest.json",
    )
    parser.add_argument(
        "--manifest-schema",
        type=Path,
        default=ROOT
        / "specs"
        / "001-pit-options-rv30"
        / "contracts"
        / "b1v3-confirmation-common-predictor-v1.schema.json",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Build the common predictor panel and print only sanitized identities."""
    args = _arguments(argv)
    inputs = load_frozen_build_inputs(
        args.plan,
        args.provider_report,
        args.provider_candidate_plan,
        args.source_confirmation_plan,
    )
    result = build_common_predictor_artifacts(
        inputs=inputs,
        base_manifest_path=args.base_manifest,
        base_manifest_schema_path=args.base_manifest_schema,
        origins_path=args.origins,
        b0_path=args.b0,
        b1_source_manifest_path=args.b1_source_manifest,
        b1_source_manifest_schema_path=args.b1_source_manifest_schema,
        b1_source_inventory_path=args.b1_source_inventory,
        b1_manifest_path=args.b1_manifest,
        b1_manifest_schema_path=args.b1_manifest_schema,
        b1_path=args.b1,
        b2_manifest_path=args.b2_manifest,
        b2_manifest_schema_path=args.b2_manifest_schema,
        b2_path=args.b2,
        output_path=args.output,
        manifest_path=args.manifest,
        manifest_schema_path=args.manifest_schema,
    )
    print(
        json.dumps(
            {
                "status": "PASS_TARGET_BLIND_COMMON_PREDICTOR_PANEL",
                "panel_sha256": result.panel_sha256,
                "manifest_sha256": result.manifest_sha256,
                "manifest_file_sha256": result.manifest_file_sha256,
                "safe_to_read_outcomes": False,
                "safe_to_evaluate_scientifically": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
