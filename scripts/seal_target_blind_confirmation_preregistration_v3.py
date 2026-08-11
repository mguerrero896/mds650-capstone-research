"""Seal a source-bound, target-blind preregistration before method freeze.

This command reads only sanitized JSON contracts. It cannot open predictor
Parquet, RV30, outcomes, predictions, metrics, model objects, or OOS data, and
it has no network or provider-credential interface.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mds650.target_blind_preregistration_v3 import (  # noqa: E402
    build_sourcebound_preregistration_v3,
)

PANEL_MANIFEST = (
    ROOT
    / "artifacts"
    / "target_blind_v23_sourcebound_20260812"
    / "target_blind_common_predictor_manifest_v23.json"
)
TEMPLATE_PREREGISTRATION = (
    ROOT / "artifacts" / "target_blind_v22" / "next_confirmation_preregistration_v2.json"
)
OUTPUT = (
    ROOT
    / "artifacts"
    / "target_blind_v23_sourcebound_20260812"
    / "next_confirmation_preregistration_v3.json"
)
PANEL_SCHEMA = (
    ROOT
    / "specs"
    / "001-pit-options-rv30"
    / "contracts"
    / "target-blind-common-predictor-manifest-v23.schema.json"
)
TEMPLATE_SCHEMA = (
    ROOT
    / "specs"
    / "001-pit-options-rv30"
    / "contracts"
    / "target-blind-confirmation-preregistration-v22.schema.json"
)
OUTPUT_SCHEMA = (
    ROOT
    / "specs"
    / "001-pit-options-rv30"
    / "contracts"
    / "target-blind-confirmation-preregistration-v3.schema.json"
)
_SEALER_SOURCE_PATHS = (
    "pyproject.toml",
    "uv.lock",
    "src/mds650/provider_timing_v21.py",
    "src/mds650/target_blind_preregistration_v3.py",
    "scripts/seal_target_blind_confirmation_preregistration_v3.py",
    "specs/001-pit-options-rv30/contracts/target-blind-common-predictor-manifest-v23.schema.json",
    "specs/001-pit-options-rv30/contracts/target-blind-confirmation-preregistration-v22.schema.json",
    "specs/001-pit-options-rv30/contracts/target-blind-confirmation-preregistration-v3.schema.json",
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse local contract paths for an offline source-bound seal.

    Parameters
    ----------
    argv:
        Optional command-line tokens. ``None`` uses process arguments.

    Returns
    -------
    argparse.Namespace
        Parsed local JSON paths only. No network endpoint or secret option is
        accepted.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel-manifest", type=Path, default=PANEL_MANIFEST)
    parser.add_argument("--template-preregistration", type=Path, default=TEMPLATE_PREREGISTRATION)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--panel-schema", type=Path, default=PANEL_SCHEMA)
    parser.add_argument("--template-schema", type=Path, default=TEMPLATE_SCHEMA)
    parser.add_argument("--output-schema", type=Path, default=OUTPUT_SCHEMA)
    return parser.parse_args(argv)


def require_committed_sealer_source() -> None:
    """Reject a seal whose executable sources or lockfile are uncommitted.

    Raises
    ------
    ValueError
        If any local code, schema, or lockfile that determines the seal is
        modified, deleted, or untracked.
    """
    completed = subprocess.run(
        ["git", "status", "--porcelain", "--", *_SEALER_SOURCE_PATHS],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    if completed.stdout.strip():
        raise ValueError("TARGET_BLIND_V3_SEALER_SOURCE_UNCOMMITTED")


def write_if_new_or_identical(path: Path, content: bytes) -> None:
    """Write immutable bytes or retain an exact deterministic replay.

    Parameters
    ----------
    path:
        Final local artifact path.
    content:
        Complete deterministic byte payload for that artifact.

    Raises
    ------
    FileExistsError
        If a prior artifact exists with bytes different from ``content``.
    OSError
        If local output creation fails.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.part")
    try:
        temporary.write_bytes(content)
        if path.exists():
            if temporary.read_bytes() != path.read_bytes():
                raise FileExistsError("TARGET_BLIND_V3_OUTPUT_EXISTS_WITH_DIFFERENT_BYTES")
            return
        try:
            os.link(temporary, path)
        except FileExistsError:
            if temporary.read_bytes() != path.read_bytes():
                raise FileExistsError(
                    "TARGET_BLIND_V3_OUTPUT_EXISTS_WITH_DIFFERENT_BYTES"
                ) from None
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: Sequence[str] | None = None) -> int:
    """Seal the v3 metadata binding without opening any predictive payload.

    Parameters
    ----------
    argv:
        Optional local command-line tokens.

    Returns
    -------
    int
        Zero after a schema-valid, immutable v3 preregistration is present.

    Raises
    ------
    FileNotFoundError
        If a required local contract file is absent.
    ValueError
        If contract validation, source cleanliness, output schema validation,
        or immutable-output comparison fails.
    """
    args = parse_args(argv)
    require_committed_sealer_source()
    panel_manifest = _read_json_object(args.panel_manifest, "TARGET_BLIND_V3_PANEL_MANIFEST")
    template = _read_json_object(
        args.template_preregistration, "TARGET_BLIND_V3_TEMPLATE_PREREGISTRATION"
    )
    _validate_schema(panel_manifest, args.panel_schema, "TARGET_BLIND_V3_PANEL_SCHEMA")
    _validate_schema(template, args.template_schema, "TARGET_BLIND_V3_TEMPLATE_SCHEMA")
    preregistration = build_sourcebound_preregistration_v3(
        panel_manifest=panel_manifest,
        template_preregistration=template,
        panel_manifest_file_sha256=_sha256_file(args.panel_manifest),
        template_file_sha256=_sha256_file(args.template_preregistration),
        source_commit=_source_commit(),
    )
    _validate_schema(preregistration, args.output_schema, "TARGET_BLIND_V3_OUTPUT_SCHEMA")
    write_if_new_or_identical(
        args.output,
        (json.dumps(preregistration, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode(
            "utf-8"
        ),
    )
    print("TARGET_BLIND_V3_PREREGISTRATION=SEALED")
    print("SAFE_TO_RECONCILE_EXISTING_RESULTS=NO")
    print("SAFE_TO_OPEN_OR_EVALUATE_OOS=NO")
    return 0


def _source_commit() -> str:
    """Return the latest source-history commit without contacting a remote."""
    completed = subprocess.run(
        ["git", "log", "-1", "--format=%H", "--", *_SEALER_SOURCE_PATHS],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    value = completed.stdout.strip()
    if len(value) != 40:
        raise ValueError("TARGET_BLIND_V3_SEALER_SOURCE_HISTORY_UNAVAILABLE")
    return value


def _read_json_object(path: Path, error_prefix: str) -> dict[str, Any]:
    """Read one UTF-8 JSON object or raise a stable fail-closed error."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{error_prefix}_INVALID_JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{error_prefix}_NOT_OBJECT")
    return value


def _validate_schema(document: Mapping[str, Any], schema_path: Path, error_prefix: str) -> None:
    """Validate a JSON object against a local Draft 2020-12 schema."""
    schema = _read_json_object(schema_path, error_prefix)
    try:
        Draft202012Validator.check_schema(schema)
        errors = list(Draft202012Validator(schema).iter_errors(document))
    except Exception as exc:  # pragma: no cover - jsonschema internal failure
        raise ValueError(f"{error_prefix}_INVALID") from exc
    if errors:
        raise ValueError(f"{error_prefix}_VIOLATION")


def _sha256_file(path: Path) -> str:
    """Return a streaming SHA-256 for one compact local JSON contract."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
