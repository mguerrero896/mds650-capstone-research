"""Build the preregistered target-blind FMP plus-two-minute sensitivity."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mds650.b1v3_confirmation import (  # noqa: E402
    canonical_sha256,
    sha256_file,
    validate_confirmation_plan_schema,
)
from mds650.b1v3_confirmation_common import (  # noqa: E402
    _write_json_if_identical,
    _write_parquet_if_identical,
)
from mds650.b1v3_confirmation_panel import build_b0_target_blind  # noqa: E402


def _json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("B1_REPLICATION_FMP_DELAY2_BASE_INVALID")
    return value


def build_delay2(
    *,
    base_manifest_path: Path,
    bars_path: Path,
    origins_path: Path,
    output_path: Path,
    manifest_path: Path,
    schema_path: Path,
) -> dict[str, Any]:
    """Build and bind the +2-minute B0 sensitivity without RV30 access."""
    base = _json_object(base_manifest_path)
    stored = base.get("manifest_sha256")
    unsigned = {key: value for key, value in base.items() if key != "manifest_sha256"}
    outputs = base.get("outputs")
    bars_binding = outputs.get("fmp_bars") if isinstance(outputs, Mapping) else None
    origins_binding = outputs.get("origins") if isinstance(outputs, Mapping) else None
    if (
        not isinstance(stored, str)
        or stored != canonical_sha256(unsigned)
        or base.get("status") != "PASS_TARGET_BLIND_BASE_PREDICTORS"
        or base.get("outcome_read_count") != 0
        or not isinstance(bars_binding, Mapping)
        or bars_binding.get("sha256") != sha256_file(bars_path)
        or not isinstance(origins_binding, Mapping)
        or origins_binding.get("sha256") != sha256_file(origins_path)
    ):
        raise ValueError("B1_REPLICATION_FMP_DELAY2_BASE_INVALID")
    bars = pl.read_parquet(bars_path)
    origins = pl.read_parquet(origins_path)
    frame = build_b0_target_blind(bars, origins, delay_minutes=2)
    if frame.height != origins.height or frame["origin_id"].n_unique() != frame.height:
        raise ValueError("B1_REPLICATION_FMP_DELAY2_SCOPE_INVALID")
    output_hash = _write_parquet_if_identical(frame, output_path)
    document: dict[str, Any] = {
        "schema_version": "b1-independent-replication-fmp-delay2-1.0",
        "status": "PASS_TARGET_BLIND_FMP_DELAY_2_MINUTES",
        "base_manifest_sha256": stored,
        "target_blind": True,
        "outcome_read_count": 0,
        "safe_to_read_outcomes": False,
        "delay_minutes": 2,
        "origin_count": frame.height,
        "complete_origin_count": int(frame["b0_complete"].sum()),
        "output": {
            "logical_path": (
                "MDS650_B1_REPLICATION_DATA_ROOT/predictors/"
                "b0_delay2_target_blind.parquet"
            ),
            "sha256": output_hash,
            "bytes": output_path.stat().st_size,
            "row_count": frame.height,
        },
        "security": {"secret_values_emitted": False, "personal_paths_emitted": False},
    }
    document["manifest_sha256"] = canonical_sha256(document)
    validate_confirmation_plan_schema(document, schema_path)
    _write_json_if_identical(manifest_path, document)
    return document


def _arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    data = Path("D:/MDS650/b1_diagnostic_replication/predictors")
    artifacts = ROOT / "artifacts/b1_diagnostic_replication/panel"
    parser.add_argument(
        "--base-manifest", type=Path, default=artifacts / "base_predictor_manifest.json"
    )
    parser.add_argument("--bars", type=Path, default=data / "underlying_1min_target_blind.parquet")
    parser.add_argument(
        "--origins", type=Path, default=data / "forecast_origins_target_blind.parquet"
    )
    parser.add_argument("--output-root", type=Path, default=data)
    parser.add_argument("--manifest", type=Path, default=artifacts / "b0_delay2_manifest.json")
    parser.add_argument(
        "--schema",
        type=Path,
        default=ROOT / "specs/001-pit-options-rv30/contracts/"
        "b1-independent-replication-fmp-delay2-v1.schema.json",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _arguments(argv)
    document = build_delay2(
        base_manifest_path=args.base_manifest,
        bars_path=args.bars,
        origins_path=args.origins,
        output_path=args.output_root / "b0_delay2_target_blind.parquet",
        manifest_path=args.manifest,
        schema_path=args.schema,
    )
    print(json.dumps({"status": document["status"], "outcome_read_count": 0}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
