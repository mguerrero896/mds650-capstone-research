"""Run the bounded target-blind provider preflight for Phase 7 replication."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from mds650.b1_independent_replication import (  # noqa: E402
    build_replication_provider_preflight_plan,
)
from mds650.b1v3_confirmation import canonical_sha256  # noqa: E402
from mds650.b1v3_provider_preflight_runner_v2 import (  # noqa: E402
    ProviderSecrets,
    execute_preflight,
    render_report,
    write_if_identical,
)
from mds650.b1v3_provider_preflight_v2 import (  # noqa: E402
    B1V3PreflightError,
    CandidatePreflightPlan,
    validate_json_schema,
)


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise B1V3PreflightError("PHASE7_PREFLIGHT_PREREGISTRATION_UNAVAILABLE") from exc
    if not isinstance(value, dict):
        raise B1V3PreflightError("PHASE7_PREFLIGHT_PREREGISTRATION_INVALID")
    return value


def _smoke_plan(
    plan: CandidatePreflightPlan,
    *,
    asset: str,
    session_date: str | None,
) -> CandidatePreflightPlan:
    if asset not in plan.assets:
        raise B1V3PreflightError("PHASE7_PREFLIGHT_SMOKE_ASSET_INVALID")
    selected_date = session_date or plan.sessions[0].date
    selected = next((item for item in plan.sessions if item.date == selected_date), None)
    if selected is None:
        raise B1V3PreflightError("PHASE7_PREFLIGHT_SMOKE_DATE_INVALID")
    base: dict[str, object] = {
        "schema_version": plan.schema_version,
        "status": plan.status,
        "target_blind": True,
        "outcome_read_count": 0,
        "assets": [asset],
        "sessions": [
            {
                "date": selected.date,
                "role": selected.role,
                "open_utc": selected.open_utc,
                "close_utc": selected.close_utc,
                "forecast_origin_utc": selected.forecast_origin_utc,
                "forecast_origin_ns": selected.forecast_origin_ns,
                "expected_regular_minutes": selected.expected_regular_minutes,
            }
        ],
        "training_session_count": 0,
        "confirmation_session_count": 1,
        "source_confirmation_plan_sha256": plan.source_confirmation_plan_sha256,
    }
    return CandidatePreflightPlan(
        schema_version=plan.schema_version,
        status=plan.status,
        target_blind=True,
        outcome_read_count=0,
        assets=(asset,),
        sessions=(selected,),
        training_session_count=0,
        confirmation_session_count=1,
        source_confirmation_plan_sha256=plan.source_confirmation_plan_sha256,
        plan_sha256=canonical_sha256(base),
    )


def _secrets() -> ProviderSecrets:
    return ProviderSecrets(
        fmp=os.environ.get("FMP_API_KEY", ""),
        unusual_whales=os.environ.get("UNUSUALWHALES_API_KEY", ""),
        massive=os.environ.get("MASSIVE_API_KEY", ""),
    )


def _free_bytes(raw_root: Path) -> int:
    resolved = raw_root.resolve()
    if resolved.drive.upper() != "D:":
        raise B1V3PreflightError("PHASE7_PREFLIGHT_RAW_ROOT_NOT_SAMSUNG_DRIVE")
    try:
        return int(shutil.disk_usage(f"{resolved.drive}\\").free)
    except OSError as exc:
        raise B1V3PreflightError("PHASE7_PREFLIGHT_DATA_VOLUME_UNAVAILABLE") from exc


def _report_path(
    report: Mapping[str, object], *, output_root: Path, smoke: bool
) -> Path:
    digest = report.get("report_sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        raise B1V3PreflightError("PHASE7_PREFLIGHT_REPORT_HASH_INVALID")
    if smoke:
        return output_root / "smoke" / f"provider_preflight_{digest[:16]}.json"
    if report.get("status") == "PASS_PROVIDER_PREFLIGHT_ASSUMPTION_BOUND":
        return output_root / "provider_preflight_report.json"
    return output_root / "blocked" / f"provider_preflight_{digest[:16]}.json"


def _arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check-only", action="store_true")
    mode.add_argument("--smoke", action="store_true")
    mode.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--preregistration",
        type=Path,
        default=ROOT
        / "artifacts/b1_diagnostic_replication/preregistration/preregistration.json",
    )
    parser.add_argument(
        "--plan-schema",
        type=Path,
        default=ROOT
        / "specs/001-pit-options-rv30/contracts/"
        "b1-independent-replication-provider-plan-v1.schema.json",
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
        default=ROOT / "artifacts/b1_diagnostic_replication/provider_preflight",
    )
    parser.add_argument(
        "--raw-root",
        type=Path,
        default=Path(r"D:\MDS650\b1_diagnostic_replication\provider_preflight"),
    )
    parser.add_argument("--smoke-asset", default="AAPL")
    parser.add_argument("--smoke-date")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Validate the plan or execute one bounded authenticated preflight."""
    args = _arguments(argv)
    try:
        plan = build_replication_provider_preflight_plan(
            _read_object(args.preregistration)
        )
        validate_json_schema(
            plan.to_mapping(),
            schema_path=args.plan_schema,
            error_code="PHASE7_PREFLIGHT_PLAN",
        )
        plan_path = args.output_root / "candidate_preflight_plan.json"
        plan_state = write_if_identical(plan_path, plan.to_canonical_json() + b"\n")
        if args.check_only:
            print(
                json.dumps(
                    {
                        "mode": "CHECK_ONLY",
                        "plan_output_state": plan_state,
                        "session_count": len(plan.sessions),
                        "asset_count": len(plan.assets),
                        "outcome_read_count": 0,
                        "status": plan.status,
                    },
                    sort_keys=True,
                )
            )
            return 0
        run_plan = (
            _smoke_plan(
                plan,
                asset=args.smoke_asset,
                session_date=args.smoke_date,
            )
            if args.smoke
            else plan
        )
        report = execute_preflight(
            run_plan,
            secrets=_secrets(),
            raw_root=args.raw_root,
            free_bytes=_free_bytes(args.raw_root),
        )
        validate_json_schema(
            report,
            schema_path=args.report_schema,
            error_code="PHASE7_PREFLIGHT_REPORT",
        )
        report_path = _report_path(
            report, output_root=args.output_root, smoke=bool(args.smoke)
        )
        report_state = write_if_identical(report_path, render_report(report))
    except (B1V3PreflightError, ValueError) as exc:
        print(json.dumps({"code": str(exc), "status": "FAILED_CLOSED"}, sort_keys=True))
        return 2
    status = str(report["status"])
    print(
        json.dumps(
            {
                "mode": "SMOKE" if args.smoke else "EXECUTE_FROZEN_30",
                "network_attempt_count": report["network_attempt_count"],
                "outcome_read_count": 0,
                "report_output_state": report_state,
                "safe_to_acquire_predictors": report["safe_to_acquire_predictors"],
                "status": status,
            },
            sort_keys=True,
        )
    )
    return 0 if status == "PASS_PROVIDER_PREFLIGHT_ASSUMPTION_BOUND" else 3


if __name__ == "__main__":
    raise SystemExit(main())
