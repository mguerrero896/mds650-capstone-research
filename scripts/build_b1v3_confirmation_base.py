"""Build the source-bound B1v3 target-free origin, FMP, spot, and B0 layer."""

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

from mds650.b1v3_confirmation_build import (  # noqa: E402
    build_base_predictor_artifacts,
    load_frozen_build_inputs,
)


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
        "--fmp-cache-root",
        type=Path,
        default=Path("D:/MDS650/b1v3_provider_preflight_v2"),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("D:/MDS650/b1v3_confirmation/predictors"),
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "artifacts/b1v3_confirmation_panel/base_predictor_manifest.json",
    )
    parser.add_argument(
        "--manifest-schema",
        type=Path,
        default=(
            ROOT
            / "specs/001-pit-options-rv30/contracts/"
            "b1v3-confirmation-base-predictors-v1.schema.json"
        ),
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the target-blind base build and print only sanitized evidence."""
    args = _arguments(argv)
    inputs = load_frozen_build_inputs(
        args.plan,
        args.provider_report,
        args.provider_candidate_plan,
        args.source_confirmation_plan,
    )
    result = build_base_predictor_artifacts(
        inputs=inputs,
        fmp_cache_root=args.fmp_cache_root,
        output_root=args.output_root,
        manifest_path=args.manifest,
        manifest_schema_path=args.manifest_schema,
    )
    print(
        json.dumps(
            {
                "status": "PASS_TARGET_BLIND_BASE_PREDICTORS",
                "manifest_file_sha256": result.manifest_sha256,
                "outcome_read_count": 0,
                "safe_to_read_outcomes": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
