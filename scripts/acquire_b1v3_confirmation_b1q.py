"""Run the resumable target-blind Massive B1Q acquisition for frozen B1v3 dates."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from importlib import import_module
from pathlib import Path
from typing import Any, Protocol, cast

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SCRIPTS = ROOT / "scripts"
for source_root in (SRC, SCRIPTS):
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))  # noqa: E402

from mds650.b1v3_confirmation import canonical_sha256, sha256_file  # noqa: E402
from mds650.b1v3_confirmation_build import (  # noqa: E402
    B1V3_CANONICAL_ASSETS,
    FrozenBuildInputs,
    load_frozen_build_inputs,
)

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


def _json_object(path: Path, *, code: str) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(code) from exc
    if not isinstance(document, dict):
        raise ValueError(code)
    return document


def validate_b1q_run_contract(
    *,
    inputs: FrozenBuildInputs,
    base_manifest_path: Path,
    origins_path: Path,
) -> None:
    """Validate the exact target-free origin source before provider execution.

    Parameters
    ----------
    inputs:
        Frozen provider-passed 60/30 plan.
    base_manifest_path:
        Immutable base-predictor manifest that binds the origin projection.
    origins_path:
        Target-free origin table enriched with point-in-time spot.

    Raises
    ------
    ValueError
        If hashes, gates, schemas, identities, assets, sessions, or target-blind
        boundaries fail.
    """
    base = _json_object(base_manifest_path, code="B1V3_B1Q_BASE_MANIFEST_INVALID")
    stored_hash = base.get("manifest_sha256")
    if not isinstance(stored_hash, str) or stored_hash != canonical_sha256(
        {key: value for key, value in base.items() if key != "manifest_sha256"}
    ):
        raise ValueError("B1V3_B1Q_BASE_MANIFEST_HASH_INVALID")
    outputs = base.get("outputs")
    if not isinstance(outputs, dict) or not isinstance(outputs.get("b1_origins"), dict):
        raise ValueError("B1V3_B1Q_BASE_MANIFEST_GATE_INVALID")
    if (
        base.get("status") != "PASS_TARGET_BLIND_BASE_PREDICTORS"
        or base.get("plan_sha256") != inputs.plan_sha256
        or base.get("target_blind") is not True
        or base.get("outcome_read_count") != 0
        or base.get("safe_to_read_outcomes") is not False
        or outputs["b1_origins"].get("sha256") != sha256_file(origins_path)
    ):
        raise ValueError("B1V3_B1Q_BASE_MANIFEST_GATE_INVALID")
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
        raise ValueError("B1V3_B1Q_ORIGIN_SCHEMA_INVALID")
    lowered = tuple(column.lower() for column in frame.columns)
    if any(token in column for token in _FORBIDDEN_COLUMN_TOKENS for column in lowered):
        raise ValueError("B1V3_B1Q_ORIGIN_NOT_TARGET_BLIND")
    sessions = tuple(sorted(str(value) for value in frame["session_date"].unique().to_list()))
    assets = tuple(sorted(str(value) for value in frame["asset"].unique().to_list()))
    if (
        frame.height != 38_664
        or frame["origin_id"].n_unique() != frame.height
        or sessions != inputs.all_sessions
        or assets != B1V3_CANONICAL_ASSETS
        or frame["spot"].null_count()
        or frame.filter(pl.col("spot") <= 0).height
    ):
        raise ValueError("B1V3_B1Q_ORIGIN_SCOPE_INVALID")


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
        "--base-manifest",
        type=Path,
        default=ROOT / "artifacts/b1v3_confirmation_panel/base_predictor_manifest.json",
    )
    parser.add_argument(
        "--origins",
        type=Path,
        default=Path("D:/MDS650/b1v3_confirmation/predictors/b1_origins_target_blind.parquet"),
    )
    parser.add_argument(
        "--cache-root",
        type=Path,
        default=Path("D:/MDS650/b1v3_confirmation/cache/massive"),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("D:/MDS650/b1v3_confirmation/tmp/b1q_acquisition_v1"),
    )
    parser.add_argument("--execute", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Validate the frozen scope and optionally execute the resumable provider job."""
    args = _arguments(argv)
    inputs = load_frozen_build_inputs(
        args.plan,
        args.provider_report,
        args.provider_candidate_plan,
        args.source_confirmation_plan,
    )
    validate_b1q_run_contract(
        inputs=inputs,
        base_manifest_path=args.base_manifest,
        origins_path=args.origins,
    )
    secret_presence = {
        name: bool(os.environ.get(name)) for name in ("FMP_API_KEY", "MASSIVE_API_KEY")
    }
    if not all(secret_presence.values()):
        raise RuntimeError("B1V3_B1Q_REQUIRED_SECRET_MISSING")
    if not args.execute:
        print(
            json.dumps(
                {
                    "status": "READY_TARGET_BLIND_B1Q_ACQUISITION",
                    "session_count": len(inputs.all_sessions),
                    "origin_count": 38_664,
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
        sessions=inputs.all_sessions,
        origins_path=args.origins,
        contract_cache_filename="resolved_contracts_b1v3_canonical_spot_v1.json",
    )
    module.main(config)
    print(
        json.dumps(
            {
                "status": "PASS_TARGET_BLIND_B1Q_ACQUISITION",
                "session_count": len(inputs.all_sessions),
                "origin_count": 38_664,
                "outcome_read_count": 0,
                "safe_to_read_outcomes": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
