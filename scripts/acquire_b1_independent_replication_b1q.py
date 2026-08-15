"""Run resumable Massive B1Q acquisition for the frozen 30-session replication."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from collections.abc import Sequence
from importlib import import_module
from pathlib import Path
from typing import Protocol, cast

import polars as pl

from mds650.b1_replication_build import CANONICAL_ASSETS
from mds650.b1v3_confirmation import canonical_sha256, sha256_file

ROOT = Path(__file__).resolve().parents[1]
GIB = 1024**3
PROJECTED_B1Q_ADDITIONAL_BYTES = 100 * GIB
MINIMUM_FREE_BYTES = 80 * GIB
_FORBIDDEN_COLUMN_TOKENS = (
    "rv30",
    "qlike",
    "prediction",
    "predicted",
    "outcome",
    "loss",
    "model_result",
)


class _ConfigFactory(Protocol):
    def __call__(
        self,
        *,
        output_root: Path,
        cache_root: Path,
        sessions: tuple[str, ...],
        origins_path: Path | None = None,
        contract_cache_filename: str = "resolved_contracts_phase6_strict_v3.json",
    ) -> object: ...


class _LegacyB1QModule(Protocol):
    B1BuildConfig: _ConfigFactory

    def main(self, config: object) -> None: ...


def _json_object(path: Path, *, code: str) -> dict[str, object]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(code) from exc
    if not isinstance(document, dict):
        raise ValueError(code)
    return cast(dict[str, object], document)


def _valid_self_hash(document: dict[str, object], field: str) -> bool:
    stored = document.get(field)
    unsigned = {key: value for key, value in document.items() if key != field}
    return isinstance(stored, str) and stored == canonical_sha256(unsigned)


def validate_b1q_run_contract(
    *,
    base_manifest_path: Path,
    origins_path: Path,
    preregistration_sha256: str,
    sessions: tuple[str, ...],
    assets: tuple[str, ...],
    expected_origin_count: int,
) -> None:
    """Reject any origin source not bound to the target-blind base manifest."""
    base = _json_object(base_manifest_path, code="REPLICATION_B1Q_BASE_INVALID")
    if not _valid_self_hash(base, "manifest_sha256"):
        raise ValueError("REPLICATION_B1Q_BASE_HASH_INVALID")
    outputs = base.get("outputs")
    b1_output = outputs.get("b1_origins") if isinstance(outputs, dict) else None
    raw_assets = base.get("assets")
    base_assets = (
        tuple(str(value) for value in raw_assets)
        if isinstance(raw_assets, list)
        else ()
    )
    if (
        base.get("status") != "PASS_TARGET_BLIND_BASE_PREDICTORS"
        or base.get("target_blind") is not True
        or base.get("outcome_read_count") != 0
        or base.get("safe_to_read_outcomes") is not False
        or base.get("preregistration_sha256") != preregistration_sha256
        or base.get("session_count") != len(sessions)
        or base_assets != assets
        or base.get("origin_count") != expected_origin_count
        or not isinstance(b1_output, dict)
        or b1_output.get("sha256") != sha256_file(origins_path)
    ):
        raise ValueError("REPLICATION_B1Q_BASE_GATE_INVALID")
    frame = pl.read_parquet(origins_path)
    required = {
        "origin_id",
        "asset",
        "session_date",
        "forecast_origin_utc",
        "spot",
        "session_segment",
    }
    if not required.issubset(frame.columns):
        raise ValueError("REPLICATION_B1Q_ORIGIN_SCHEMA_INVALID")
    lowered = tuple(column.lower() for column in frame.columns)
    if any(
        token in column for token in _FORBIDDEN_COLUMN_TOKENS for column in lowered
    ):
        raise ValueError("REPLICATION_B1Q_ORIGIN_NOT_TARGET_BLIND")
    observed_sessions = tuple(
        sorted(str(value) for value in frame["session_date"].unique().to_list())
    )
    observed_assets = tuple(
        sorted(str(value) for value in frame["asset"].unique().to_list())
    )
    if (
        frame.height != expected_origin_count
        or frame["origin_id"].n_unique() != frame.height
        or observed_sessions != sessions
        or observed_assets != assets
        or frame["spot"].null_count()
        or frame.filter(~pl.col("spot").is_finite() | (pl.col("spot") <= 0)).height
    ):
        raise ValueError("REPLICATION_B1Q_ORIGIN_SCOPE_INVALID")


def _arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--preregistration",
        type=Path,
        default=ROOT
        / "artifacts/b1_diagnostic_replication/preregistration/preregistration.json",
    )
    parser.add_argument(
        "--base-manifest",
        type=Path,
        default=ROOT
        / "artifacts/b1_diagnostic_replication/panel/base_predictor_manifest.json",
    )
    parser.add_argument(
        "--origins",
        type=Path,
        default=Path(
            "D:/MDS650/b1_diagnostic_replication/predictors/"
            "b1_origins_target_blind.parquet"
        ),
    )
    parser.add_argument(
        "--cache-root",
        type=Path,
        default=Path(r"D:\MDS650\b1_diagnostic_replication\cache\massive"),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path(
            r"D:\MDS650\b1_diagnostic_replication\tmp\b1q_acquisition_v1"
        ),
    )
    parser.add_argument("--execute", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Validate the frozen scope and optionally execute the provider job."""
    args = _arguments(argv)
    preregistration = _json_object(
        args.preregistration, code="REPLICATION_B1Q_PREREGISTRATION_INVALID"
    )
    if (
        not _valid_self_hash(preregistration, "manifest_sha256")
        or preregistration.get("status") != "FROZEN_BEFORE_PROVIDER_PAYLOAD"
        or preregistration.get("target_blind") is not True
        or preregistration.get("replication_target_reads") != 0
    ):
        raise ValueError("REPLICATION_B1Q_PREREGISTRATION_GATE_INVALID")
    raw_sessions = preregistration.get("replication_sessions")
    if not isinstance(raw_sessions, list):
        raise ValueError("REPLICATION_B1Q_SESSION_INVALID")
    sessions = tuple(str(value) for value in raw_sessions)
    if len(sessions) != 30 or sessions != tuple(sorted(set(sessions))):
        raise ValueError("REPLICATION_B1Q_SESSION_INVALID")
    preregistration_sha256 = str(preregistration["manifest_sha256"])
    validate_b1q_run_contract(
        base_manifest_path=args.base_manifest,
        origins_path=args.origins,
        preregistration_sha256=preregistration_sha256,
        sessions=sessions,
        assets=CANONICAL_ASSETS,
        expected_origin_count=12_744,
    )
    for root in (args.cache_root, args.output_root):
        if root.resolve().drive.upper() != "D:":
            raise RuntimeError("REPLICATION_B1Q_ROOT_NOT_SAMSUNG_DRIVE")
    free_bytes = int(shutil.disk_usage("D:\\").free)
    if free_bytes - PROJECTED_B1Q_ADDITIONAL_BYTES < MINIMUM_FREE_BYTES:
        raise RuntimeError("REPLICATION_B1Q_PROJECTED_FREE_BELOW_80_GIB")
    secret_presence = {
        name: bool(os.environ.get(name)) for name in ("FMP_API_KEY", "MASSIVE_API_KEY")
    }
    if not all(secret_presence.values()):
        raise RuntimeError("REPLICATION_B1Q_REQUIRED_SECRET_MISSING")
    if not args.execute:
        print(
            json.dumps(
                {
                    "status": "READY_TARGET_BLIND_B1Q_ACQUISITION",
                    "session_count": len(sessions),
                    "origin_count": 12_744,
                    "projected_additional_gib": 100,
                    "projected_final_free_gib": round(
                        (free_bytes - PROJECTED_B1Q_ADDITIONAL_BYTES) / GIB, 2
                    ),
                    "secret_presence": secret_presence,
                    "outcome_read_count": 0,
                    "safe_to_read_outcomes": False,
                },
                sort_keys=True,
            )
        )
        return 0
    module = cast(_LegacyB1QModule, import_module("run_b1_calibration_20d"))
    config = module.B1BuildConfig(
        output_root=args.output_root,
        cache_root=args.cache_root,
        sessions=sessions,
        origins_path=args.origins,
        contract_cache_filename=(
            "resolved_contracts_b1_independent_replication_v1.json"
        ),
    )
    module.main(config)
    matrix_path = args.output_root / "b1_origin_matrix_20d.parquet"
    attempts_path = args.output_root / "b1_iv_attempts_20d.parquet"
    if not matrix_path.is_file() or not attempts_path.is_file():
        raise RuntimeError("REPLICATION_B1Q_OUTPUT_MISSING")
    matrix = pl.read_parquet(matrix_path)
    if matrix.height != 12_744 or matrix["origin_id"].n_unique() != matrix.height:
        raise RuntimeError("REPLICATION_B1Q_OUTPUT_SCOPE_INVALID")
    print(
        json.dumps(
            {
                "status": "PASS_TARGET_BLIND_B1Q_ACQUISITION",
                "session_count": len(sessions),
                "origin_count": matrix.height,
                "outcome_read_count": 0,
                "safe_to_read_outcomes": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
