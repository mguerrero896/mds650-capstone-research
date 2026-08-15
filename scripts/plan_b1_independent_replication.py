"""Freeze the sign-agnostic B1/B2 independent-replication plan."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

import exchange_calendars as xcals  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from mds650.b1_independent_replication import (  # noqa: E402
    build_exposure_ledger,
    build_replication_preregistration,
    collect_exposed_result_dates,
)
from mds650.b1v3_confirmation import (  # noqa: E402
    canonical_sha256,
    sha256_file,
    validate_confirmation_plan_schema,
    write_json_if_identical,
)


def _read_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"PHASE7_INPUT_MISSING:{path.name}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"PHASE7_INPUT_NOT_OBJECT:{path.name}")
    return value


def _sessions(start: str, end: str) -> list[str]:
    calendar = xcals.get_calendar("XNYS")
    return [str(value.date()) for value in calendar.sessions_in_range(start, end)]


def _payload(document: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            document,
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _hygiene(payload: bytes) -> None:
    lowered = payload.lower()
    forbidden = (b"c:\\users\\", b"c:/users/", b"api_key", b"apikey", b"bearer ")
    if any(token in lowered for token in forbidden):
        raise ValueError("PHASE7_PREREGISTRATION_HYGIENE_FAILURE")


def freeze_plan(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build, validate, and immutably write the Phase 7 zero-read freeze."""
    phase5 = _read_object(args.phase5_exposure_ledger)
    b1v3 = _read_object(args.b1v3_plan)
    independent = _read_object(args.independent_window)
    exposed = collect_exposed_result_dates(
        phase5_ledger=phase5,
        b1v3_plan=b1v3,
        independent_window=independent,
    )
    training = _sessions("2024-09-16", "2024-12-09")
    replication = _sessions("2024-12-10", "2025-01-24")
    design_hash = sha256_file(args.design)
    code_hash = canonical_sha256(
        {
            "module_sha256": sha256_file(args.code_module),
            "planner_sha256": sha256_file(Path(__file__)),
        }
    )
    ledger = build_exposure_ledger(
        training_sessions=training,
        replication_sessions=replication,
        exposed_result_dates=exposed,
        prior_evidence_cutoff_session=date.fromisoformat("2024-12-09"),
        design_sha256=design_hash,
    )
    preregistration = build_replication_preregistration(
        exposure_ledger=ledger,
        design_sha256=design_hash,
        code_sha256=code_hash,
        uv_lock_sha256=sha256_file(args.uv_lock),
    )
    validate_confirmation_plan_schema(ledger, args.exposure_schema)
    validate_confirmation_plan_schema(preregistration, args.preregistration_schema)
    ledger_payload = _payload(ledger)
    preregistration_payload = _payload(preregistration)
    _hygiene(ledger_payload)
    _hygiene(preregistration_payload)
    write_json_if_identical(args.output_root / "exposure_ledger.json", ledger_payload)
    write_json_if_identical(
        args.output_root / "preregistration.json", preregistration_payload
    )
    return ledger, preregistration


def _parser() -> argparse.ArgumentParser:
    contracts = ROOT / "specs" / "001-pit-options-rv30" / "contracts"
    parser = argparse.ArgumentParser(
        description="Freeze the zero-read B1/B2 independent-replication plan."
    )
    parser.add_argument(
        "--phase5-exposure-ledger",
        type=Path,
        default=ROOT / "artifacts/b1v3_confirmation_plan/session_exposure_ledger.json",
    )
    parser.add_argument(
        "--b1v3-plan",
        type=Path,
        default=ROOT
        / "artifacts/b1v3_confirmation_plan/confirmation_plan_provider_passed.json",
    )
    parser.add_argument(
        "--independent-window",
        type=Path,
        default=ROOT / "artifacts/independent_replication/window_manifest.json",
    )
    parser.add_argument(
        "--design",
        type=Path,
        default=ROOT
        / "docs/superpowers/specs/2026-08-15-b1-diagnosis-independent-replication-design.md",
    )
    parser.add_argument(
        "--code-module",
        type=Path,
        default=ROOT / "src/mds650/b1_independent_replication.py",
    )
    parser.add_argument("--uv-lock", type=Path, default=ROOT / "uv.lock")
    parser.add_argument(
        "--exposure-schema",
        type=Path,
        default=contracts / "b1-independent-replication-exposure-v1.schema.json",
    )
    parser.add_argument(
        "--preregistration-schema",
        type=Path,
        default=contracts
        / "b1-independent-replication-preregistration-v1.schema.json",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=ROOT / "artifacts/b1_diagnostic_replication/preregistration",
    )
    return parser


def main() -> int:
    """Run the metadata-only zero-read freeze."""
    ledger, preregistration = freeze_plan(_parser().parse_args())
    print(
        json.dumps(
            {
                "status": preregistration["status"],
                "training_sessions": len(preregistration["training_sessions"]),
                "replication_sessions": len(preregistration["replication_sessions"]),
                "exposed_result_dates": len(ledger["exposed_result_dates"]),
                "replication_target_reads": 0,
                "ledger_sha256": ledger["ledger_sha256"],
                "preregistration_sha256": preregistration["manifest_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
