"""Freeze the target-blind B1v3 60/30 plan from authenticated provider evidence."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

from mds650.b1v3_confirmation import (
    build_confirmation_plan,
    canonical_sha256,
    enumerate_xnys_sessions,
    provider_passed_sessions_from_report,
    validate_confirmation_plan_schema,
    write_json_if_identical,
)


def _load_mapping(path: Path, *, code: str) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(code)
    decoded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError(code)
    return decoded


def _pretty_json_bytes(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, allow_nan=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def freeze_confirmation_plan(
    *,
    exposure_ledger_path: Path,
    pending_plan_path: Path,
    provider_report_path: Path,
    schema_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    """Create an immutable provider-bound confirmation plan.

    The command reads only compact target-blind metadata. It rederives the
    pending plan before freezing and never opens an outcome, loss, prediction,
    model or holdout payload.
    """
    ledger = _load_mapping(
        exposure_ledger_path,
        code="B1V3_EXPOSURE_LEDGER_MISSING_OR_INVALID",
    )
    pending = _load_mapping(
        pending_plan_path,
        code="B1V3_PENDING_PLAN_MISSING_OR_INVALID",
    )
    provider_report = _load_mapping(
        provider_report_path,
        code="B1V3_PROVIDER_PREFLIGHT_MISSING_OR_INVALID",
    )
    expected_ledger_hash = canonical_sha256(
        {key: value for key, value in ledger.items() if key != "ledger_sha256"}
    )
    if ledger.get("ledger_sha256") != expected_ledger_hash:
        raise ValueError("B1V3_EXPOSURE_LEDGER_HASH_INVALID")
    expected_pending_hash = canonical_sha256(
        {key: value for key, value in pending.items() if key != "plan_sha256"}
    )
    if pending.get("plan_sha256") != expected_pending_hash:
        raise ValueError("B1V3_PENDING_PLAN_HASH_INVALID")
    if (
        pending.get("status") != "PENDING_DATE_LEVEL_PROVIDER_PREFLIGHT"
        or pending.get("target_blind") is not True
        or pending.get("safe_to_acquire") is not False
        or pending.get("safe_to_read_outcomes") is not False
        or pending.get("outcome_read_count") != 0
        or pending.get("exposure_ledger_sha256") != expected_ledger_hash
    ):
        raise ValueError("B1V3_PENDING_PLAN_GATE_INVALID")
    validate_confirmation_plan_schema(pending, schema_path)

    first = pending.get("candidate_first_session")
    last = pending.get("candidate_last_session")
    if not isinstance(first, str) or not isinstance(last, str):
        raise ValueError("B1V3_PENDING_PLAN_CANDIDATES_INVALID")
    try:
        candidates = enumerate_xnys_sessions(date.fromisoformat(first), date.fromisoformat(last))
    except ValueError as exc:
        raise ValueError("B1V3_PENDING_PLAN_CANDIDATES_INVALID") from exc
    if pending.get("candidate_session_count") != len(candidates):
        raise ValueError("B1V3_PENDING_PLAN_CANDIDATES_INVALID")
    rederived_pending = build_confirmation_plan(
        exposure_ledger=ledger,
        candidate_sessions=candidates,
        provider_passed_sessions=None,
    )
    if rederived_pending != pending:
        raise ValueError("B1V3_PENDING_PLAN_REDERIVATION_FAILED")

    provider_sessions = provider_passed_sessions_from_report(provider_report)
    report_sha256 = provider_report.get("report_sha256")
    if not isinstance(report_sha256, str):
        raise ValueError("B1V3_PROVIDER_PREFLIGHT_HASH_INVALID")
    frozen = build_confirmation_plan(
        exposure_ledger=ledger,
        candidate_sessions=candidates,
        provider_passed_sessions=provider_sessions,
        provider_report_sha256=report_sha256,
    )
    validate_confirmation_plan_schema(frozen, schema_path)
    payload = _pretty_json_bytes(frozen)
    lowered = payload.decode("utf-8").lower()
    if "c:\\users\\" in lowered or "/users/" in lowered or "api_key" in lowered:
        raise ValueError("B1V3_CONFIRMATION_HYGIENE_FAILURE")
    write_json_if_identical(output_path, payload)
    return frozen


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exposure-ledger", type=Path, required=True)
    parser.add_argument("--pending-plan", type=Path, required=True)
    parser.add_argument("--provider-report", type=Path, required=True)
    parser.add_argument(
        "--schema",
        type=Path,
        default=Path("specs/001-pit-options-rv30/contracts/b1v3-confirmation-plan.schema.json"),
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the metadata-only confirmation-plan freezer."""
    args = _parse_args(argv)
    plan = freeze_confirmation_plan(
        exposure_ledger_path=args.exposure_ledger,
        pending_plan_path=args.pending_plan,
        provider_report_path=args.provider_report,
        schema_path=args.schema,
        output_path=args.output,
    )
    print(
        json.dumps(
            {
                "status": plan["status"],
                "plan_sha256": plan["plan_sha256"],
                "safe_to_acquire": plan["safe_to_acquire"],
                "safe_to_read_outcomes": plan["safe_to_read_outcomes"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
