"""Build one immutable target-free corrected-development predictor release.

The builder consumes only local, already-acquired predictor evidence. It never
accepts targets, metrics, models, forecasts, sealed legacy results or a
prospective-holdout path. A later command binds RV30 only after this release
passes independently.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from mds650.corrected_development_release import (
    assert_safe_corrected_development_paths,
    build_corrected_development_release,
    prepare_corrected_development_panel,
    validate_corrected_development_release,
)
from mds650.study_design import build_study_sessions, canonical_sha256
from mds650.target_blind_sourcebound_v24 import validate_sourcebound_manifest_v24

ROOT = Path(__file__).resolve().parents[1]
DERIVED_ROOT = Path(r"D:\MDS650\phase6\derived\corrected_development_v1")
ARTIFACT_ROOT = ROOT / "artifacts" / "corrected_development_v1"
PREDICTOR_MANIFEST = (
    ROOT
    / "artifacts"
    / "target_blind_v24_sourcebound_20260812"
    / "target_blind_common_predictor_manifest_v24.json"
)
PREDICTOR_SCHEMA = (
    ROOT
    / "specs"
    / "001-pit-options-rv30"
    / "contracts"
    / "target-blind-common-predictor-manifest-v24.schema.json"
)
PREDICTOR_PANEL = Path(
    r"D:\MDS650\phase6\derived\target_blind_v24_sourcebound_20260812"
    r"\target_blind_common_predictors_v24.parquet"
)
B2_AVAILABILITY_SIDECAR = Path(
    r"D:\MDS650\phase6\derived\provider_timing_v22\b2_row_availability_v22.parquet"
)
PIT_RECONCILIATION_GATE = (
    ROOT
    / "artifacts"
    / "provider_timing_v21"
    / "pit_reconciliation_gate_v21_20260812.json"
)
MASSIVE_RESELECTION = (
    ROOT
    / "artifacts"
    / "provider_timing_v21"
    / "massive_reselection_sensitivity_v21_recomputed_20260812.json"
)
DEVELOPMENT_SOURCE_MANIFEST = ROOT / "artifacts" / "phase5" / "development_source_manifest_80d.json"
RELEASE_SCHEMA = (
    ROOT
    / "specs"
    / "001-pit-options-rv30"
    / "contracts"
    / "corrected-development-release-v1.schema.json"
)
_FORBIDDEN_PATH_TOKENS = frozenset(
    {"holdout", "oos", "outcome", "prediction", "qlike", "metric", "model", "result", "legacy"}
)


@dataclass(frozen=True)
class _Preflight:
    """Validated target-free source identity required for the local build."""

    development_sessions: tuple[str, ...]
    holdout_sessions: tuple[str, ...]
    source_hashes: dict[str, str]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse local predictor-only source and output paths.

    Parameters
    ----------
    argv:
        Optional command-line token sequence for testing.

    Returns
    -------
    argparse.Namespace
        Parsed local paths and the optional preflight-only flag.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DERIVED_ROOT)
    parser.add_argument("--artifact-root", type=Path, default=ARTIFACT_ROOT)
    parser.add_argument("--predictor-manifest", type=Path, default=PREDICTOR_MANIFEST)
    parser.add_argument("--predictor-schema", type=Path, default=PREDICTOR_SCHEMA)
    parser.add_argument("--predictor-panel", type=Path, default=PREDICTOR_PANEL)
    parser.add_argument("--b2-availability-sidecar", type=Path, default=B2_AVAILABILITY_SIDECAR)
    parser.add_argument("--pit-reconciliation-gate", type=Path, default=PIT_RECONCILIATION_GATE)
    parser.add_argument("--massive-reselection", type=Path, default=MASSIVE_RESELECTION)
    parser.add_argument(
        "--development-source-manifest",
        type=Path,
        default=DEVELOPMENT_SOURCE_MANIFEST,
    )
    parser.add_argument("--release-schema", type=Path, default=RELEASE_SCHEMA)
    parser.add_argument("--check-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Preflight and optionally construct the corrected target-free release.

    The preflight completes before any Parquet reader is invoked. ``--check-only``
    performs only compact manifest, schema and byte-hash checks and writes no output.

    Parameters
    ----------
    argv:
        Optional command-line token sequence for testing.

    Returns
    -------
    int
        Zero after a passing preflight or idempotent local release build.

    Raises
    ------
    ValueError
        If any source binding, session identity, path or predictor-only gate fails.
    """
    args = parse_args(argv)
    _assert_safe_arguments(args)
    preflight = _preflight(args)
    if args.check_only:
        print("CORRECTED_DEVELOPMENT_RELEASE_PREFLIGHT=PASS")
        print("SAFE_TO_RECONCILE_EXISTING_RESULTS=NO")
        print("SAFE_TO_OPEN_OR_EVALUATE_OOS=NO")
        return 0

    source_panel = (
        pl.scan_parquet(args.predictor_panel)
        .filter(pl.col("session_date").is_in(preflight.development_sessions))
        .collect()
    )
    prepared = prepare_corrected_development_panel(
        panel=source_panel,
        development_sessions=preflight.development_sessions,
        holdout_sessions=preflight.holdout_sessions,
    )
    panel_path = args.output_root / "corrected_development_predictors_v1.parquet"
    common_path = args.output_root / "corrected_development_common_complete_v1.parquet"
    _write_parquet_if_new_or_identical(prepared.panel, panel_path)
    _write_parquet_if_new_or_identical(prepared.common, common_path)

    release = build_corrected_development_release(
        prepared=prepared,
        source_hashes=preflight.source_hashes,
        output_hashes={
            "panel_sha256": _sha256_file(panel_path),
            "common_complete_sha256": _sha256_file(common_path),
            "panel_row_count": prepared.panel.height,
            "common_complete_row_count": prepared.common.height,
        },
        source_locations={
            "predictor_panel": args.predictor_panel.as_posix(),
            "corrected_panel": panel_path.as_posix(),
            "corrected_common": common_path.as_posix(),
        },
        release_id="corrected-development-v1-20260812",
    )
    validate_corrected_development_release(release, args.release_schema)
    _write_json_if_new_or_identical(
        args.artifact_root / "target_blind_release_manifest.json", release
    )
    print("CORRECTED_DEVELOPMENT_RELEASE=TARGET_BLIND_READY")
    print("SAFE_TO_EVALUATE_CORRECTED_DEVELOPMENT=NO")
    print("SAFE_TO_RECONCILE_EXISTING_RESULTS=NO")
    print("SAFE_TO_OPEN_OR_EVALUATE_OOS=NO")
    return 0


def _preflight(args: argparse.Namespace) -> _Preflight:
    """Validate all compact input identities before any predictor Parquet read."""
    _require_files(
        {
            "predictor_manifest": args.predictor_manifest,
            "predictor_schema": args.predictor_schema,
            "predictor_panel": args.predictor_panel,
            "b2_availability_sidecar": args.b2_availability_sidecar,
            "pit_reconciliation_gate": args.pit_reconciliation_gate,
            "massive_reselection": args.massive_reselection,
            "development_source_manifest": args.development_source_manifest,
            "release_schema": args.release_schema,
        }
    )
    predictor_manifest = _read_json_object(args.predictor_manifest, "PREDICTOR_MANIFEST")
    validate_sourcebound_manifest_v24(predictor_manifest, args.predictor_schema)
    _assert_predictor_manifest_state(predictor_manifest)
    development, holdout = _validated_study_sessions(args.development_source_manifest)
    source_hashes = {
        "target_blind_predictor_manifest_sha256": _sha256_file(args.predictor_manifest),
        "b2_availability_sidecar_sha256": _sha256_file(args.b2_availability_sidecar),
        "pit_reconciliation_gate_sha256": _sha256_file(args.pit_reconciliation_gate),
        "massive_reselection_sha256": _sha256_file(args.massive_reselection),
        "development_source_manifest_sha256": _sha256_file(args.development_source_manifest),
    }
    _assert_predictor_source_bindings(
        predictor_manifest=predictor_manifest,
        source_hashes=source_hashes,
        predictor_panel_path=args.predictor_panel,
    )
    return _Preflight(
        development_sessions=tuple(development),
        holdout_sessions=tuple(holdout),
        source_hashes=source_hashes,
    )


def _assert_safe_arguments(args: argparse.Namespace) -> None:
    """Reject unsafe paths before compact-manifest or predictor I/O begins."""
    path_values = {
        "output_root": args.output_root,
        "artifact_root": args.artifact_root,
        "predictor_manifest": args.predictor_manifest,
        "predictor_schema": args.predictor_schema,
        "predictor_panel": args.predictor_panel,
        "b2_availability_sidecar": args.b2_availability_sidecar,
        "pit_reconciliation_gate": args.pit_reconciliation_gate,
        "massive_reselection": args.massive_reselection,
        "development_source_manifest": args.development_source_manifest,
        "release_schema": args.release_schema,
    }
    assert_safe_corrected_development_paths(
        {
            "output_root": args.output_root,
            "predictor_panel": args.predictor_panel,
            "b2_availability_sidecar": args.b2_availability_sidecar,
        }
    )
    for role, path in path_values.items():
        normalised = path.as_posix().casefold()
        components = normalised.split("/")
        if any(
            token in _FORBIDDEN_PATH_TOKENS
            for component in components
            if not component.startswith("target_blind")
            for token in re.split(r"[^a-z0-9]+", component)
            if token
        ):
            raise ValueError(f"CORRECTED_DEVELOPMENT_UNSAFE_PATH:{role}")
    try:
        args.artifact_root.resolve().relative_to((ROOT / "artifacts").resolve())
    except ValueError as exc:
        raise ValueError("CORRECTED_DEVELOPMENT_UNSAFE_PATH:artifact_root") from exc


def _require_files(paths: Mapping[str, Path]) -> None:
    """Require every local evidence file before source-byte hash validation."""
    for role, path in paths.items():
        if not path.is_file():
            raise FileNotFoundError(f"CORRECTED_DEVELOPMENT_SOURCE_MISSING:{role}")


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    """Read one compact UTF-8 JSON object without exposing values in errors."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"CORRECTED_DEVELOPMENT_{label}_INVALID_JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"CORRECTED_DEVELOPMENT_{label}_NOT_OBJECT")
    return payload


def _assert_predictor_manifest_state(manifest: Mapping[str, Any]) -> None:
    """Require the immutable v2.4 target-free state without interpreting outcomes."""
    required = {
        "schema_version": "target-blind-common-predictor-manifest-v2.4",
        "status": "PASS_TARGET_BLIND_INPUTS_RECONCILIATION_REMAINS_BLOCKED",
        "scope": "offline_target_blind_predictor_construction_only",
        "no_target_or_metric_payload_read": True,
        "model_fit_performed": False,
        "safe_to_reconcile_existing_results": "NO",
        "SAFE_TO_OPEN_OR_EVALUATE_OOS": "NO",
    }
    if any(manifest.get(key) != value for key, value in required.items()):
        raise ValueError("CORRECTED_DEVELOPMENT_PREDICTOR_MANIFEST_STATE_INVALID")


def _validated_study_sessions(source_manifest_path: Path) -> tuple[list[str], list[str]]:
    """Require exact approved 80/10 arrays from the compact source manifest."""
    document = _read_json_object(source_manifest_path, "DEVELOPMENT_SOURCE_MANIFEST")
    recorded_hash = document.get("manifest_sha256")
    unsigned = {key: value for key, value in document.items() if key != "manifest_sha256"}
    if not isinstance(recorded_hash, str) or canonical_sha256(unsigned) != recorded_hash:
        raise ValueError("CORRECTED_DEVELOPMENT_SOURCE_MANIFEST_SELF_HASH_MISMATCH")
    expected = build_study_sessions(
        "XNYS",
        development_end=date(2026, 7, 17),
        development_count=80,
        holdout_count=10,
    )
    development = document.get("development_sessions")
    if (
        document.get("status") != "PASS"
        or document.get("development_session_count") != 80
        or document.get("holdout_overlap") != []
        or document.get("holdout_reads") != 0
        or development != expected["development"]
    ):
        raise ValueError("CORRECTED_DEVELOPMENT_SOURCE_MANIFEST_IDENTITY_INVALID")
    return list(expected["development"]), list(expected["holdout"])


def _assert_predictor_source_bindings(
    *,
    predictor_manifest: Mapping[str, Any],
    source_hashes: Mapping[str, str],
    predictor_panel_path: Path,
) -> None:
    """Bind external source bytes to the promoted v2.4 manifest before panel I/O."""
    source = predictor_manifest.get("source_hashes")
    output = predictor_manifest.get("output")
    if not isinstance(source, Mapping) or not isinstance(output, Mapping):
        raise ValueError("CORRECTED_DEVELOPMENT_PREDICTOR_MANIFEST_BINDING_INVALID")
    expected = {
        "b2_availability_sidecar_sha256": source.get("b2_availability_sidecar_sha256"),
        "pit_reconciliation_gate_sha256": source.get("pit_reconciliation_gate_v21_sha256"),
        "massive_reselection_sha256": source.get("massive_reselection_recomputed_v21_sha256"),
    }
    if any(source_hashes[key] != value for key, value in expected.items()):
        raise ValueError("CORRECTED_DEVELOPMENT_SOURCE_HASH_MISMATCH")
    if output.get("panel_sha256") != _sha256_file(predictor_panel_path):
        raise ValueError("CORRECTED_DEVELOPMENT_PREDICTOR_PANEL_HASH_MISMATCH")


def _write_parquet_if_new_or_identical(frame: pl.DataFrame, path: Path) -> None:
    """Write deterministic local Parquet output or reject a divergent replay."""
    _write_if_new_or_identical(
        path,
        lambda temporary: frame.write_parquet(temporary, compression="zstd", statistics=True),
    )


def _write_json_if_new_or_identical(path: Path, payload: Mapping[str, Any]) -> None:
    """Write one canonical JSON manifest or reject a divergent replay."""
    rendered = json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"

    def write_json(temporary: Path) -> None:
        temporary.write_text(rendered, encoding="utf-8")

    _write_if_new_or_identical(path, write_json)


def _write_if_new_or_identical(path: Path, writer: Callable[[Path], None]) -> None:
    """Atomically retain byte-identical output and fail closed on an existing conflict."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.part")
    try:
        writer(temporary)
        if path.exists():
            if _sha256_file(temporary) != _sha256_file(path):
                raise FileExistsError("CORRECTED_DEVELOPMENT_OUTPUT_EXISTS_WITH_DIFFERENT_BYTES")
            return
        try:
            os.link(temporary, path)
        except FileExistsError:
            if _sha256_file(temporary) != _sha256_file(path):
                raise FileExistsError(
                    "CORRECTED_DEVELOPMENT_OUTPUT_EXISTS_WITH_DIFFERENT_BYTES"
                ) from None
    finally:
        temporary.unlink(missing_ok=True)


def _sha256_file(path: Path) -> str:
    """Return one streaming SHA-256 digest without printing file contents."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
