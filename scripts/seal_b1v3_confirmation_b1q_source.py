"""Seal canonical B1v3 Massive attempts to their exact target-free raw payloads."""

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

from mds650.b1v3_b1q_source import seal_b1q_source  # noqa: E402
from mds650.b1v3_confirmation_build import load_frozen_build_inputs  # noqa: E402


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
        "--origins",
        type=Path,
        default=Path(
            "D:/MDS650/b1v3_confirmation/predictors/b1_origins_target_blind.parquet"
        ),
    )
    parser.add_argument(
        "--attempts",
        type=Path,
        default=Path(
            "D:/MDS650/b1v3_confirmation/tmp/b1q_acquisition_v1/"
            "b1_iv_attempts_20d.parquet"
        ),
    )
    parser.add_argument(
        "--contract-grid",
        type=Path,
        default=Path(
            "D:/MDS650/b1v3_confirmation/cache/massive/"
            "resolved_contracts_b1v3_canonical_spot_v1.json"
        ),
    )
    parser.add_argument(
        "--cache-root",
        type=Path,
        default=Path("D:/MDS650/b1v3_confirmation/cache/massive"),
    )
    parser.add_argument(
        "--inventory",
        type=Path,
        default=Path(
            "D:/MDS650/b1v3_confirmation/evidence/"
            "b1q_raw_payload_inventory.parquet"
        ),
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT
        / "artifacts"
        / "b1v3_confirmation_panel"
        / "b1q_source_manifest.json",
    )
    parser.add_argument(
        "--schema",
        type=Path,
        default=ROOT
        / "specs"
        / "001-pit-options-rv30"
        / "contracts"
        / "b1v3-confirmation-b1q-source-v1.schema.json",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Validate and seal B1Q source evidence, printing only sanitized hashes."""
    args = _arguments(argv)
    inputs = load_frozen_build_inputs(
        args.plan,
        args.provider_report,
        args.provider_candidate_plan,
        args.source_confirmation_plan,
    )
    artifacts = seal_b1q_source(
        inputs=inputs,
        base_manifest_path=args.base_manifest,
        origins_path=args.origins,
        attempts_path=args.attempts,
        contract_grid_path=args.contract_grid,
        cache_root=args.cache_root,
        inventory_path=args.inventory,
        manifest_path=args.manifest,
        manifest_schema_path=args.schema,
    )
    print(
        json.dumps(
            {
                "status": "PASS_TARGET_BLIND_B1Q_SOURCE_BOUND",
                "inventory_sha256": artifacts.inventory_sha256,
                "manifest_sha256": artifacts.manifest_sha256,
                "manifest_file_sha256": artifacts.manifest_file_sha256,
                "outcome_read_count": 0,
                "safe_to_read_outcomes": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
