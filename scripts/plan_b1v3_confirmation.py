"""Create a date-only B1v3 exposure ledger and provisional/frozen 60/30 plan."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable, Mapping
from datetime import date
from importlib import import_module
from pathlib import Path
from typing import Any, Protocol, cast

from mds650.b1v3_confirmation import (
    ExposureSource,
    build_confirmation_plan,
    build_session_exposure_ledger,
    enumerate_xnys_sessions,
    write_json_if_identical,
)


class _SchemaValidator(Protocol):
    """Minimal runtime boundary for untyped jsonschema."""

    @classmethod
    def check_schema(cls, schema: Mapping[str, Any]) -> None: ...

    def __init__(self, schema: Mapping[str, Any]) -> None: ...

    def iter_errors(self, instance: object) -> Iterable[object]: ...


def _pretty_json_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, allow_nan=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _validate_schema(document: Mapping[str, Any], schema_path: Path) -> None:
    if not schema_path.is_file():
        raise ValueError("B1V3_CONFIRMATION_SCHEMA_MISSING")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    if not isinstance(schema, dict):
        raise ValueError("B1V3_CONFIRMATION_SCHEMA_INVALID")
    module = import_module("jsonschema")
    raw = getattr(module, "Draft202012Validator", None)
    if raw is None or not callable(raw):
        raise ValueError("B1V3_CONFIRMATION_JSONSCHEMA_RUNTIME_INVALID")
    validator_type = cast(type[_SchemaValidator], raw)
    validator_type.check_schema(schema)
    if any(validator_type(schema).iter_errors(document)):
        raise ValueError("B1V3_CONFIRMATION_SCHEMA_VALIDATION_FAILED")


def _load_provider_passed_sessions(path: Path | None) -> list[str] | None:
    if path is None:
        return None
    if not path.is_file():
        raise ValueError("B1V3_PROVIDER_PREFLIGHT_MISSING")
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("B1V3_PROVIDER_PREFLIGHT_INVALID")
    sessions = document.get("common_passed_sessions")
    if not isinstance(sessions, list) or not all(isinstance(value, str) for value in sessions):
        raise ValueError("B1V3_PROVIDER_PREFLIGHT_INVALID")
    return list(sessions)


def plan_confirmation(
    *,
    exposure_sources: list[ExposureSource],
    candidate_start: date,
    candidate_end: date,
    provider_preflight_path: Path | None,
    ledger_path: Path,
    plan_path: Path,
    schema_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build, validate and immutably write the date-only planning package.

    Parameters
    ----------
    exposure_sources:
        Explicit date-only prior-exposure manifests.
    candidate_start, candidate_end:
        Bounds used only to enumerate official XNYS sessions.
    provider_preflight_path:
        Optional schema-controlled result whose ``common_passed_sessions`` are
        the only dates allowed to become a frozen 60/30 plan.
    ledger_path, plan_path:
        New immutable JSON outputs.
    schema_path:
        Draft 2020-12 plan schema.

    Returns
    -------
    tuple[dict[str, Any], dict[str, Any]]
        Exposure ledger and confirmation plan.

    Raises
    ------
    ValueError
        On invalid sources, dates, provider evidence, schema or output conflict.
    """
    ledger = build_session_exposure_ledger(exposure_sources)
    candidates = enumerate_xnys_sessions(candidate_start, candidate_end)
    provider_sessions = _load_provider_passed_sessions(provider_preflight_path)
    plan = build_confirmation_plan(
        exposure_ledger=ledger,
        candidate_sessions=candidates,
        provider_passed_sessions=provider_sessions,
    )
    _validate_schema(plan, schema_path)
    ledger_bytes = _pretty_json_bytes(ledger)
    plan_bytes = _pretty_json_bytes(plan)
    lowered = (ledger_bytes + plan_bytes).decode("utf-8").lower()
    if "c:\\users\\" in lowered or "/users/" in lowered or "api_key" in lowered:
        raise ValueError("B1V3_CONFIRMATION_HYGIENE_FAILURE")
    write_json_if_identical(ledger_path, ledger_bytes)
    write_json_if_identical(plan_path, plan_bytes)
    return ledger, plan


def _parse_source(value: str) -> ExposureSource:
    logical_name, separator, raw_path = value.partition("=")
    if not separator or not logical_name or not raw_path:
        raise argparse.ArgumentTypeError("Expected LOGICAL_NAME=PATH")
    return ExposureSource(logical_name=logical_name, path=Path(raw_path))


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exposure-source", action="append", type=_parse_source, required=True)
    parser.add_argument("--candidate-start", type=date.fromisoformat, required=True)
    parser.add_argument("--candidate-end", type=date.fromisoformat, required=True)
    parser.add_argument("--provider-preflight", type=Path)
    parser.add_argument("--ledger-output", type=Path, required=True)
    parser.add_argument("--plan-output", type=Path, required=True)
    parser.add_argument(
        "--schema",
        type=Path,
        default=Path("specs/001-pit-options-rv30/contracts/b1v3-confirmation-plan.schema.json"),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the date-only CLI without reading targets, metrics or results."""
    args = _parse_args(argv)
    _ledger, plan = plan_confirmation(
        exposure_sources=args.exposure_source,
        candidate_start=args.candidate_start,
        candidate_end=args.candidate_end,
        provider_preflight_path=args.provider_preflight,
        ledger_path=args.ledger_output,
        plan_path=args.plan_output,
        schema_path=args.schema,
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
