"""Run the source-bound B1v3 provider preflight without opening outcomes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import cast

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
    build_candidate_preflight_plan,
    canonical_json,
    derive_xnys_calendar_sessions,
    validate_json_schema,
)

ASSETS = ("SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META")
DEFAULT_CONFIRMATION_PLAN = Path("artifacts/b1v3_confirmation_plan/confirmation_plan.json")
DEFAULT_PLAN_OUTPUT = Path("artifacts/b1v3_provider_preflight_v2/candidate_preflight_plan.json")
DEFAULT_ARTIFACT_ROOT = Path("artifacts/b1v3_provider_preflight_v2")
DEFAULT_RAW_ROOT = Path("D:/MDS650/b1v3_provider_preflight_v2")
PLAN_SCHEMA = Path(
    "specs/001-pit-options-rv30/contracts/b1v3-provider-preflight-plan-v2.schema.json"
)
REPORT_SCHEMA = Path(
    "specs/001-pit-options-rv30/contracts/b1v3-provider-preflight-report-v2.schema.json"
)


def _arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check-only", action="store_true")
    mode.add_argument("--smoke", action="store_true")
    mode.add_argument("--execute", action="store_true")
    parser.add_argument("--confirmation-plan", type=Path, default=DEFAULT_CONFIRMATION_PLAN)
    parser.add_argument("--plan-output", type=Path, default=DEFAULT_PLAN_OUTPUT)
    parser.add_argument("--report-output", type=Path)
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    parser.add_argument("--smoke-asset", default="AAPL")
    parser.add_argument("--smoke-date")
    return parser.parse_args(argv)


def _load_json_object(path: Path) -> dict[str, object]:
    try:
        decoded: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise B1V3PreflightError("B1V3_PREFLIGHT_CONFIRMATION_PLAN_UNAVAILABLE") from exc
    if not isinstance(decoded, dict):
        raise B1V3PreflightError("B1V3_PREFLIGHT_CONFIRMATION_PLAN_INVALID")
    return cast(dict[str, object], decoded)


def _string_list(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise B1V3PreflightError("B1V3_PREFLIGHT_CONFIRMATION_PLAN_INVALID")
    return tuple(value)


def _build_full_plan(path: Path) -> CandidatePreflightPlan:
    source = _load_json_object(path)
    dates = (
        *_string_list(source.get("training_sessions")),
        *_string_list(source.get("confirmation_sessions")),
    )
    sessions = derive_xnys_calendar_sessions(dates)
    plan = build_candidate_preflight_plan(source, assets=ASSETS, calendar_sessions=sessions)
    validate_json_schema(
        plan.to_mapping(),
        schema_path=PLAN_SCHEMA,
        error_code="B1V3_PREFLIGHT_PLAN",
    )
    return plan


def _smoke_plan(
    plan: CandidatePreflightPlan,
    *,
    asset: str,
    session_date: str | None,
) -> CandidatePreflightPlan:
    if asset not in plan.assets:
        raise B1V3PreflightError("B1V3_PREFLIGHT_SMOKE_ASSET_INVALID")
    selected_date = session_date or plan.sessions[0].date
    selected = next((row for row in plan.sessions if row.date == selected_date), None)
    if selected is None:
        raise B1V3PreflightError("B1V3_PREFLIGHT_SMOKE_DATE_INVALID")
    base: dict[str, object] = {
        "schema_version": plan.schema_version,
        "status": plan.status,
        "target_blind": True,
        "outcome_read_count": 0,
        "assets": [asset],
        "sessions": [asdict(selected)],
        "training_session_count": int(selected.role == "training_warmup"),
        "confirmation_session_count": int(selected.role == "confirmation"),
        "source_confirmation_plan_sha256": plan.source_confirmation_plan_sha256,
    }
    digest = hashlib.sha256(canonical_json(base)).hexdigest()
    return CandidatePreflightPlan(
        schema_version=plan.schema_version,
        status=plan.status,
        target_blind=True,
        outcome_read_count=0,
        assets=(asset,),
        sessions=(
            CandidateSession(
                date=selected.date,
                role=selected.role,
                open_utc=selected.open_utc,
                close_utc=selected.close_utc,
                forecast_origin_utc=selected.forecast_origin_utc,
                forecast_origin_ns=selected.forecast_origin_ns,
                expected_regular_minutes=selected.expected_regular_minutes,
            ),
        ),
        training_session_count=cast(int, base["training_session_count"]),
        confirmation_session_count=cast(int, base["confirmation_session_count"]),
        source_confirmation_plan_sha256=plan.source_confirmation_plan_sha256,
        plan_sha256=digest,
    )


def _secrets() -> ProviderSecrets:
    return ProviderSecrets(
        fmp=os.environ.get("FMP_API_KEY", ""),
        unusual_whales=os.environ.get("UNUSUALWHALES_API_KEY", ""),
        massive=os.environ.get("MASSIVE_API_KEY", ""),
    )


def _free_bytes_on_data_volume(raw_root: Path) -> int:
    resolved = raw_root.resolve()
    if resolved.drive.upper() != "D:":
        raise B1V3PreflightError("B1V3_PREFLIGHT_RAW_ROOT_NOT_SAMSUNG_DRIVE")
    try:
        return int(shutil.disk_usage(f"{resolved.drive}\\").free)
    except OSError as exc:
        raise B1V3PreflightError("B1V3_PREFLIGHT_DATA_VOLUME_UNAVAILABLE") from exc


def _default_report_path(report: Mapping[str, object], *, smoke: bool) -> Path:
    digest = report.get("report_sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        raise B1V3PreflightError("B1V3_PREFLIGHT_REPORT_HASH_INVALID")
    if smoke:
        return DEFAULT_ARTIFACT_ROOT / "smoke" / f"provider_preflight_{digest[:16]}.json"
    if report.get("status") == "PASS_PROVIDER_PREFLIGHT_ASSUMPTION_BOUND":
        return DEFAULT_ARTIFACT_ROOT / "provider_preflight_report.json"
    return DEFAULT_ARTIFACT_ROOT / "blocked" / f"provider_preflight_{digest[:16]}.json"


def main(argv: Sequence[str] | None = None) -> int:
    args = _arguments(argv)
    try:
        full_plan = _build_full_plan(args.confirmation_plan)
        plan_state = write_if_identical(args.plan_output, full_plan.to_canonical_json() + b"\n")
        if args.check_only:
            print(
                json.dumps(
                    {
                        "mode": "CHECK_ONLY",
                        "plan_output_state": plan_state,
                        "session_count": len(full_plan.sessions),
                        "status": full_plan.status,
                    },
                    sort_keys=True,
                )
            )
            return 0
        run_plan = (
            _smoke_plan(full_plan, asset=args.smoke_asset, session_date=args.smoke_date)
            if args.smoke
            else full_plan
        )
        report = execute_preflight(
            run_plan,
            secrets=_secrets(),
            raw_root=args.raw_root,
            free_bytes=_free_bytes_on_data_volume(args.raw_root),
        )
        validate_json_schema(
            report,
            schema_path=REPORT_SCHEMA,
            error_code="B1V3_PREFLIGHT_REPORT",
        )
        report_path = args.report_output or _default_report_path(report, smoke=bool(args.smoke))
        report_state = write_if_identical(report_path, render_report(report))
    except B1V3PreflightError as exc:
        print(json.dumps({"code": str(exc), "status": "FAILED_CLOSED"}, sort_keys=True))
        return 2
    status = cast(str, report["status"])
    print(
        json.dumps(
            {
                "mode": "SMOKE" if args.smoke else "EXECUTE_FROZEN_90",
                "network_attempt_count": report["network_attempt_count"],
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
