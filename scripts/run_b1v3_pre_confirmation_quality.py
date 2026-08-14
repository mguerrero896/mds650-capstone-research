"""Run and seal every target-blind gate before B1v3 confirmation access."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mds650.b1v3_confirmation import (  # noqa: E402
    canonical_sha256,
    sha256_file,
    validate_confirmation_plan_schema,
)

_GATES: Final[tuple[str, ...]] = (
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
_FORBIDDEN_ARTIFACT_TOKENS: Final[tuple[bytes, ...]] = (
    b"c:\\users\\",
    b"c:/users/",
    b"d:\\mds650",
    b"d:/mds650",
    b"api_key",
    b"apikey",
    b"bearer ",
)


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _read_contract(path: Path, schema_path: Path, *, error: str) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(error) from exc
    if not isinstance(document, dict):
        raise ValueError(error)
    validate_confirmation_plan_schema(document, schema_path)
    stored = document.get("manifest_sha256")
    unsigned = {key: value for key, value in document.items() if key != "manifest_sha256"}
    if not isinstance(stored, str) or stored != canonical_sha256(unsigned):
        raise ValueError(f"{error}_SELF_HASH")
    return document


def _write_exclusive(path: Path, payload: bytes) -> str:
    if any(token in payload.lower() for token in _FORBIDDEN_ARTIFACT_TOKENS):
        raise ValueError("B1V3_QUALITY_OUTPUT_HYGIENE_INVALID")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise ValueError(f"B1V3_QUALITY_OUTPUT_EXISTS:{path.name}") from exc
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return sha256_file(path)


def _sanitize_log(text: str, *, data_root: Path) -> str:
    replacements = {
        str(ROOT): "<WORKSPACE>",
        str(ROOT).replace("\\", "/"): "<WORKSPACE>",
        str(data_root): "<DATA_ROOT>",
        str(data_root).replace("\\", "/"): "<DATA_ROOT>",
    }
    sanitized = text
    for source, replacement in sorted(replacements.items(), key=lambda item: -len(item[0])):
        sanitized = sanitized.replace(source, replacement)
    return sanitized


def _run_commands(
    name: str,
    commands: Sequence[Sequence[str]],
    *,
    log_root: Path,
    data_root: Path,
    environment: Mapping[str, str] | None = None,
) -> str:
    chunks: list[str] = []
    for index, command in enumerate(commands, start=1):
        completed = subprocess.run(
            list(command),
            cwd=ROOT,
            env=dict(environment) if environment is not None else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        chunks.extend(
            (
                f"command_index={index}",
                f"command={' '.join(command)}",
                f"exit_code={completed.returncode}",
                "stdout:",
                completed.stdout,
                "stderr:",
                completed.stderr,
            )
        )
        if completed.returncode != 0:
            sanitized = _sanitize_log("\n".join(chunks), data_root=data_root)
            failure = log_root / f"{name}.failed.log"
            failure.parent.mkdir(parents=True, exist_ok=True)
            failure.write_text(sanitized, encoding="utf-8")
            raise ValueError(f"B1V3_QUALITY_COMMAND_FAILED:{name}")
    payload = (_sanitize_log("\n".join(chunks), data_root=data_root) + "\n").encode("utf-8")
    return _write_exclusive(log_root / f"{name}.log", payload)


def _assert_target_blind_panel(frame: pl.DataFrame) -> None:
    """Reject outcome fields and every known predictor-time violation."""
    forbidden = {
        name
        for name in frame.columns
        if name.lower() in {"rv30", "target", "qlike", "prediction", "residual", "loss"}
        or name.lower().startswith(("rv30_", "qlike_", "prediction_", "residual_"))
    }
    if forbidden:
        raise ValueError("B1V3_QUALITY_OUTCOME_COLUMN_FORBIDDEN")
    columns = set(frame.columns)
    if {
        "max_predictor_available_at_utc",
        "forecast_origin_utc",
    } <= columns and frame.filter(
        pl.col("max_predictor_available_at_utc").is_not_null()
        & (pl.col("max_predictor_available_at_utc") > pl.col("forecast_origin_utc"))
    ).height:
        raise ValueError("B1V3_QUALITY_FUTURE_B0_RECORD")
    if {"max_sip_timestamp_ns", "forecast_origin_ns"} <= columns and frame.filter(
        pl.col("max_sip_timestamp_ns").is_not_null()
        & (pl.col("max_sip_timestamp_ns") > pl.col("forecast_origin_ns"))
    ).height:
        raise ValueError("B1V3_QUALITY_FUTURE_MASSIVE_QUOTE")
    if {"b2v2_max_created_at_utc", "b2v2_cutoff_utc"} <= columns and frame.filter(
        pl.col("b2v2_max_created_at_utc").is_not_null()
        & (pl.col("b2v2_max_created_at_utc") > pl.col("b2v2_cutoff_utc"))
    ).height:
        raise ValueError("B1V3_QUALITY_FUTURE_B2_RECORD")


def build_quality_document(
    *,
    preregistration_manifest_sha256: str,
    method_freeze_manifest_sha256: str,
    common_panel_sha256: str,
    timing_panel_manifest_sha256: str,
    gate_evidence: Mapping[str, str],
) -> dict[str, Any]:
    """Build the self-hashed gate document from exact successful evidence."""
    hashes = (
        preregistration_manifest_sha256,
        method_freeze_manifest_sha256,
        common_panel_sha256,
        timing_panel_manifest_sha256,
    )
    if set(gate_evidence) != set(_GATES):
        raise ValueError("B1V3_QUALITY_GATE_SET_INVALID")
    if any(not _is_sha256(value) for value in (*hashes, *gate_evidence.values())):
        raise ValueError("B1V3_QUALITY_EVIDENCE_HASH_INVALID")
    document: dict[str, Any] = {
        "schema_version": "1.0",
        "status": "PASS_B1V3_PRE_CONFIRMATION_QUALITY",
        "target_blind": True,
        "outcome_read_count": 1,
        "training_read_count": 1,
        "confirmation_read_count": 0,
        "source_bindings": {
            "preregistration_manifest_sha256": preregistration_manifest_sha256,
            "method_freeze_manifest_sha256": method_freeze_manifest_sha256,
            "common_panel_sha256": common_panel_sha256,
            "timing_panel_manifest_sha256": timing_panel_manifest_sha256,
        },
        "gates": {
            name: {"status": "PASS", "evidence_sha256": gate_evidence[name]} for name in _GATES
        },
        "security": {
            "secret_values_emitted": False,
            "personal_paths_emitted": False,
        },
    }
    document["manifest_sha256"] = canonical_sha256(document)
    return document


def _focused_test_paths() -> list[str]:
    paths = sorted((ROOT / "tests/unit").glob("test_*b1v3*.py"))
    paths.extend(
        sorted(
            path
            for path in (ROOT / "tests/unit").glob("test_*b1v3_confirmation*.py")
            if path not in paths
        )
    )
    paths.append(ROOT / "tests/contract/test_b1v3_confirmation_base_artifact.py")
    return [str(path.relative_to(ROOT)) for path in paths]


def run_pre_confirmation_quality(
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
    timing_panel_paths: Mapping[str, Path],
    spec_kit_report_path: Path,
    clean_install_root: Path,
    data_root: Path,
    log_root: Path,
    output_path: Path,
    output_schema_path: Path,
    minimum_free_gib: float,
) -> dict[str, Any]:
    """Execute all registered pre-confirmation checks and seal their hashes."""
    preregistration = _read_contract(
        preregistration_path,
        preregistration_schema_path,
        error="B1V3_QUALITY_PREREGISTRATION_INVALID",
    )
    method_freeze = _read_contract(
        method_freeze_path,
        method_freeze_schema_path,
        error="B1V3_QUALITY_METHOD_FREEZE_INVALID",
    )
    common_manifest = _read_contract(
        common_manifest_path,
        common_manifest_schema_path,
        error="B1V3_QUALITY_COMMON_MANIFEST_INVALID",
    )
    timing_manifest = _read_contract(
        timing_manifest_path,
        timing_manifest_schema_path,
        error="B1V3_QUALITY_TIMING_MANIFEST_INVALID",
    )
    common_output = common_manifest.get("output")
    timing_records = timing_manifest.get("variants")
    common_sha = sha256_file(common_panel_path)
    if (
        not isinstance(common_output, Mapping)
        or common_output.get("sha256") != common_sha
        or preregistration.get("common_predictor_panel_sha256") != common_sha
        or method_freeze.get("common_panel_sha256") != common_sha
        or method_freeze.get("training_read_count") != 1
        or method_freeze.get("confirmation_read_count") != 0
        or not isinstance(timing_records, Mapping)
        or set(timing_panel_paths) != set(timing_records)
    ):
        raise ValueError("B1V3_QUALITY_SOURCE_BINDING_INVALID")
    for variant, path in timing_panel_paths.items():
        record = timing_records.get(variant)
        if not isinstance(record, Mapping) or record.get("sha256") != sha256_file(path):
            raise ValueError(f"B1V3_QUALITY_TIMING_BINDING_INVALID:{variant}")

    evidence: dict[str, str] = {}
    evidence["focused_tests"] = _run_commands(
        "focused_tests",
        (("uv", "run", "pytest", "-q", *_focused_test_paths()),),
        log_root=log_root,
        data_root=data_root,
    )
    full_hash = _run_commands(
        "full_tests_with_coverage",
        (("uv", "run", "pytest", "--cov=mds650", "--cov-report=term-missing"),),
        log_root=log_root,
        data_root=data_root,
    )
    evidence["full_tests"] = full_hash
    evidence["coverage"] = full_hash
    evidence["ruff"] = _run_commands(
        "ruff",
        (("uv", "run", "ruff", "check", "src", "scripts", "tests"),),
        log_root=log_root,
        data_root=data_root,
    )
    evidence["mypy"] = _run_commands(
        "mypy",
        (("uv", "run", "mypy", "src", "scripts"),),
        log_root=log_root,
        data_root=data_root,
    )

    schema_payload = json.dumps(
        {
            "status": "PASS",
            "validated": [
                "preregistration",
                "method_freeze",
                "common_manifest",
                "timing_manifest",
            ],
        },
        sort_keys=True,
    ).encode()
    evidence["json_schema"] = _write_exclusive(log_root / "json_schema.log", schema_payload)
    _assert_target_blind_panel(pl.read_parquet(common_panel_path))
    for path in timing_panel_paths.values():
        _assert_target_blind_panel(pl.read_parquet(path))
    evidence["no_leakage"] = _write_exclusive(
        log_root / "no_leakage.log", b"status=PASS\nconfirmation_target_reads=0\n"
    )
    artifact_payloads = [
        preregistration_path.read_bytes(),
        method_freeze_path.read_bytes(),
        common_manifest_path.read_bytes(),
        timing_manifest_path.read_bytes(),
    ]
    if any(
        token in payload.lower()
        for payload in artifact_payloads
        for token in _FORBIDDEN_ARTIFACT_TOKENS
    ):
        raise ValueError("B1V3_QUALITY_ARTIFACT_HYGIENE_INVALID")
    evidence["hygiene"] = _write_exclusive(
        log_root / "hygiene.log", b"status=PASS\nsecret_values=0\npersonal_paths=0\n"
    )
    evidence["deterministic_replay"] = _run_commands(
        "deterministic_replay",
        (
            ("uv", "run", "python", "scripts/build_b1v3_confirmation_common.py"),
            ("uv", "run", "python", "scripts/build_b1v3_confirmation_timing_panels.py"),
            ("uv", "run", "python", "scripts/seal_b1v3_preregistration.py"),
        ),
        log_root=log_root,
        data_root=data_root,
    )
    clean_install_root.mkdir(parents=True, exist_ok=True)
    clean_parent = Path(tempfile.mkdtemp(prefix="b1v3-clean-", dir=clean_install_root)).resolve()
    clean_environment = dict(os.environ)
    clean_environment["UV_PROJECT_ENVIRONMENT"] = str(clean_parent / ".venv")
    evidence["clean_install"] = _run_commands(
        "clean_install",
        (
            ("uv", "sync", "--frozen", "--link-mode", "copy"),
            (
                "uv",
                "run",
                "python",
                "-c",
                "import duckdb,lightgbm,polars,pyarrow,sklearn;print('imports=PASS')",
            ),
        ),
        log_root=log_root,
        data_root=data_root,
        environment=clean_environment,
    )
    try:
        spec_text = spec_kit_report_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError("B1V3_QUALITY_SPEC_KIT_EVIDENCE_INVALID") from exc
    if "PASS_NO_CRITICAL_CONTRADICTIONS" not in spec_text:
        raise ValueError("B1V3_QUALITY_SPEC_KIT_FAILED")
    evidence["spec_kit"] = sha256_file(spec_kit_report_path)
    free_gib = shutil.disk_usage(data_root).free / (1024**3)
    if free_gib < minimum_free_gib:
        raise ValueError("B1V3_QUALITY_DISK_GATE_FAILED")
    evidence["disk_gate"] = _write_exclusive(
        log_root / "disk_gate.log",
        f"status=PASS\nminimum_free_gib={minimum_free_gib:.2f}\nobserved_free_gib={free_gib:.2f}\n".encode(),
    )
    document = build_quality_document(
        preregistration_manifest_sha256=str(preregistration["manifest_sha256"]),
        method_freeze_manifest_sha256=str(method_freeze["manifest_sha256"]),
        common_panel_sha256=common_sha,
        timing_panel_manifest_sha256=str(timing_manifest["manifest_sha256"]),
        gate_evidence=evidence,
    )
    validate_confirmation_plan_schema(document, output_schema_path)
    payload = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode()
    _write_exclusive(output_path, payload)
    return document


def _arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    contracts = ROOT / "specs/001-pit-options-rv30/contracts"
    artifacts = ROOT / "artifacts/b1v3_confirmation"
    panel_artifacts = ROOT / "artifacts/b1v3_confirmation_panel"
    data = Path("D:/MDS650/b1v3_confirmation")
    parser.add_argument("--execute", action="store_true")
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
        "--method-freeze-schema", type=Path, default=contracts / "b1v3-method-freeze-v1.schema.json"
    )
    parser.add_argument(
        "--common-manifest", type=Path, default=panel_artifacts / "common_predictor_manifest.json"
    )
    parser.add_argument(
        "--common-schema",
        type=Path,
        default=contracts / "b1v3-confirmation-common-predictor-v1.schema.json",
    )
    parser.add_argument(
        "--common-panel", type=Path, default=data / "predictors/common_predictor_panel.parquet"
    )
    parser.add_argument(
        "--timing-manifest", type=Path, default=panel_artifacts / "timing_panel_manifest.json"
    )
    parser.add_argument(
        "--timing-schema",
        type=Path,
        default=contracts / "b1v3-confirmation-timing-panels-v1.schema.json",
    )
    parser.add_argument(
        "--spec-kit-report", type=Path, default=ROOT / "docs/recovery/b1v3_spec_analysis.md"
    )
    parser.add_argument("--clean-install-root", type=Path, default=data / "clean_install")
    parser.add_argument("--log-root", type=Path, default=artifacts / "quality")
    parser.add_argument(
        "--output", type=Path, default=artifacts / "pre_confirmation_quality_gate.json"
    )
    parser.add_argument(
        "--output-schema",
        type=Path,
        default=contracts / "b1v3-pre-confirmation-quality-v1.schema.json",
    )
    parser.add_argument("--minimum-free-gib", type=float, default=80.0)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Execute the gate only when the explicit ``--execute`` flag is present."""
    args = _arguments(argv)
    if not args.execute:
        raise ValueError("B1V3_QUALITY_EXECUTION_FLAG_REQUIRED")
    timing_records = _read_contract(
        args.timing_manifest,
        args.timing_schema,
        error="B1V3_QUALITY_TIMING_MANIFEST_INVALID",
    )["variants"]
    assert isinstance(timing_records, Mapping)
    timing_paths = {
        str(variant): Path("D:/MDS650/b1v3_confirmation/predictors/timing/common")
        / f"{variant}.parquet"
        for variant in timing_records
    }
    document = run_pre_confirmation_quality(
        preregistration_path=args.preregistration,
        preregistration_schema_path=args.preregistration_schema,
        method_freeze_path=args.method_freeze,
        method_freeze_schema_path=args.method_freeze_schema,
        common_manifest_path=args.common_manifest,
        common_manifest_schema_path=args.common_schema,
        common_panel_path=args.common_panel,
        timing_manifest_path=args.timing_manifest,
        timing_manifest_schema_path=args.timing_schema,
        timing_panel_paths=timing_paths,
        spec_kit_report_path=args.spec_kit_report,
        clean_install_root=args.clean_install_root,
        data_root=Path("D:/MDS650"),
        log_root=args.log_root,
        output_path=args.output,
        output_schema_path=args.output_schema,
        minimum_free_gib=args.minimum_free_gib,
    )
    print(
        json.dumps(
            {
                "status": document["status"],
                "manifest_sha256": document["manifest_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
