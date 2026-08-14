"""Seal the source-bound B1v3 preregistration before any outcome access."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mds650.b1v3_confirmation import (  # noqa: E402
    canonical_sha256,
    sha256_file,
    validate_confirmation_plan_schema,
)
from mds650.b1v3_evaluation import build_b1v3_preregistration  # noqa: E402

_FORBIDDEN = (
    b"c:\\users\\",
    b"c:/users/",
    b"d:\\mds650",
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


def _write_if_identical(path: Path, payload: bytes) -> None:
    if any(token in payload.lower() for token in _FORBIDDEN):
        raise ValueError("B1V3_PREREG_OUTPUT_HYGIENE_INVALID")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise ValueError(f"B1V3_PREREG_OUTPUT_CONFLICT:{path.name}")
        return
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".part", dir=path.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _render_markdown(preregistration: Mapping[str, Any]) -> bytes:
    training = preregistration["training_sessions"]
    confirmation = preregistration["confirmation_sessions"]
    assert isinstance(training, list)
    assert isinstance(confirmation, list)
    lines = [
        "# B1v3 preregistration",
        "",
        "This document freezes the independent B1v3 confirmation before any RV30, QLIKE, "
        "prediction, loss or result payload is opened.",
        "",
        f"- Preregistration SHA-256: `{preregistration['manifest_sha256']}`",
        f"- Common predictor panel SHA-256: `{preregistration['common_predictor_panel_sha256']}`",
        f"- Training sessions: {len(training)}",
        f"- Confirmation sessions: {len(confirmation)}",
        "- SAFE_TO_EVALUATE_B1V3: NO",
        "- Confirmation reads: 0",
        "- Registered signs retained: positive, null and negative",
        "",
        "## Frozen information sets",
        "",
        "- B0: 12 underlying/market controls.",
        "- B1v3a: B0 plus the three frozen ATM-variance features.",
        "- B2: B1v3a plus the exact nine frozen trade-derived activity features.",
        "",
        "Primary contrasts are `QLIKE(B0)-QLIKE(B1v3a)` and "
        "`QLIKE(B1v3a)-QLIKE(B2)`. Gamma GLM is confirmatory; fixed Gamma-objective "
        "LightGBM is robustness. QLIKE is primary, MAE/RMSE descriptive, uncertainty is "
        "10,000 paired whole-day bootstrap draws, and Holm covers exactly both global contrasts.",
        "",
        "## Exact development sessions (60)",
        "",
        "```text",
        *[str(value) for value in training],
        "```",
        "",
        "## Exact one-read confirmation sessions (30)",
        "",
        "```text",
        *[str(value) for value in confirmation],
        "```",
        "",
        "The separate access ledger may transition to YES only after the source-bound panel, "
        "tests, Ruff, Mypy, coverage, JSON Schema, leakage and disk gates all pass. This "
        "preregistration itself is immutable.",
        "",
    ]
    return "\n".join(lines).encode("utf-8")


def seal_b1v3_preregistration(
    *,
    plan_path: Path,
    common_manifest_path: Path,
    common_manifest_schema_path: Path,
    design_path: Path,
    evaluation_code_path: Path,
    uv_lock_path: Path,
    preregistration_schema_path: Path,
    output_path: Path,
    markdown_path: Path,
) -> dict[str, Any]:
    """Validate, bind and immutably write the B1v3 preregistration.

    Parameters
    ----------
    plan_path, common_manifest_path:
        Frozen target-blind 60/30 plan and common predictor manifest.
    common_manifest_schema_path, preregistration_schema_path:
        Draft 2020-12 input and output contracts.
    design_path, evaluation_code_path, uv_lock_path:
        Exact method, implementation and environment files to hash.
    output_path, markdown_path:
        Sanitized machine- and human-readable destinations.

    Returns
    -------
    dict[str, Any]
        The immutable self-hashed preregistration document.

    Raises
    ------
    ValueError
        If a binding, schema, hash, hygiene or idempotence gate fails.
    """
    plan = _read_mapping(plan_path, "B1V3_PREREG_PLAN_INVALID")
    common = _read_mapping(common_manifest_path, "B1V3_PREREG_COMMON_INVALID")
    validate_confirmation_plan_schema(common, common_manifest_schema_path)
    _validate_self_hash(common, "B1V3_PREREG_COMMON_HASH_INVALID")
    for source in (design_path, evaluation_code_path, uv_lock_path):
        if not source.is_file():
            raise ValueError(f"B1V3_PREREG_SOURCE_MISSING:{source.name}")
    preregistration = build_b1v3_preregistration(
        plan,
        common,
        common_manifest_file_sha256=sha256_file(common_manifest_path),
        design_sha256=sha256_file(design_path),
        evaluation_code_sha256=sha256_file(evaluation_code_path),
        uv_lock_sha256=sha256_file(uv_lock_path),
    )
    validate_confirmation_plan_schema(preregistration, preregistration_schema_path)
    _validate_self_hash(preregistration, "B1V3_PREREG_SELF_HASH_INVALID")
    json_payload = (
        json.dumps(preregistration, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    ).encode("utf-8")
    markdown_payload = _render_markdown(preregistration)
    _write_if_identical(output_path, json_payload)
    _write_if_identical(markdown_path, markdown_payload)
    return preregistration


def _arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    contracts = ROOT / "specs" / "001-pit-options-rv30" / "contracts"
    parser.add_argument(
        "--plan",
        type=Path,
        default=ROOT
        / "artifacts"
        / "b1v3_confirmation_plan"
        / "confirmation_plan_provider_passed.json",
    )
    parser.add_argument(
        "--common-manifest",
        type=Path,
        default=ROOT
        / "artifacts"
        / "b1v3_confirmation_panel"
        / "common_predictor_manifest.json",
    )
    parser.add_argument(
        "--common-schema",
        type=Path,
        default=contracts / "b1v3-confirmation-common-predictor-v1.schema.json",
    )
    parser.add_argument(
        "--design",
        type=Path,
        default=ROOT
        / "docs"
        / "superpowers"
        / "specs"
        / "2026-08-14-b1v3-target-blind-replication-design.md",
    )
    parser.add_argument(
        "--evaluation-code",
        type=Path,
        default=ROOT / "src" / "mds650" / "b1v3_evaluation.py",
    )
    parser.add_argument("--uv-lock", type=Path, default=ROOT / "uv.lock")
    parser.add_argument(
        "--preregistration-schema",
        type=Path,
        default=contracts / "b1v3-preregistration-v1.schema.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT
        / "artifacts"
        / "b1v3_confirmation_preregistration"
        / "preregistration.json",
    )
    parser.add_argument(
        "--markdown",
        type=Path,
        default=ROOT / "docs" / "b1v3_preregistration.md",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Seal the preregistration and print only sanitized identities."""
    args = _arguments(argv)
    document = seal_b1v3_preregistration(
        plan_path=args.plan,
        common_manifest_path=args.common_manifest,
        common_manifest_schema_path=args.common_schema,
        design_path=args.design,
        evaluation_code_path=args.evaluation_code,
        uv_lock_path=args.uv_lock,
        preregistration_schema_path=args.preregistration_schema,
        output_path=args.output,
        markdown_path=args.markdown,
    )
    print(
        json.dumps(
            {
                "status": document["status"],
                "safe_to_evaluate_b1v3": document["safe_to_evaluate_b1v3"],
                "manifest_sha256": document["manifest_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
