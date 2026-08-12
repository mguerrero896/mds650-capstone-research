"""Build a v2.2-masked common B0/B1Q/B2 predictor panel without outcomes.

This is an offline transformation over already acquired D: sources.  It makes
no provider request, reads no RV30, QLIKE, forecast, model, or holdout-result
payload, and does not authorise reconciliation of results sealed before the
B2 availability correction.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mds650.phase6 import build_b2v2_from_activity  # noqa: E402
from mds650.target_blind_panel_v22 import (  # noqa: E402
    B2_PRIMARY_VARIANT,
    adapt_b1q_source_to_v22,
    apply_b2_availability_mask_v22,
    build_target_blind_b0_v22,
    build_target_blind_common_predictor_panel_v22,
    summarize_target_blind_common_predictor_panel_v22,
)

DATA_ROOT = Path(r"D:\MDS650\phase6\data")
DERIVED_ROOT = Path(r"D:\MDS650\phase6\derived\target_blind_v22")
ARTIFACT_ROOT = ROOT / "artifacts" / "target_blind_v22"
B1_ORIGINS = DATA_ROOT / "b1q" / "phase6_b1_origins.parquet"
B1_SOURCE = DATA_ROOT / "b1q" / "b1_origin_matrix_20d.parquet"
FMP_BARS = DATA_ROOT / "fmp" / "underlying_1min_180d.parquet"
B2_PRIMARY_ROOT = DATA_ROOT / "b2" / "raw_activity_by_session" / B2_PRIMARY_VARIANT
B2_AVAILABILITY = Path(
    r"D:\MDS650\phase6\derived\provider_timing_v22\b2_row_availability_v22.parquet"
)
MASSIVE_SENSITIVITY = (
    ROOT / "artifacts" / "provider_timing_v21" / "massive_reselection_sensitivity_v21.json"
)


def sha256_file(path: Path) -> str:
    """Return a streaming SHA-256 digest for one local input or output file.

    Parameters
    ----------
    path:
        Existing local file.

    Returns
    -------
    str
        Lowercase 64-character SHA-256 digest.

    Raises
    ------
    FileNotFoundError
        If ``path`` does not exist as a file.
    """
    if not path.is_file():
        raise FileNotFoundError(f"TARGET_BLIND_V22_FILE_MISSING:{path.name}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def combined_input_digest(paths: Sequence[Path]) -> str:
    """Hash ordered date-partition identities and contents without reading data values.

    Parameters
    ----------
    paths:
        Ordered local B2 partition paths.

    Returns
    -------
    str
        Digest binding both file names and their SHA-256 digests.

    Raises
    ------
    ValueError
        If no input partitions are supplied or date names repeat.
    """
    if not paths:
        raise ValueError("TARGET_BLIND_V22_B2_PRIMARY_PARTITIONS_MISSING")
    names = [path.name for path in paths]
    if len(set(names)) != len(names):
        raise ValueError("TARGET_BLIND_V22_B2_PRIMARY_PARTITION_DUPLICATE")
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda candidate: candidate.name):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_file(path).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def build_panel(
    *,
    origins_path: Path,
    b1_source_path: Path,
    fmp_bars_path: Path,
    b2_primary_root: Path,
    availability_path: Path,
    massive_sensitivity_path: Path,
) -> tuple[pl.DataFrame, pl.DataFrame, dict[str, Any], dict[str, str]]:
    """Construct a target-free common predictor panel from canonical sources.

    Parameters
    ----------
    origins_path:
        Target-free canonical origin grid.
    b1_source_path:
        Target-free B1Q source-state table.
    fmp_bars_path:
        One-minute underlying and market-control source bars.
    b2_primary_root:
        Directory containing one primary B2 activity partition per session.
    availability_path:
        v2.2 B2 availability sidecar.
    massive_sensitivity_path:
        Target-free v2.1 Massive re-selection evidence required by B1Q.

    Returns
    -------
    tuple
        Full origin-preserving panel, complete common subset, non-evaluative
        summary, and source hashes.

    Raises
    ------
    FileNotFoundError
        If an expected already-acquired source is absent.
    ValueError
        If source schemas, keys, PIT rules, or target-blind constraints fail.
    """
    required_files = (
        origins_path,
        b1_source_path,
        fmp_bars_path,
        availability_path,
        massive_sensitivity_path,
    )
    for path in required_files:
        if not path.is_file():
            raise FileNotFoundError(f"TARGET_BLIND_V22_FILE_MISSING:{path.name}")
    if not b2_primary_root.is_dir():
        raise FileNotFoundError("TARGET_BLIND_V22_B2_PRIMARY_ROOT_MISSING")
    b2_paths = sorted(b2_primary_root.glob("date=*.parquet"))
    if not b2_paths:
        raise FileNotFoundError("TARGET_BLIND_V22_B2_PRIMARY_PARTITIONS_MISSING")

    origins = pl.read_parquet(origins_path)
    b1_source = pl.read_parquet(b1_source_path)
    bars = pl.read_parquet(fmp_bars_path)
    activity = pl.scan_parquet([str(path) for path in b2_paths]).collect(engine="streaming")
    availability = pl.read_parquet(availability_path)
    _validate_massive_sensitivity(massive_sensitivity_path)

    b0 = build_target_blind_b0_v22(bars, origins, delay_minutes=1)
    b1 = adapt_b1q_source_to_v22(origins, b1_source)
    b2_unmasked = build_b2v2_from_activity(activity, origins)
    b2 = apply_b2_availability_mask_v22(
        b2_unmasked,
        availability,
        canonical_variant=B2_PRIMARY_VARIANT,
    )
    panel, common = build_target_blind_common_predictor_panel_v22(origins, b0, b1, b2)
    summary = summarize_target_blind_common_predictor_panel_v22(panel)
    hashes = {
        "origins_sha256": sha256_file(origins_path),
        "fmp_bars_sha256": sha256_file(fmp_bars_path),
        "b1q_source_sha256": sha256_file(b1_source_path),
        "b2_primary_inputs_sha256": combined_input_digest(b2_paths),
        "b2_availability_sidecar_sha256": sha256_file(availability_path),
        "massive_reselection_sensitivity_v21_sha256": sha256_file(massive_sensitivity_path),
    }
    return panel, common, summary, hashes


def _validate_massive_sensitivity(path: Path) -> None:
    """Require the target-free Massive re-selection evidence used by B1Q.

    Parameters
    ----------
    path:
        Sanitized v2.1 Massive sensitivity JSON.

    Raises
    ------
    ValueError
        If the record does not retain its PASS status and explicit shifted
        as-of selection contract.
    """
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("TARGET_BLIND_V22_MASSIVE_SENSITIVITY_UNREADABLE") from error
    if not isinstance(record, dict):
        raise ValueError("TARGET_BLIND_V22_MASSIVE_SENSITIVITY_SCHEMA_INVALID")
    required = {
        "status": "PASS",
        "selection_rule": (
            "last_quote_by_sip_timestamp_then_sequence_at_or_before_origin_minus_delay"
        ),
        "no_targets_or_predictive_metrics_read": True,
    }
    if any(record.get(key) != value for key, value in required.items()):
        raise ValueError("TARGET_BLIND_V22_MASSIVE_SENSITIVITY_NOT_ACCEPTED")


def _write_parquet_atomic(frame: pl.DataFrame, path: Path) -> None:
    """Write one local derived Parquet file atomically using zstd compression."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.write_parquet(temporary, compression="zstd", statistics=True)
    os.replace(temporary, path)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Write stable formatted JSON to a local artefact path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _git_commit() -> str:
    """Return the local source commit without contacting any remote."""
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def main(argv: Sequence[str] | None = None) -> int:
    """Build and hash the v2.2 target-blind panel without model evaluation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DERIVED_ROOT)
    parser.add_argument("--artifact-root", type=Path, default=ARTIFACT_ROOT)
    parser.add_argument("--origins", type=Path, default=B1_ORIGINS)
    parser.add_argument("--b1-source", type=Path, default=B1_SOURCE)
    parser.add_argument("--fmp-bars", type=Path, default=FMP_BARS)
    parser.add_argument("--b2-primary-root", type=Path, default=B2_PRIMARY_ROOT)
    parser.add_argument("--availability", type=Path, default=B2_AVAILABILITY)
    parser.add_argument("--massive-sensitivity", type=Path, default=MASSIVE_SENSITIVITY)
    args = parser.parse_args(argv)

    panel, common, summary, source_hashes = build_panel(
        origins_path=args.origins,
        b1_source_path=args.b1_source,
        fmp_bars_path=args.fmp_bars,
        b2_primary_root=args.b2_primary_root,
        availability_path=args.availability,
        massive_sensitivity_path=args.massive_sensitivity,
    )
    panel_path = args.output_root / "target_blind_common_predictors_v22.parquet"
    common_path = args.output_root / "target_blind_common_complete_v22.parquet"
    _write_parquet_atomic(panel, panel_path)
    _write_parquet_atomic(common, common_path)

    manifest = {
        "schema_version": "target-blind-common-predictor-manifest-v2.2",
        "status": "PASS_TARGET_BLIND_INPUTS_RECONCILIATION_REMAINS_BLOCKED",
        "scope": "offline_target_blind_predictor_construction_only",
        "no_target_or_metric_payload_read": True,
        "model_fit_performed": False,
        "safe_to_reconcile_existing_results": "NO",
        "timing_rules": {
            "fmp_primary_delay_minutes": 1,
            "fmp_sensitivity_delay_minutes": 2,
            "b1q_primary_state": "SIP_ASOF_ORIGIN_MAX_AGE_60S",
            "massive_reselection_sensitivity_cutoff_seconds": [60, 300],
            "b2_primary_variant": B2_PRIMARY_VARIANT,
            "b2_created_at_rule": ("OPERATIONAL_AVAILABILITY_PROXY_ORIGIN_MINUS_60_SECONDS"),
        },
        "source_hashes": source_hashes,
        "builder_hashes": {
            "script_sha256": sha256_file(Path(__file__).resolve()),
            "panel_module_sha256": sha256_file(
                ROOT / "src" / "mds650" / "target_blind_panel_v22.py"
            ),
        },
        "output": {
            "panel_sha256": sha256_file(panel_path),
            "row_count": panel.height,
            "common_complete_row_count": common.height,
        },
        "summary": summary,
        "source_commit": _git_commit(),
        "output_locations": {
            "panel": (
                "D:/MDS650/phase6/derived/target_blind_v22/"
                "target_blind_common_predictors_v22.parquet"
            ),
            "common_complete": (
                "D:/MDS650/phase6/derived/target_blind_v22/target_blind_common_complete_v22.parquet"
            ),
        },
    }
    _write_json(args.artifact_root / "target_blind_common_predictor_manifest_v22.json", manifest)
    _write_json(args.artifact_root / "target_blind_common_predictor_summary_v22.json", summary)
    coverage = (
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
    coverage.write_csv(
        args.artifact_root / "target_blind_common_predictor_coverage_by_asset_v22.csv"
    )
    print("TARGET_BLIND_COMMON_PREDICTOR_PANEL=PASS")
    print(f"ROWS={panel.height}")
    print(f"COMMON_COMPLETE_ROWS={common.height}")
    print("SAFE_TO_RECONCILE_EXISTING_RESULTS=NO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
