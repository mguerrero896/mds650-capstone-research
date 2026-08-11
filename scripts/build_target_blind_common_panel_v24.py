"""Build a v2.4 source-bound target-blind predictor panel without evaluation.

The command validates the approved B2 v2.2 availability manifest and the
closed PIT v2.1 reconciliation gate before it opens already-acquired predictor
sources.  It never opens outcomes, predictions, metrics, models, reports, or
OOS artefacts, and it cannot reconcile sealed existing results.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# Direct script invocation must bootstrap ``src`` before sibling imports. The
# E402 exemptions below are deliberately limited to that bootstrap block.
from build_target_blind_common_panel_v22 import (  # noqa: E402
    B1_ORIGINS,
    B1_SOURCE,
    B2_AVAILABILITY,
    B2_PRIMARY_ROOT,
    FMP_BARS,
    build_panel,
    sha256_file,
)

from mds650.target_blind_panel_v22 import KEY_COLUMNS  # noqa: E402
from mds650.target_blind_provenance_v23 import (  # noqa: E402
    validate_target_blind_provenance_v23,
)
from mds650.target_blind_sourcebound_v24 import (  # noqa: E402
    assert_preflight_hashes_unchanged_v24,
    assert_safe_target_blind_paths_v24,
    build_sourcebound_manifest_v24,
    validate_sourcebound_manifest_v24,
    validate_sourcebound_panel_v24,
    write_if_new_or_identical_v24,
)

DERIVED_ROOT = Path(r"D:\MDS650\phase6\derived\target_blind_v24_sourcebound_20260812")
ARTIFACT_ROOT = ROOT / "artifacts" / "target_blind_v24_sourcebound_20260812"
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
    / "target-blind-common-predictor-manifest-v24.schema.json"
)
_BUILDER_SOURCE_PATHS = (
    "pyproject.toml",
    "uv.lock",
    "scripts/build_target_blind_common_panel_v22.py",
    "scripts/build_target_blind_common_panel_v24.py",
    "src/mds650/phase6.py",
    "src/mds650/provider_timing_v21.py",
    "src/mds650/target_blind_panel_v22.py",
    "src/mds650/target_blind_provenance_v23.py",
    "src/mds650/target_blind_sourcebound_v24.py",
    "specs/001-pit-options-rv30/contracts/b2-availability-manifest-v22.schema.json",
    "specs/001-pit-options-rv30/contracts/pit-reconciliation-gate-v21.schema.json",
    "specs/001-pit-options-rv30/contracts/target-blind-common-predictor-manifest-v24.schema.json",
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse only local, registered source paths and fail-closed output paths."""
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


def source_commit_v24() -> str:
    """Return the latest commit affecting any guarded runtime source or schema."""
    completed = subprocess.run(
        ["git", "log", "-1", "--format=%H", "--", *_BUILDER_SOURCE_PATHS],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    source_commit = completed.stdout.strip()
    if len(source_commit) != 40:
        raise ValueError("TARGET_BLIND_V24_BUILDER_SOURCE_HISTORY_UNAVAILABLE")
    return source_commit


def require_committed_builder_source() -> None:
    """Reject a build whose hashed runtime files or schemas are uncommitted."""
    completed = subprocess.run(
        ["git", "status", "--porcelain", "--", *_BUILDER_SOURCE_PATHS],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    if completed.stdout.strip():
        raise ValueError("TARGET_BLIND_V24_BUILDER_SOURCE_UNCOMMITTED")


def main(argv: Sequence[str] | None = None) -> int:
    """Construct a new immutable v2.4 target-blind predictor panel.

    All contract and source-hash validation is complete before predictor
    Parquet files are read.  The resulting panel preserves every canonical
    origin; B2 exclusions use null feature values plus an eligibility flag and
    a reason code rather than zero filling.
    """
    args = parse_args(argv)
    _assert_safe_paths_and_output_roots(args)
    require_committed_builder_source()

    preflight_before = validate_target_blind_provenance_v23(
        availability_manifest_path=args.availability_manifest,
        availability_manifest_schema_path=args.availability_manifest_schema,
        availability_sidecar_path=args.availability_sidecar,
        massive_reselection_path=args.massive_reselection,
        origins_path=args.origins,
        reconciliation_gate_path=args.reconciliation_gate,
        reconciliation_gate_schema_path=args.reconciliation_gate_schema,
    )
    panel, common, base_summary, source_hashes = build_panel(
        origins_path=args.origins,
        b1_source_path=args.b1_source,
        fmp_bars_path=args.fmp_bars,
        b2_primary_root=args.b2_primary_root,
        availability_path=args.availability_sidecar,
        massive_sensitivity_path=args.massive_reselection,
    )
    _assert_build_hashes_match_preflight(source_hashes, preflight_before)
    origins = pl.read_parquet(args.origins, columns=list(KEY_COLUMNS))
    validate_sourcebound_panel_v24(origins=origins, panel=panel, common=common)

    preflight_after = validate_target_blind_provenance_v23(
        availability_manifest_path=args.availability_manifest,
        availability_manifest_schema_path=args.availability_manifest_schema,
        availability_sidecar_path=args.availability_sidecar,
        massive_reselection_path=args.massive_reselection,
        origins_path=args.origins,
        reconciliation_gate_path=args.reconciliation_gate,
        reconciliation_gate_schema_path=args.reconciliation_gate_schema,
    )
    assert_preflight_hashes_unchanged_v24(before=preflight_before, after=preflight_after)

    panel_path = args.output_root / "target_blind_common_predictors_v24.parquet"
    common_path = args.output_root / "target_blind_common_complete_v24.parquet"
    _write_parquet_if_new_or_identical(panel, panel_path)
    _write_parquet_if_new_or_identical(common, common_path)
    summary = _v24_summary(base_summary)
    manifest = build_sourcebound_manifest_v24(
        panel=panel,
        common=common,
        panel_path=panel_path,
        common_path=common_path,
        provenance_hashes=preflight_before,
        source_hashes=source_hashes,
        summary=summary,
        builder_hashes={
            "script_sha256": sha256_file(Path(__file__).resolve()),
            "panel_module_sha256": sha256_file(
                ROOT / "src" / "mds650" / "target_blind_sourcebound_v24.py"
            ),
            "base_panel_module_sha256": sha256_file(
                ROOT / "src" / "mds650" / "target_blind_panel_v22.py"
            ),
            "provenance_module_sha256": sha256_file(
                ROOT / "src" / "mds650" / "target_blind_provenance_v23.py"
            ),
        },
        source_commit=source_commit_v24(),
        panel_location=panel_path.as_posix(),
        common_location=common_path.as_posix(),
    )
    validate_sourcebound_manifest_v24(manifest, args.output_manifest_schema)
    _write_json_if_new_or_identical(
        args.artifact_root / "target_blind_common_predictor_manifest_v24.json", manifest
    )
    _write_json_if_new_or_identical(
        args.artifact_root / "target_blind_common_predictor_summary_v24.json", summary
    )
    print("TARGET_BLIND_COMMON_PREDICTOR_PANEL_V24=PASS")
    print("SAFE_TO_RECONCILE_EXISTING_RESULTS=NO")
    print("SAFE_TO_OPEN_OR_EVALUATE_OOS=NO")
    return 0


def _assert_safe_paths_and_output_roots(args: argparse.Namespace) -> None:
    """Reject result-like paths and prevent output from escaping registered roots."""
    assert_safe_target_blind_paths_v24(
        {
            "output_root": args.output_root,
            "artifact_root": args.artifact_root,
            "origins": args.origins,
            "b1_source": args.b1_source,
            "fmp_bars": args.fmp_bars,
            "b2_primary_root": args.b2_primary_root,
            "availability_sidecar": args.availability_sidecar,
            "massive_reselection": args.massive_reselection,
            "availability_manifest": args.availability_manifest,
            "reconciliation_gate": args.reconciliation_gate,
            "availability_manifest_schema": args.availability_manifest_schema,
            "reconciliation_gate_schema": args.reconciliation_gate_schema,
            "output_manifest_schema": args.output_manifest_schema,
        }
    )
    if not args.output_root.as_posix().startswith("D:/MDS650/"):
        raise ValueError("TARGET_BLIND_V24_OUTPUT_ROOT_INVALID")
    if not args.output_root.name.casefold().replace("-", "_").startswith("target_blind"):
        raise ValueError("TARGET_BLIND_V24_OUTPUT_ROOT_INVALID")
    artifacts_root = (ROOT / "artifacts").resolve()
    try:
        args.artifact_root.resolve().relative_to(artifacts_root)
    except ValueError as exc:
        raise ValueError("TARGET_BLIND_V24_ARTIFACT_ROOT_INVALID") from exc
    if not args.artifact_root.name.casefold().replace("-", "_").startswith("target_blind"):
        raise ValueError("TARGET_BLIND_V24_ARTIFACT_ROOT_INVALID")


def _assert_build_hashes_match_preflight(
    source_hashes: Mapping[str, str], preflight_hashes: Mapping[str, str]
) -> None:
    """Ensure builder-read origins, B2 sidecar, and Massive record did not drift."""
    post_build = dict(preflight_hashes)
    post_build["origins_sha256"] = source_hashes.get("origins_sha256", "")
    post_build["b2_availability_sidecar_sha256"] = source_hashes.get(
        "b2_availability_sidecar_sha256", ""
    )
    post_build["massive_reselection_recomputed_v21_sha256"] = source_hashes.get(
        "massive_reselection_sensitivity_v21_sha256", ""
    )
    assert_preflight_hashes_unchanged_v24(before=preflight_hashes, after=post_build)


def _write_parquet_if_new_or_identical(frame: pl.DataFrame, path: Path) -> None:
    """Persist a target-blind frame atomically and reject divergent replays."""
    write_if_new_or_identical_v24(
        path,
        lambda temporary: frame.write_parquet(temporary, compression="zstd", statistics=True),
    )


def _write_json_if_new_or_identical(path: Path, payload: Mapping[str, Any]) -> None:
    """Persist one deterministic JSON object without overwriting a conflict."""
    rendered = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"

    def write_json(temporary: Path) -> None:
        temporary.write_text(rendered, encoding="utf-8")

    write_if_new_or_identical_v24(path, write_json)


def _v24_summary(base_summary: Mapping[str, Any]) -> dict[str, Any]:
    """Retain target-blind coverage metadata while binding it to v2.4 controls."""
    summary = dict(base_summary)
    summary.update(
        {
            "schema_version": "target-blind-common-predictor-panel-v2.4",
            "status": "PASS_TARGET_BLIND_INPUTS_RECONCILIATION_REMAINS_BLOCKED",
            "scope": "offline_target_blind_predictor_construction_only",
            "no_target_or_metric_payload_read": True,
            "model_fit_performed": False,
            "safe_to_reconcile_existing_results": "NO",
            "SAFE_TO_OPEN_OR_EVALUATE_OOS": "NO",
        }
    )
    return summary


if __name__ == "__main__":
    raise SystemExit(main())
