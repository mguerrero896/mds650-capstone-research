"""Emit a local, source-bound MDS650 readiness v2 snapshot without outcomes.

The command reads only v2.3 target-blind predictors, provenance records and
provider-timing documentation. It has no provider endpoint, credential, model,
RV30, prediction, metric or OOS input.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mds650.confirmation_readiness_v2 import (  # noqa: E402
    SourceBoundConfirmationReadinessV2Config,
    build_source_bound_confirmation_readiness_v2,
)

DERIVED_ROOT = Path(r"D:\MDS650\phase6\derived\target_blind_v23_sourcebound_20260812")
ARTIFACT_ROOT = ROOT / "artifacts" / "target_blind_v23_sourcebound_20260812"
PANEL_MANIFEST = ARTIFACT_ROOT / "target_blind_common_predictor_manifest_v23.json"
PREREGISTRATION = ARTIFACT_ROOT / "next_confirmation_preregistration_v3.json"
PROVIDER_DOCS_AUDIT = (
    ROOT / "artifacts" / "provider_timing_v21" / "official_docs_audit_v1_20260812.json"
)
AVAILABILITY_SIDECAR = Path(
    r"D:\MDS650\phase6\derived\provider_timing_v22\b2_row_availability_v22.parquet"
)
SCHEMA = (
    ROOT / "specs" / "001-pit-options-rv30" / "contracts" / "confirmation-readiness-v2.schema.json"
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse only local source-bound inputs and a sanitized output location.

    Parameters
    ----------
    argv:
        Optional command-line tokens. ``None`` uses process arguments.

    Returns
    -------
    argparse.Namespace
        Parsed local-only paths. No provider or secret option exists.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel-manifest", type=Path, default=PANEL_MANIFEST)
    parser.add_argument("--preregistration", type=Path, default=PREREGISTRATION)
    parser.add_argument("--provider-docs-audit", type=Path, default=PROVIDER_DOCS_AUDIT)
    parser.add_argument(
        "--panel-path",
        type=Path,
        default=DERIVED_ROOT / "target_blind_common_predictors_v23.parquet",
    )
    parser.add_argument(
        "--common-path",
        type=Path,
        default=DERIVED_ROOT / "target_blind_common_complete_v23.parquet",
    )
    parser.add_argument("--availability-sidecar", type=Path, default=AVAILABILITY_SIDECAR)
    parser.add_argument(
        "--output",
        type=Path,
        default=ARTIFACT_ROOT / "confirmation_readiness_v2.json",
    )
    parser.add_argument("--schema", type=Path, default=SCHEMA)
    return parser.parse_args(argv)


def _read_json_object(path: Path, code: str) -> dict[str, Any]:
    """Read one JSON object or raise a sanitized deterministic error.

    Parameters
    ----------
    path:
        Local JSON input path.
    code:
        Error code that intentionally contains no local path.

    Returns
    -------
    dict[str, Any]
        Parsed JSON object.

    Raises
    ------
    ValueError
        If the path cannot be read, parsed or represented as an object.
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(code) from exc
    if not isinstance(payload, dict):
        raise ValueError(code)
    return payload


def _validate_output(report: Mapping[str, Any], schema_path: Path) -> None:
    """Require the readiness report to conform to its JSON Schema before writing.

    Parameters
    ----------
    report:
        Readiness report returned by the fail-closed module.
    schema_path:
        JSON Schema path for the v2 readiness contract.

    Raises
    ------
    ValueError
        If the schema cannot be read or the report violates it.
    """
    schema = _read_json_object(schema_path, "CONFIRMATION_READINESS_V2_SCHEMA_UNREADABLE")
    try:
        Draft202012Validator.check_schema(schema)
        errors = list(Draft202012Validator(schema).iter_errors(dict(report)))
    except Exception as exc:  # jsonschema exposes multiple public exception types.
        raise ValueError("CONFIRMATION_READINESS_V2_SCHEMA_UNREADABLE") from exc
    if errors:
        raise ValueError("CONFIRMATION_READINESS_V2_SCHEMA_VIOLATION")


def _write_json_if_new_or_identical(path: Path, payload: Mapping[str, Any]) -> None:
    """Write a deterministic JSON artifact or reject a conflicting prior record.

    Parameters
    ----------
    path:
        Destination artifact path.
    payload:
        JSON-compatible readiness report.

    Raises
    ------
    ValueError
        If a pre-existing file has different deterministic bytes.
    """
    encoded = json.dumps(dict(payload), indent=2, sort_keys=True) + "\n"
    try:
        if path.exists():
            if path.read_text(encoding="utf-8") != encoded:
                raise ValueError("CONFIRMATION_READINESS_V2_OUTPUT_CONFLICT")
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(encoded, encoding="utf-8")
    except OSError as exc:
        raise ValueError("CONFIRMATION_READINESS_V2_OUTPUT_UNWRITABLE") from exc


def main(argv: Sequence[str] | None = None) -> int:
    """Create or verify one target-blind v2 readiness artifact.

    Parameters
    ----------
    argv:
        Optional local-only command-line tokens.

    Returns
    -------
    int
        Zero when the deterministic, schema-valid record is created or already
        identical.

    Raises
    ------
    ValueError
        If any provenance input is unavailable, malformed or contract-invalid.
    """
    args = parse_args(argv)
    panel_manifest = _read_json_object(args.panel_manifest, "PANEL_MANIFEST_UNREADABLE")
    preregistration = _read_json_object(args.preregistration, "PREREGISTRATION_UNREADABLE")
    provider_docs_audit = _read_json_object(
        args.provider_docs_audit, "PROVIDER_DOCS_AUDIT_UNREADABLE"
    )
    report = build_source_bound_confirmation_readiness_v2(
        SourceBoundConfirmationReadinessV2Config(
            panel_manifest=panel_manifest,
            panel_manifest_path=args.panel_manifest,
            preregistration=preregistration,
            provider_docs_audit=provider_docs_audit,
            provider_docs_audit_path=args.provider_docs_audit,
            panel_path=args.panel_path,
            common_path=args.common_path,
            availability_sidecar_path=args.availability_sidecar,
        )
    )
    _validate_output(report, args.schema)
    _write_json_if_new_or_identical(args.output, report)
    return 0


if __name__ == "__main__":
    main()
