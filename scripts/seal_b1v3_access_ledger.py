"""Seal the B1v3 one-read authorization after every pre-confirmation gate passes."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mds650.b1v3_confirmation import (  # noqa: E402
    canonical_sha256,
    sha256_file,
    validate_confirmation_plan_schema,
)
from mds650.b1v3_evaluation import build_b1v3_access_ledger  # noqa: E402

_REQUIRED_GATES: Final[tuple[str, ...]] = (
    "focused_tests",
    "full_tests",
    "ruff",
    "mypy",
    "coverage",
    "json_schema",
    "no_leakage",
    "hygiene",
    "deterministic_replay",
    "clean_install",
    "spec_kit",
    "disk_gate",
)
_FORBIDDEN: Final[tuple[bytes, ...]] = (
    b"c:\\users\\",
    b"c:/users/",
    b"d:\\mds650",
    b"d:/mds650",
    b"api_key",
    b"apikey",
    b"authorization",
    b"bearer ",
)


def _read_mapping(path: Path, error: str) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(error) from exc
    if not isinstance(document, dict):
        raise ValueError(error)
    return document


def _validate_self_hash(document: Mapping[str, Any], error: str) -> None:
    stored = document.get("manifest_sha256")
    unsigned = {key: value for key, value in document.items() if key != "manifest_sha256"}
    if not isinstance(stored, str) or stored != canonical_sha256(unsigned):
        raise ValueError(error)


def _write_json_if_identical(path: Path, document: Mapping[str, Any]) -> str:
    """Write a sanitized JSON artifact atomically or verify byte identity."""
    payload = (json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode(
        "utf-8"
    )
    if any(token in payload.lower() for token in _FORBIDDEN):
        raise ValueError("B1V3_ACCESS_OUTPUT_HYGIENE_INVALID")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise ValueError(f"B1V3_ACCESS_OUTPUT_CONFLICT:{path.name}")
        return sha256_file(path)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".part", dir=path.parent)
    os.close(descriptor)
    temporary = Path(name)
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return sha256_file(path)


def _validated_quality_prerequisites(
    quality: Mapping[str, Any],
    *,
    preregistration_manifest_sha256: str,
    method_freeze_manifest_sha256: str,
    common_panel_sha256: str,
    timing_panel_manifest_sha256: str,
) -> dict[str, bool]:
    """Map a self-hashed quality report to the exact access prerequisites.

    Raises
    ------
    ValueError
        If status, read counters, source bindings, gate set, evidence hashes, or
        security assertions are incomplete.
    """
    _validate_self_hash(quality, "B1V3_QUALITY_SELF_HASH_INVALID")
    bindings = quality.get("source_bindings")
    gates = quality.get("gates")
    security = quality.get("security")
    if (
        quality.get("status") != "PASS_B1V3_PRE_CONFIRMATION_QUALITY"
        or quality.get("target_blind") is not True
        or quality.get("outcome_read_count") != 1
        or quality.get("training_read_count") != 1
        or quality.get("confirmation_read_count") != 0
        or not isinstance(bindings, Mapping)
        or not isinstance(security, Mapping)
        or security.get("secret_values_emitted") is not False
        or security.get("personal_paths_emitted") is not False
    ):
        raise ValueError("B1V3_QUALITY_STATUS_INVALID")
    expected_bindings = {
        "preregistration_manifest_sha256": preregistration_manifest_sha256,
        "method_freeze_manifest_sha256": method_freeze_manifest_sha256,
        "common_panel_sha256": common_panel_sha256,
        "timing_panel_manifest_sha256": timing_panel_manifest_sha256,
    }
    if dict(bindings) != expected_bindings:
        raise ValueError("B1V3_QUALITY_BINDING_INVALID")
    if not isinstance(gates, Mapping) or set(gates) != set(_REQUIRED_GATES):
        raise ValueError("B1V3_QUALITY_GATE_SET_INVALID")
    prerequisites: dict[str, bool] = {}
    for name in _REQUIRED_GATES:
        gate = gates.get(name)
        evidence = gate.get("evidence_sha256") if isinstance(gate, Mapping) else None
        if (
            not isinstance(gate, Mapping)
            or gate.get("status") != "PASS"
            or not isinstance(evidence, str)
            or len(evidence) != 64
            or any(character not in "0123456789abcdef" for character in evidence)
        ):
            raise ValueError(f"B1V3_QUALITY_GATE_FAILED:{name}")
        prerequisites[name] = True
    return prerequisites


def seal_b1v3_access_ledger(
    *,
    preregistration_path: Path,
    preregistration_schema_path: Path,
    method_freeze_path: Path,
    method_freeze_schema_path: Path,
    common_manifest_path: Path,
    common_manifest_schema_path: Path,
    common_panel_path: Path,
    timing_manifest_path: Path,
    timing_manifest_schema_path: Path,
    quality_report_path: Path,
    quality_report_schema_path: Path,
    access_schema_path: Path,
    confirmation_code_paths: Sequence[Path],
    uv_lock_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    """Validate all source bindings and immutably seal one confirmation access."""
    preregistration = _read_mapping(preregistration_path, "B1V3_ACCESS_PREREGISTRATION_INVALID")
    method_freeze = _read_mapping(method_freeze_path, "B1V3_ACCESS_METHOD_FREEZE_INVALID")
    common = _read_mapping(common_manifest_path, "B1V3_ACCESS_COMMON_MANIFEST_INVALID")
    timing = _read_mapping(timing_manifest_path, "B1V3_ACCESS_TIMING_MANIFEST_INVALID")
    quality = _read_mapping(quality_report_path, "B1V3_ACCESS_QUALITY_REPORT_INVALID")
    for document, schema in (
        (preregistration, preregistration_schema_path),
        (method_freeze, method_freeze_schema_path),
        (common, common_manifest_schema_path),
        (timing, timing_manifest_schema_path),
        (quality, quality_report_schema_path),
    ):
        validate_confirmation_plan_schema(document, schema)
        _validate_self_hash(document, "B1V3_ACCESS_SOURCE_SELF_HASH_INVALID")
    common_output = common.get("output")
    timing_bindings = timing.get("source_bindings")
    common_panel_sha256 = sha256_file(common_panel_path)
    if (
        preregistration.get("status") != "FROZEN_BEFORE_CONFIRMATION"
        or preregistration.get("safe_to_evaluate_b1v3") != "NO"
        or preregistration.get("confirmation_read_count") != 0
        or method_freeze.get("status") != "FROZEN_AFTER_TRAINING_BEFORE_CONFIRMATION"
        or method_freeze.get("safe_to_read_confirmation") is not False
        or method_freeze.get("training_read_count") != 1
        or method_freeze.get("confirmation_read_count") != 0
        or method_freeze.get("preregistration_manifest_sha256")
        != preregistration.get("manifest_sha256")
        or method_freeze.get("common_panel_sha256") != common_panel_sha256
        or common.get("status") != "PASS_TARGET_BLIND_COMMON_PREDICTOR_PANEL"
        or common.get("target_blind") is not True
        or not isinstance(common_output, Mapping)
        or common_output.get("sha256") != common_panel_sha256
        or preregistration.get("common_predictor_panel_sha256") != common_panel_sha256
        or timing.get("status") != "PASS_TARGET_BLIND_TIMING_COMMON_PANELS"
        or timing.get("target_blind") is not True
        or timing.get("outcome_read_count") != 0
        or not isinstance(timing_bindings, Mapping)
        or timing_bindings.get("common_panel_sha256") != common_panel_sha256
    ):
        raise ValueError("B1V3_ACCESS_SOURCE_BINDING_INVALID")
    prerequisites = _validated_quality_prerequisites(
        quality,
        preregistration_manifest_sha256=str(preregistration["manifest_sha256"]),
        method_freeze_manifest_sha256=str(method_freeze["manifest_sha256"]),
        common_panel_sha256=common_panel_sha256,
        timing_panel_manifest_sha256=str(timing["manifest_sha256"]),
    )
    if not confirmation_code_paths or any(not path.is_file() for path in confirmation_code_paths):
        raise ValueError("B1V3_ACCESS_CONFIRMATION_CODE_MISSING")
    confirmation_code_sha256 = canonical_sha256(
        {
            "files": [
                {"name": path.name, "sha256": sha256_file(path)} for path in confirmation_code_paths
            ]
        }
    )
    ledger = build_b1v3_access_ledger(
        preregistration,
        common_panel_sha256=common_panel_sha256,
        method_freeze_sha256=str(method_freeze["manifest_sha256"]),
        timing_panel_manifest_sha256=str(timing["manifest_sha256"]),
        quality_report_sha256=str(quality["manifest_sha256"]),
        confirmation_code_sha256=confirmation_code_sha256,
        uv_lock_sha256=sha256_file(uv_lock_path),
        prerequisites=prerequisites,
    )
    validate_confirmation_plan_schema(ledger, access_schema_path)
    _validate_self_hash(ledger, "B1V3_ACCESS_LEDGER_SELF_HASH_INVALID")
    _write_json_if_identical(output_path, ledger)
    return ledger


def _arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    contracts = ROOT / "specs" / "001-pit-options-rv30" / "contracts"
    panel_artifacts = ROOT / "artifacts" / "b1v3_confirmation_panel"
    parser.add_argument(
        "--preregistration",
        type=Path,
        default=ROOT / "artifacts/b1v3_confirmation_preregistration/preregistration.json",
    )
    parser.add_argument(
        "--preregistration-schema",
        type=Path,
        default=contracts / "b1v3-preregistration-v1.schema.json",
    )
    parser.add_argument(
        "--method-freeze",
        type=Path,
        default=ROOT / "artifacts/b1v3_confirmation_method_freeze/method_freeze.json",
    )
    parser.add_argument(
        "--method-freeze-schema",
        type=Path,
        default=contracts / "b1v3-method-freeze-v1.schema.json",
    )
    parser.add_argument(
        "--common-manifest",
        type=Path,
        default=panel_artifacts / "common_predictor_manifest.json",
    )
    parser.add_argument(
        "--common-schema",
        type=Path,
        default=contracts / "b1v3-confirmation-common-predictor-v1.schema.json",
    )
    parser.add_argument(
        "--common-panel",
        type=Path,
        default=Path("D:/MDS650/b1v3_confirmation/predictors/common_predictor_panel.parquet"),
    )
    parser.add_argument(
        "--timing-manifest",
        type=Path,
        default=panel_artifacts / "timing_panel_manifest.json",
    )
    parser.add_argument(
        "--timing-schema",
        type=Path,
        default=contracts / "b1v3-confirmation-timing-panels-v1.schema.json",
    )
    parser.add_argument(
        "--quality-report",
        type=Path,
        default=ROOT / "artifacts/b1v3_confirmation/pre_confirmation_quality_gate.json",
    )
    parser.add_argument(
        "--quality-schema",
        type=Path,
        default=contracts / "b1v3-pre-confirmation-quality-v1.schema.json",
    )
    parser.add_argument(
        "--access-schema",
        type=Path,
        default=contracts / "b1v3-access-ledger-v1.schema.json",
    )
    parser.add_argument(
        "--confirmation-code",
        type=Path,
        action="append",
        default=[
            ROOT / "src/mds650/b1v3_confirmation_evaluation.py",
            ROOT / "src/mds650/b1v3_confirmation_run.py",
            ROOT / "scripts/run_b1v3_confirmation_once.py",
        ],
    )
    parser.add_argument("--uv-lock", type=Path, default=ROOT / "uv.lock")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "artifacts/b1v3_confirmation/access_ledger_frozen.json",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Seal the ledger and emit only sanitized status and semantic hash."""
    args = _arguments(argv)
    ledger = seal_b1v3_access_ledger(
        preregistration_path=args.preregistration,
        preregistration_schema_path=args.preregistration_schema,
        method_freeze_path=args.method_freeze,
        method_freeze_schema_path=args.method_freeze_schema,
        common_manifest_path=args.common_manifest,
        common_manifest_schema_path=args.common_schema,
        common_panel_path=args.common_panel,
        timing_manifest_path=args.timing_manifest,
        timing_manifest_schema_path=args.timing_schema,
        quality_report_path=args.quality_report,
        quality_report_schema_path=args.quality_schema,
        access_schema_path=args.access_schema,
        confirmation_code_paths=args.confirmation_code,
        uv_lock_path=args.uv_lock,
        output_path=args.output,
    )
    print(
        json.dumps(
            {
                "status": ledger["status"],
                "safe_to_evaluate_b1v3": ledger["safe_to_evaluate_b1v3"],
                "manifest_sha256": ledger["manifest_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
