"""Build source-bound target-blind B1v3 predictors for independent replication."""

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

from build_b1v3_target_blind import build_target_blind_package  # noqa: E402


def _arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    data_root = Path("D:/MDS650/b1_diagnostic_replication")
    parser.add_argument(
        "--input",
        type=Path,
        default=data_root / "tmp/b1q_acquisition_v1/b1_iv_attempts_20d.parquet",
    )
    parser.add_argument(
        "--design",
        type=Path,
        default=ROOT
        / "docs/superpowers/specs/"
        "2026-08-15-b1-diagnosis-independent-replication-design.md",
    )
    parser.add_argument(
        "--source-binding-manifest",
        type=Path,
        default=ROOT / "artifacts/b1_diagnostic_replication/panel/b1q_source_manifest.json",
    )
    parser.add_argument(
        "--source-binding-schema",
        type=Path,
        default=ROOT
        / "specs/001-pit-options-rv30/contracts/"
        "b1-independent-replication-b1q-source-v1.schema.json",
    )
    parser.add_argument(
        "--source-inventory",
        type=Path,
        default=data_root / "evidence/b1q_raw_payload_inventory.parquet",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=data_root / "predictors/b1v3_source_bound/cutoff_0s",
    )
    parser.add_argument(
        "--manifest-schema",
        type=Path,
        default=ROOT
        / "specs/001-pit-options-rv30/contracts/"
        "b1v3-target-blind-source-bound-manifest-v2.schema.json",
    )
    parser.add_argument("--minimum-free-gib", type=float, default=80.0)
    parser.add_argument("--batch-size", type=int, default=65_536)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _arguments(argv)
    result = build_target_blind_package(
        input_path=args.input,
        design_path=args.design,
        output_root=args.output_root,
        manifest_schema_path=args.manifest_schema,
        source_binding_manifest_path=args.source_binding_manifest,
        source_binding_schema_path=args.source_binding_schema,
        source_inventory_path=args.source_inventory,
        quote_cutoff_seconds=0,
        minimum_free_gib=args.minimum_free_gib,
        batch_size=args.batch_size,
    )
    print(
        json.dumps(
            {
                "status": "PASS_TARGET_BLIND_SOURCE_BOUND_TECHNICAL_BUILD",
                "features_sha256": result.features_sha256,
                "coverage_sha256": result.coverage_sha256,
                "manifest_file_sha256": result.manifest_sha256,
                "outcome_read_count": 0,
                "safe_to_evaluate_scientifically": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
