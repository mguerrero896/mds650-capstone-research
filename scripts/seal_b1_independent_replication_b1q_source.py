"""Seal independent-replication B1Q attempts to immutable Massive payloads."""

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

from mds650.b1_replication_b1q_source import (  # noqa: E402
    seal_replication_b1q_source,
)


def _arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    data_root = Path("D:/MDS650/b1_diagnostic_replication")
    parser.add_argument(
        "--preregistration",
        type=Path,
        default=ROOT
        / "artifacts/b1_diagnostic_replication/preregistration/preregistration.json",
    )
    parser.add_argument(
        "--base-manifest",
        type=Path,
        default=ROOT / "artifacts/b1_diagnostic_replication/panel/base_predictor_manifest.json",
    )
    parser.add_argument(
        "--origins",
        type=Path,
        default=data_root / "predictors/b1_origins_target_blind.parquet",
    )
    parser.add_argument(
        "--attempts",
        type=Path,
        default=data_root / "tmp/b1q_acquisition_v1/b1_iv_attempts_20d.parquet",
    )
    parser.add_argument(
        "--contract-grid",
        type=Path,
        default=data_root
        / "cache/massive/resolved_contracts_b1_independent_replication_v1.json",
    )
    parser.add_argument("--cache-root", type=Path, default=data_root / "cache/massive")
    parser.add_argument(
        "--inventory",
        type=Path,
        default=data_root / "evidence/b1q_raw_payload_inventory.parquet",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=ROOT / "artifacts/b1_diagnostic_replication/panel",
    )
    parser.add_argument(
        "--schema",
        type=Path,
        default=ROOT
        / "specs/001-pit-options-rv30/contracts/"
        "b1-independent-replication-b1q-source-v1.schema.json",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _arguments(argv)
    document = seal_replication_b1q_source(
        preregistration_path=args.preregistration,
        base_manifest_path=args.base_manifest,
        origins_path=args.origins,
        attempts_path=args.attempts,
        contract_grid_path=args.contract_grid,
        cache_root=args.cache_root,
        inventory_path=args.inventory,
        manifest_path=args.output_root / "b1q_source_manifest.json",
        schema_path=args.schema,
    )
    print(
        json.dumps(
            {
                "status": document["status"],
                "origin_count": document["scope"]["origin_count"],
                "contract_day_count": document["raw_payload_binding"][
                    "contract_day_count"
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
