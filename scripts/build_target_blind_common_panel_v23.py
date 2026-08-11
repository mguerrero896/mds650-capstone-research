"""Build a provenance-bound v2.3 predictor panel without outcomes or models.

This local command validates the approved B2 sidecar, Massive reselection
record, and closed PIT gate before it reads predictor sources.  It cannot
reconcile sealed results or authorize OOS evaluation.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import polars as pl
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from build_target_blind_common_panel_v22 import (  # noqa: E402
    B1_ORIGINS,
    B1_SOURCE,
    B2_AVAILABILITY,
    B2_PRIMARY_ROOT,
    FMP_BARS,
    build_panel,
    sha256_file,
)

from mds650.target_blind_provenance_v23 import (  # noqa: E402
    validate_target_blind_provenance_v23,
)

DERIVED_ROOT = Path(r"D:\MDS650\phase6\derived\target_blind_v23_committed_20260812")
ARTIFACT_ROOT = ROOT / "artifacts" / "target_blind_v23_committed_20260812"
MASSIVE_RESELECTION = (
    ROOT
    / "artifacts"
    / "provider_timing_v21"
    / "massive_reselection_sensitivity_v21_recomputed_20260812.json"
)
AVAILABILITY_MANIFEST = (
    ROOT / "artifacts" / "provider_timing_v22" / "b2_availability_manifest_v22.json"
)
RECONCILIATION_GATE = (
    ROOT / "artifacts" / "provider_timing_v21" / "pit_reconciliation_gate_v21_20260812.json"
)
AVAILABILITY_MANIFEST_SCHEMA = (
    ROOT
    / "specs"
    / "001-pit-options-rv30"
    / "contracts"
    / "b2-availability-manifest-v22.schema.json"
)
RECONCILIATION_GATE_SCHEMA = (
    ROOT
    / "specs"
    / "001-pit-options-rv30"
    / "contracts"
    / "pit-reconciliation-gate-v21.schema.json"
)
OUTPUT_MANIFEST_SCHEMA = (
    ROOT
    / "specs"
    / "001-pit-options-rv30"
    / "contracts"
    / "target-blind-common-predictor-manifest-v23.schema.json"
)
_BUILDER_SOURCE_PATHS = (
    "pyproject.toml",
    "uv.lock",
    "scripts/build_target_blind_common_panel_v22.py",
    "src/mds650/target_blind_panel_v22.py",
    "src/mds650/target_blind_provenance_v23.py",
    "src/mds650/phase6.py",
    "src/mds650/provider_timing_v21.py",
    "scripts/build_target_blind_common_panel_v23.py",
    "specs/001-pit-options-rv30/contracts/target-blind-common-predictor-manifest-v23.schema.json",
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse only local, already-acquired input and output paths.

    Parameters
    ----------
    argv:
        Optional command-line tokens. ``None`` reads process arguments.

    Returns
    -------
    argparse.Namespace
        Parsed local paths. No provider endpoint or credential option exists.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DERIVED_ROOT)
    parser.add_argument("--artifact-root", type=Path, default=ARTIFACT_ROOT)
    parser.add_argument("--origins", type=Path, default=B1_ORIGINS)
    parser.add_argument("--b1-source", type=Path, default=B1_SOURCE)
    parser.add_argument("--fmp-bars", type=Path, default=FMP_BARS)
    parser.add_argument("--b2-primary-root", type=Path, default=B2_PRIMARY_ROOT)
    parser.add_argument("--availability-sidecar", type=Path, default=B2_AVAILABILITY)
    parser.add_argument("--massive-reselection", type=Path, default=MASSIVE_RESELECTION)
    parser.add_argument("--availability-manifest", type=Path, default=AVAILABILITY_MANIFEST)
    parser.add_argument("--reconciliation-gate", type=Path, default=RECONCILIATION_GATE)
    parser.add_argument(
        "--availability-manifest-schema", type=Path, default=AVAILABILITY_MANIFEST_SCHEMA
    )
    parser.add_argument(
        "--reconciliation-gate-schema", type=Path, default=RECONCILIATION_GATE_SCHEMA
    )
    parser.add_argument("--output-manifest-schema", type=Path, default=OUTPUT_MANIFEST_SCHEMA)
    return parser.parse_args(argv)


def write_if_new_or_identical(path: Path, writer: Callable[[Path], None]) -> None:
    """Create one immutable output or retain a byte-identical replay.

    Parameters
    ----------
    path:
        Final local output path.
    writer:
        Callback that writes a complete temporary file at the provided path.

    Raises
    ------
    FileExistsError
        If an output already exists with different bytes.
    OSError
        If the callback or an atomic hard-link promotion fails.

    Notes
    -----
    A hard link provides no-overwrite promotion on the local NTFS volume.  A
    concurrent, differing writer remains visible and fails closed.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.part")
    try:
        writer(temporary)
        if path.exists():
            if not _files_equal(temporary, path):
                raise FileExistsError("TARGET_BLIND_V23_OUTPUT_EXISTS_WITH_DIFFERENT_BYTES")
            return
        try:
            os.link(temporary, path)
        except FileExistsError:
            if not _files_equal(temporary, path):
                raise FileExistsError(
                    "TARGET_BLIND_V23_OUTPUT_EXISTS_WITH_DIFFERENT_BYTES"
                ) from None
    finally:
        temporary.unlink(missing_ok=True)


def _files_equal(left: Path, right: Path) -> bool:
    """Compare two local files exactly without materializing their contents."""
    if left.stat().st_size != right.stat().st_size:
        return False
    with left.open("rb") as left_handle, right.open("rb") as right_handle:
        while left_chunk := left_handle.read(1024 * 1024):
            if left_chunk != right_handle.read(1024 * 1024):
                return False
        return right_handle.read(1) == b""


def _write_parquet_if_new_or_identical(frame: pl.DataFrame, path: Path) -> None:
    """Persist a target-blind Parquet frame without overwriting a prior replay."""
    write_if_new_or_identical(
        path,
        lambda temporary: frame.write_parquet(temporary, compression="zstd", statistics=True),
    )


def _write_csv_if_new_or_identical(frame: pl.DataFrame, path: Path) -> None:
    """Persist a target-blind CSV summary without overwriting a prior replay."""

    def write_csv(temporary: Path) -> None:
        frame.write_csv(temporary)

    write_if_new_or_identical(path, write_csv)


def _write_json_if_new_or_identical(path: Path, payload: Mapping[str, Any]) -> None:
    """Persist stable JSON without overwriting a prior replay."""
    rendered = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"

    def write_json(temporary: Path) -> None:
        temporary.write_text(rendered, encoding="utf-8")

    write_if_new_or_identical(path, write_json)


def _validate_output_manifest(manifest: Mapping[str, Any], schema_path: Path) -> None:
    """Require a valid v2.3 output manifest before it reaches disk."""
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        errors = list(Draft202012Validator(schema).iter_errors(manifest))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("TARGET_BLIND_V23_OUTPUT_MANIFEST_SCHEMA_UNREADABLE") from exc
    if errors:
        raise ValueError("TARGET_BLIND_V23_OUTPUT_MANIFEST_SCHEMA_VIOLATION")


def _source_commit() -> str:
    """Return the local commit identity without contacting a remote."""
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def require_committed_builder_source() -> None:
    """Reject a run when its executable builder sources are not committed.

    Raises
    ------
    ValueError
        If any source file whose hash contributes to the v2.3 manifest is
        modified, deleted, or untracked. Unrelated user-owned worktree changes
        are deliberately outside this narrow check.
    """
    completed = subprocess.run(
        ["git", "status", "--porcelain", "--", *_BUILDER_SOURCE_PATHS],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    if completed.stdout.strip():
        raise ValueError("TARGET_BLIND_V23_BUILDER_SOURCE_UNCOMMITTED")


def main(argv: Sequence[str] | None = None) -> int:
    """Build the immutable target-blind v2.3 predictor matrix.

    The provenance preflight runs before any predictor Parquet is opened.  The
    command cannot read outcomes, predictions, metrics, models, or OOS files.
    """
    args = parse_args(argv)
    require_committed_builder_source()
    provenance_hashes = validate_target_blind_provenance_v23(
        availability_manifest_path=args.availability_manifest,
        availability_manifest_schema_path=args.availability_manifest_schema,
        availability_sidecar_path=args.availability_sidecar,
        massive_reselection_path=args.massive_reselection,
        origins_path=args.origins,
        reconciliation_gate_path=args.reconciliation_gate,
        reconciliation_gate_schema_path=args.reconciliation_gate_schema,
    )
    panel, common, summary, source_hashes = build_panel(
        origins_path=args.origins,
        b1_source_path=args.b1_source,
        fmp_bars_path=args.fmp_bars,
        b2_primary_root=args.b2_primary_root,
        availability_path=args.availability_sidecar,
        massive_sensitivity_path=args.massive_reselection,
    )
    _assert_post_build_bindings(source_hashes, provenance_hashes)
    panel_path = args.output_root / "target_blind_common_predictors_v23.parquet"
    common_path = args.output_root / "target_blind_common_complete_v23.parquet"
    _write_parquet_if_new_or_identical(panel, panel_path)
    _write_parquet_if_new_or_identical(common, common_path)
    coverage = _coverage_by_asset(panel)
    coverage_path = args.artifact_root / "target_blind_common_predictor_coverage_by_asset_v23.csv"
    _write_csv_if_new_or_identical(coverage, coverage_path)
    manifest = _build_manifest(
        panel=panel,
        common=common,
        panel_path=panel_path,
        common_path=common_path,
        provenance_hashes=provenance_hashes,
        source_hashes=source_hashes,
        summary=summary,
    )
    _validate_output_manifest(manifest, args.output_manifest_schema)
    _write_json_if_new_or_identical(
        args.artifact_root / "target_blind_common_predictor_manifest_v23.json", manifest
    )
    _write_json_if_new_or_identical(
        args.artifact_root / "target_blind_common_predictor_summary_v23.json", summary
    )
    print("TARGET_BLIND_COMMON_PREDICTOR_PANEL_V23=PASS")
    print("SAFE_TO_RECONCILE_EXISTING_RESULTS=NO")
    print("SAFE_TO_OPEN_OR_EVALUATE_OOS=NO")
    return 0


def _assert_post_build_bindings(
    source_hashes: Mapping[str, str], provenance_hashes: Mapping[str, str]
) -> None:
    """Ensure input files did not change after the provenance preflight."""
    expected_pairs = {
        "origins_sha256": "origins_sha256",
        "b2_availability_sidecar_sha256": "b2_availability_sidecar_sha256",
        "massive_reselection_sensitivity_v21_sha256": ("massive_reselection_recomputed_v21_sha256"),
    }
    for source_key, provenance_key in expected_pairs.items():
        if source_hashes.get(source_key) != provenance_hashes.get(provenance_key):
            raise ValueError("TARGET_BLIND_V23_INPUT_CHANGED_AFTER_PREFLIGHT")


def _coverage_by_asset(panel: pl.DataFrame) -> pl.DataFrame:
    """Return non-evaluative predictor-completeness coverage by asset."""
    return (
        panel.group_by("asset")
        .agg(
            pl.len().alias("origin_count"),
            pl.col("b0v2_predictor_complete").mean().alias("b0_completion_rate"),
            pl.col("b1v2a_predictor_complete").mean().alias("b1a_completion_rate"),
            pl.col("b1v2b_predictor_complete").mean().alias("b1b_completion_rate"),
            pl.col("b1v2c_predictor_complete").mean().alias("b1c_completion_rate"),
            pl.col("b2v2_predictor_complete").mean().alias("b2_completion_rate"),
            pl.col("common_predictor_complete").mean().alias("common_completion_rate"),
        )
        .sort("asset")
    )


def _build_manifest(
    *,
    panel: pl.DataFrame,
    common: pl.DataFrame,
    panel_path: Path,
    common_path: Path,
    provenance_hashes: Mapping[str, str],
    source_hashes: Mapping[str, str],
    summary: Mapping[str, Any],
) -> dict[str, Any]:
    """Create a schema-bound, non-evaluative v2.3 output manifest."""
    return {
        "schema_version": "target-blind-common-predictor-manifest-v2.3",
        "status": "PASS_TARGET_BLIND_INPUTS_RECONCILIATION_REMAINS_BLOCKED",
        "scope": "offline_target_blind_predictor_construction_only",
        "no_target_or_metric_payload_read": True,
        "model_fit_performed": False,
        "safe_to_reconcile_existing_results": "NO",
        "SAFE_TO_OPEN_OR_EVALUATE_OOS": "NO",
        "input_provenance": {
            "availability_sidecar_status": "PASS_WITH_EXCLUSIONS",
            "reconciliation_gate_status": "CONDITIONAL_NOT_CLOSED",
            "edge_conclusion": "NOT_EVALUATED_TARGET_BLIND",
            "primary_excluded_row_count": 451,
        },
        "timing_rules": {
            "fmp_primary_delay_minutes": 1,
            "fmp_sensitivity_delay_minutes": 2,
            "b1q_primary_state": "SIP_ASOF_ORIGIN_MAX_AGE_60S",
            "massive_reselection_sensitivity_cutoff_seconds": [60, 300],
            "b2_primary_variant": "primary_5m_60s",
            "b2_created_at_rule": "OPERATIONAL_AVAILABILITY_PROXY_ORIGIN_MINUS_60_SECONDS",
        },
        "source_hashes": {
            "origins_sha256": provenance_hashes["origins_sha256"],
            "fmp_bars_sha256": source_hashes["fmp_bars_sha256"],
            "b1q_source_sha256": source_hashes["b1q_source_sha256"],
            "b2_primary_inputs_sha256": source_hashes["b2_primary_inputs_sha256"],
            "b2_availability_sidecar_sha256": provenance_hashes["b2_availability_sidecar_sha256"],
            "massive_reselection_recomputed_v21_sha256": provenance_hashes[
                "massive_reselection_recomputed_v21_sha256"
            ],
            "b2_availability_manifest_v22_sha256": provenance_hashes[
                "b2_availability_manifest_v22_sha256"
            ],
            "pit_reconciliation_gate_v21_sha256": provenance_hashes[
                "pit_reconciliation_gate_v21_sha256"
            ],
        },
        "builder_hashes": {
            "script_sha256": sha256_file(Path(__file__).resolve()),
            "panel_module_sha256": sha256_file(
                ROOT / "src" / "mds650" / "target_blind_panel_v22.py"
            ),
            "provenance_module_sha256": sha256_file(
                ROOT / "src" / "mds650" / "target_blind_provenance_v23.py"
            ),
        },
        "output": {
            "panel_sha256": sha256_file(panel_path),
            "common_complete_sha256": sha256_file(common_path),
            "row_count": panel.height,
            "common_complete_row_count": common.height,
        },
        "summary": dict(summary),
        "source_commit": _source_commit(),
        "output_locations": {
            "panel": panel_path.as_posix(),
            "common_complete": common_path.as_posix(),
        },
    }


if __name__ == "__main__":
    raise SystemExit(main())
