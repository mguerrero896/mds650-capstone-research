"""Add a target-blind SPY/QQQ provider preflight for predeclared B0 controls."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from mds650.b1v3_confirmation import canonical_sha256
from mds650.b1v3_provider_preflight_runner_v2 import (
    ProviderSecrets,
    execute_preflight,
    render_report,
    write_if_identical,
)
from mds650.b1v3_provider_preflight_v2 import (
    B1V3PreflightError,
    CandidatePreflightPlan,
    CandidateSession,
    validate_json_schema,
)

ROOT = Path(__file__).resolve().parents[1]
MARKET_CONTROLS = ("SPY", "QQQ")


def _read_object(path: Path, *, code: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise B1V3PreflightError(code) from exc
    if not isinstance(value, dict):
        raise B1V3PreflightError(code)
    return value


def _candidate_session(raw: object) -> CandidateSession:
    if not isinstance(raw, Mapping):
        raise B1V3PreflightError("MARKET_CONTROL_SESSION_INVALID")
    try:
        return CandidateSession(
            date=str(raw["date"]),
            role=str(raw["role"]),
            open_utc=str(raw["open_utc"]),
            close_utc=str(raw["close_utc"]),
            forecast_origin_utc=str(raw["forecast_origin_utc"]),
            forecast_origin_ns=int(str(raw["forecast_origin_ns"])),
            expected_regular_minutes=int(str(raw["expected_regular_minutes"])),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise B1V3PreflightError("MARKET_CONTROL_SESSION_INVALID") from exc


def build_market_control_plan(
    source: Mapping[str, object],
) -> CandidatePreflightPlan:
    """Freeze only SPY/QQQ while preserving the preregistered date block.

    This is an engineering amendment for B0 controls already present in the
    frozen information set. It does not change targets, models, metrics,
    hypotheses or the six outcome assets.
    """
    stored = source.get("plan_sha256")
    unsigned = {key: value for key, value in source.items() if key != "plan_sha256"}
    if (
        not isinstance(stored, str)
        or stored != canonical_sha256(unsigned)
        or source.get("status")
        != "FROZEN_TARGET_BLIND_PENDING_PROVIDER_EXECUTION"
        or source.get("target_blind") is not True
        or source.get("outcome_read_count") != 0
    ):
        raise B1V3PreflightError("MARKET_CONTROL_SOURCE_PLAN_INVALID")
    raw_sessions = source.get("sessions")
    if not isinstance(raw_sessions, list) or not raw_sessions:
        raise B1V3PreflightError("MARKET_CONTROL_SESSION_INVALID")
    sessions = tuple(_candidate_session(value) for value in raw_sessions)
    if any(value.role != "confirmation" for value in sessions):
        raise B1V3PreflightError("MARKET_CONTROL_SESSION_ROLE_INVALID")
    source_hash = source.get("source_confirmation_plan_sha256")
    if not isinstance(source_hash, str) or len(source_hash) != 64:
        raise B1V3PreflightError("MARKET_CONTROL_SOURCE_BINDING_INVALID")
    base: dict[str, object] = {
        "schema_version": "b1-independent-replication-market-control-plan-1.0",
        "status": "FROZEN_TARGET_BLIND_PENDING_PROVIDER_EXECUTION",
        "target_blind": True,
        "outcome_read_count": 0,
        "assets": list(MARKET_CONTROLS),
        "sessions": [
            {
                "date": value.date,
                "role": value.role,
                "open_utc": value.open_utc,
                "close_utc": value.close_utc,
                "forecast_origin_utc": value.forecast_origin_utc,
                "forecast_origin_ns": value.forecast_origin_ns,
                "expected_regular_minutes": value.expected_regular_minutes,
            }
            for value in sessions
        ],
        "training_session_count": 0,
        "confirmation_session_count": len(sessions),
        "source_confirmation_plan_sha256": source_hash,
    }
    return CandidatePreflightPlan(
        schema_version=str(base["schema_version"]),
        status=str(base["status"]),
        target_blind=True,
        outcome_read_count=0,
        assets=MARKET_CONTROLS,
        sessions=sessions,
        training_session_count=0,
        confirmation_session_count=len(sessions),
        source_confirmation_plan_sha256=source_hash,
        plan_sha256=canonical_sha256(base),
    )


def _secrets() -> ProviderSecrets:
    return ProviderSecrets(
        fmp=os.environ.get("FMP_API_KEY", ""),
        unusual_whales=os.environ.get("UNUSUALWHALES_API_KEY", ""),
        massive=os.environ.get("MASSIVE_API_KEY", ""),
    )


def _arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check-only", action="store_true")
    mode.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--source-plan",
        type=Path,
        default=ROOT
        / "artifacts/b1_diagnostic_replication/provider_preflight/"
        "candidate_preflight_plan.json",
    )
    parser.add_argument(
        "--plan-schema",
        type=Path,
        default=ROOT
        / "specs/001-pit-options-rv30/contracts/"
        "b1-independent-replication-market-control-plan-v1.schema.json",
    )
    parser.add_argument(
        "--report-schema",
        type=Path,
        default=ROOT
        / "specs/001-pit-options-rv30/contracts/"
        "b1v3-provider-preflight-report-v2.schema.json",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=ROOT
        / "artifacts/b1_diagnostic_replication/provider_preflight/market_controls",
    )
    parser.add_argument(
        "--raw-root",
        type=Path,
        default=Path(r"D:\MDS650\b1_diagnostic_replication\provider_preflight"),
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Freeze the supplement, then optionally execute authenticated probes."""
    args = _arguments(argv)
    try:
        plan = build_market_control_plan(
            _read_object(args.source_plan, code="MARKET_CONTROL_SOURCE_PLAN_MISSING")
        )
        validate_json_schema(
            plan.to_mapping(),
            schema_path=args.plan_schema,
            error_code="MARKET_CONTROL_PLAN",
        )
        plan_state = write_if_identical(
            args.output_root / "candidate_plan.json",
            plan.to_canonical_json() + b"\n",
        )
        if args.check_only:
            print(
                json.dumps(
                    {
                        "status": "FROZEN_TARGET_BLIND_MARKET_CONTROL_SUPPLEMENT",
                        "assets": list(plan.assets),
                        "session_count": len(plan.sessions),
                        "plan_output_state": plan_state,
                        "outcome_read_count": 0,
                    },
                    sort_keys=True,
                )
            )
            return 0
        resolved = args.raw_root.resolve()
        if resolved.drive.upper() != "D:":
            raise B1V3PreflightError("MARKET_CONTROL_RAW_ROOT_NOT_SAMSUNG_DRIVE")
        report = execute_preflight(
            plan,
            secrets=_secrets(),
            raw_root=args.raw_root,
            free_bytes=int(shutil.disk_usage(f"{resolved.drive}\\").free),
        )
        validate_json_schema(
            report,
            schema_path=args.report_schema,
            error_code="MARKET_CONTROL_REPORT",
        )
        report_state = write_if_identical(
            args.output_root / "provider_preflight_report.json",
            render_report(report),
        )
    except (B1V3PreflightError, ValueError) as exc:
        print(json.dumps({"status": "FAILED_CLOSED", "code": str(exc)}, sort_keys=True))
        return 2
    print(
        json.dumps(
            {
                "status": report["status"],
                "network_attempt_count": report["network_attempt_count"],
                "outcome_read_count": 0,
                "report_output_state": report_state,
            },
            sort_keys=True,
        )
    )
    return int(report["status"] != "PASS_PROVIDER_PREFLIGHT_ASSUMPTION_BOUND")


if __name__ == "__main__":
    raise SystemExit(main())
