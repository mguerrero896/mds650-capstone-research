"""Build corrected 60/120/300-second B2 predictors without outcome access."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))  # noqa: E402

from mds650.b1v3_b2_confirmation import (  # noqa: E402
    build_b2_confirmation_artifacts,
    load_full_tape_contract,
)
from mds650.b1v3_confirmation_build import load_frozen_build_inputs  # noqa: E402


def _arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--plan",
        type=Path,
        default=ROOT / "artifacts/b1v3_confirmation_plan/confirmation_plan_provider_passed.json",
    )
    parser.add_argument(
        "--provider-report",
        type=Path,
        default=ROOT / "artifacts/b1v3_provider_preflight_v2/provider_preflight_report.json",
    )
    parser.add_argument(
        "--provider-candidate-plan",
        type=Path,
        default=ROOT / "artifacts/b1v3_provider_preflight_v2/candidate_preflight_plan.json",
    )
    parser.add_argument(
        "--source-confirmation-plan",
        type=Path,
        default=ROOT / "artifacts/b1v3_confirmation_plan/confirmation_plan.json",
    )
    parser.add_argument(
        "--acquisition-manifest",
        type=Path,
        default=ROOT / "artifacts/b1v3_confirmation_panel/full_tape_acquisition_manifest.json",
    )
    parser.add_argument(
        "--acquisition-manifest-schema",
        type=Path,
        default=(
            ROOT
            / "specs/001-pit-options-rv30/contracts/"
            "b1v3-full-tape-acquisition-manifest-v1.schema.json"
        ),
    )
    parser.add_argument(
        "--base-manifest",
        type=Path,
        default=ROOT / "artifacts/b1v3_confirmation_panel/base_predictor_manifest.json",
    )
    parser.add_argument(
        "--origins",
        type=Path,
        default=Path("D:/MDS650/b1v3_confirmation/predictors/forecast_origins_target_blind.parquet"),
    )
    parser.add_argument("--data-root", type=Path, default=Path("D:/MDS650/b1v3_confirmation"))
    parser.add_argument(
        "--event-root",
        type=Path,
        default=Path("D:/MDS650/b1v3_confirmation/data/option_events"),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("D:/MDS650/b1v3_confirmation/predictors"),
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "artifacts/b1v3_confirmation_panel/b2_predictor_manifest.json",
    )
    parser.add_argument(
        "--manifest-schema",
        type=Path,
        default=(
            ROOT
            / "specs/001-pit-options-rv30/contracts/"
            "b1v3-confirmation-b2-predictors-v1.schema.json"
        ),
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the fail-closed target-blind B2 build."""
    args = _arguments(argv)
    inputs = load_frozen_build_inputs(
        args.plan,
        args.provider_report,
        args.provider_candidate_plan,
        args.source_confirmation_plan,
    )
    contract = load_full_tape_contract(
        args.acquisition_manifest,
        frozen_inputs=inputs,
        manifest_schema_path=args.acquisition_manifest_schema,
    )
    result = build_b2_confirmation_artifacts(
        frozen_inputs=inputs,
        full_tape_contract=contract,
        base_manifest_path=args.base_manifest,
        origins_path=args.origins,
        data_root=args.data_root,
        event_root=args.event_root,
        output_root=args.output_root,
        manifest_path=args.manifest,
        manifest_schema_path=args.manifest_schema,
    )
    print(
        json.dumps(
            {
                "status": "PASS_TARGET_BLIND_B2_PREDICTORS",
                "manifest_file_sha256": result.manifest_file_sha256,
                "outcome_read_count": 0,
                "safe_to_read_outcomes": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
