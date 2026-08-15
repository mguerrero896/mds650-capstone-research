"""Build the source-bound target-blind FMP/origin/B0 replication layer."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from mds650.b1_replication_build import (
    build_replication_base_artifacts,
    load_replication_base_inputs,
)

ROOT = Path(__file__).resolve().parents[1]


def _arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--preregistration",
        type=Path,
        default=ROOT
        / "artifacts/b1_diagnostic_replication/preregistration/preregistration.json",
    )
    parser.add_argument(
        "--primary-plan",
        type=Path,
        default=ROOT
        / "artifacts/b1_diagnostic_replication/provider_preflight/"
        "candidate_preflight_plan.json",
    )
    parser.add_argument(
        "--primary-report",
        type=Path,
        default=ROOT
        / "artifacts/b1_diagnostic_replication/provider_preflight/"
        "provider_preflight_report.json",
    )
    parser.add_argument(
        "--market-plan",
        type=Path,
        default=ROOT
        / "artifacts/b1_diagnostic_replication/provider_preflight/market_controls/"
        "candidate_plan.json",
    )
    parser.add_argument(
        "--market-report",
        type=Path,
        default=ROOT
        / "artifacts/b1_diagnostic_replication/provider_preflight/market_controls/"
        "provider_preflight_report.json",
    )
    parser.add_argument(
        "--fmp-cache-root",
        type=Path,
        default=Path(r"D:\MDS650\b1_diagnostic_replication\provider_preflight"),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path(r"D:\MDS650\b1_diagnostic_replication\predictors"),
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT
        / "artifacts/b1_diagnostic_replication/panel/base_predictor_manifest.json",
    )
    parser.add_argument(
        "--schema",
        type=Path,
        default=ROOT
        / "specs/001-pit-options-rv30/contracts/"
        "b1-independent-replication-base-v1.schema.json",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Build the target-blind base layer and print sanitized identities."""
    args = _arguments(argv)
    inputs = load_replication_base_inputs(
        preregistration_path=args.preregistration,
        primary_plan_path=args.primary_plan,
        primary_report_path=args.primary_report,
        market_plan_path=args.market_plan,
        market_report_path=args.market_report,
    )
    artifacts = build_replication_base_artifacts(
        inputs=inputs,
        fmp_cache_root=args.fmp_cache_root,
        output_root=args.output_root,
        manifest_path=args.manifest,
        manifest_schema_path=args.schema,
    )
    print(
        json.dumps(
            {
                "status": "PASS_TARGET_BLIND_BASE_PREDICTORS",
                "session_count": len(inputs.sessions),
                "outcome_read_count": 0,
                "manifest_file_sha256": artifacts.manifest_sha256,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
