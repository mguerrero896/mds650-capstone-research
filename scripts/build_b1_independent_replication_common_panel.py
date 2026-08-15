"""Build the primary source-bound predictor-only panel for replication."""

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

from mds650.b1_replication_common import (  # noqa: E402
    build_replication_common_artifacts,
)


def _arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    contracts = ROOT / "specs/001-pit-options-rv30/contracts"
    artifacts = ROOT / "artifacts/b1_diagnostic_replication/panel"
    data = Path("D:/MDS650/b1_diagnostic_replication")
    parser.add_argument(
        "--preregistration",
        type=Path,
        default=ROOT / "artifacts/b1_diagnostic_replication/preregistration/preregistration.json",
    )
    parser.add_argument(
        "--base-manifest", type=Path, default=artifacts / "base_predictor_manifest.json"
    )
    parser.add_argument(
        "--base-schema",
        type=Path,
        default=contracts / "b1-independent-replication-base-v1.schema.json",
    )
    parser.add_argument(
        "--b1-source-manifest", type=Path, default=artifacts / "b1q_source_manifest.json"
    )
    parser.add_argument(
        "--b1-source-schema",
        type=Path,
        default=contracts / "b1-independent-replication-b1q-source-v1.schema.json",
    )
    parser.add_argument(
        "--b1-inventory", type=Path, default=data / "evidence/b1q_raw_payload_inventory.parquet"
    )
    parser.add_argument(
        "--b1-manifest",
        type=Path,
        default=data / "predictors/b1v3_source_bound/cutoff_0s/b1v3_manifest.json",
    )
    parser.add_argument(
        "--b1-schema",
        type=Path,
        default=contracts / "b1v3-target-blind-source-bound-manifest-v2.schema.json",
    )
    parser.add_argument(
        "--b2-manifest", type=Path, default=artifacts / "b2_predictor_manifest.json"
    )
    parser.add_argument(
        "--b2-schema", type=Path, default=contracts / "b1-independent-replication-b2-v1.schema.json"
    )
    parser.add_argument(
        "--origins", type=Path, default=data / "predictors/forecast_origins_target_blind.parquet"
    )
    parser.add_argument("--b0", type=Path, default=data / "predictors/b0_target_blind.parquet")
    parser.add_argument(
        "--b1",
        type=Path,
        default=data / "predictors/b1v3_source_bound/cutoff_0s/b1v3_features.parquet",
    )
    parser.add_argument(
        "--b2", type=Path, default=data / "predictors/b2/b2_primary_target_blind.parquet"
    )
    parser.add_argument("--output-root", type=Path, default=data / "predictors")
    parser.add_argument(
        "--manifest", type=Path, default=artifacts / "common_predictor_manifest.json"
    )
    parser.add_argument(
        "--schema",
        type=Path,
        default=contracts / "b1-independent-replication-common-v1.schema.json",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _arguments(argv)
    document = build_replication_common_artifacts(
        preregistration_path=args.preregistration,
        base_manifest_path=args.base_manifest,
        base_schema_path=args.base_schema,
        b1_source_manifest_path=args.b1_source_manifest,
        b1_source_schema_path=args.b1_source_schema,
        b1_inventory_path=args.b1_inventory,
        b1_manifest_path=args.b1_manifest,
        b1_schema_path=args.b1_schema,
        b2_manifest_path=args.b2_manifest,
        b2_schema_path=args.b2_schema,
        origins_path=args.origins,
        b0_path=args.b0,
        b1_path=args.b1,
        b2_path=args.b2,
        output_path=args.output_root / "common_predictor_panel.parquet",
        manifest_path=args.manifest,
        manifest_schema_path=args.schema,
    )
    print(
        json.dumps(
            {
                "status": document["status"],
                "origin_count": document["scope"]["origin_count"],
                "common_complete_origin_count": document["technical_acceptance"][
                    "common_complete_origin_count"
                ],
                "outcome_read_count": 0,
                "manifest_sha256": document["manifest_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
