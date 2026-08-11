"""Build the target-blind B2 availability remediation sidecar v2.2.

The command operates exclusively on already acquired Full Tape partitions and
immutable canonical B2 matrices.  It does not open targets, predictions,
QLIKE, models, or sealed OOS artefacts, and it makes no provider request.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import polars as pl

from mds650.b2_availability_v22 import build_b2_availability_sidecar


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse deterministic local paths for the target-free v2.2 builder.

    Parameters
    ----------
    argv
        Optional command-line tokens.  When omitted, values are read from the
        process command line.

    Returns
    -------
    argparse.Namespace
        Validated command-line namespace.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-root", type=Path, required=True)
    parser.add_argument("--matrix-root", type=Path, required=True)
    parser.add_argument("--expected-origins-path", type=Path, required=True)
    parser.add_argument("--traceability-csv", type=Path, required=True)
    parser.add_argument("--sidecar-output", type=Path, required=True)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Write the D-resident sidecar and compact sanitized v2.2 evidence.

    Parameters
    ----------
    argv
        Optional CLI tokens; see :func:`parse_args`.

    Returns
    -------
    int
        Zero when input identity and all availability invariants pass.

    Raises
    ------
    ValueError
        If a canonical identity, row count, or required v2.2 assertion fails.
    """
    args = parse_args(argv)
    _require_inputs(args)
    traceability = pl.read_csv(args.traceability_csv).to_dicts()
    sidecar, summary = build_b2_availability_sidecar(
        event_root=args.event_root,
        matrix_root=args.matrix_root,
        expected_origins_path=args.expected_origins_path,
        traceability_rows=traceability,
    )
    _validate_build(sidecar, summary)
    _atomic_write_parquet(args.sidecar_output, sidecar)
    sidecar_sha256 = _sha256_file(args.sidecar_output)
    args.artifact_dir.mkdir(parents=True, exist_ok=True)
    _write_compact_evidence(
        artifact_dir=args.artifact_dir,
        sidecar=sidecar,
        summary=summary,
        sidecar_sha256=sidecar_sha256,
        expected_origins_sha256=_sha256_file(args.expected_origins_path),
        traceability_sha256=_sha256_file(args.traceability_csv),
    )
    print(
        json.dumps(
            {
                "status": "PASS_WITH_EXCLUSIONS",
                "row_count": summary["row_count"],
                "eligible_row_count": summary["eligible_row_count"],
                "excluded_row_count": summary["excluded_row_count"],
                "primary_delayed_raw_zero_exclusion_count": summary[
                    "primary_delayed_raw_zero_exclusion_count"
                ],
                "sidecar_sha256": sidecar_sha256,
            },
            sort_keys=True,
        )
    )
    return 0


def _require_inputs(args: argparse.Namespace) -> None:
    """Fail before output creation if any read-only input is absent."""
    for path in (
        args.event_root,
        args.matrix_root,
        args.expected_origins_path,
        args.traceability_csv,
    ):
        if not path.exists():
            raise ValueError("B2_AVAILABILITY_V22_INPUT_MISSING")


def _validate_build(sidecar: pl.DataFrame, summary: dict[str, Any]) -> None:
    """Enforce target-free output completeness and the known v2.1 incident."""
    expected_rows = 5 * 77_328
    if sidecar.height != expected_rows:
        raise ValueError("B2_AVAILABILITY_V22_UNEXPECTED_ROW_COUNT")
    if int(summary["row_count"]) != expected_rows:
        raise ValueError("B2_AVAILABILITY_V22_SUMMARY_ROW_COUNT_MISMATCH")
    known_incident_count = sidecar.filter(
        (pl.col("canonical_variant") == "primary_5m_60s")
        & (pl.col("session_date") == "2025-10-20")
        & (pl.col("row_status") == "PIT_EXCLUDED_DELAYED_RAW_WINDOW_TRADES")
    ).height
    if known_incident_count != 432:
        raise ValueError("B2_AVAILABILITY_V22_KNOWN_INCIDENT_COUNT_MISMATCH")
    if sidecar.filter(
        pl.col("eligible_for_corrected_pit_panel")
        & (pl.col("row_status") == "PIT_EXCLUDED_DELAYED_RAW_WINDOW_TRADES")
    ).height:
        raise ValueError("B2_AVAILABILITY_V22_DELAYED_ZERO_ELIGIBLE")


def _write_compact_evidence(
    *,
    artifact_dir: Path,
    sidecar: pl.DataFrame,
    summary: dict[str, Any],
    sidecar_sha256: str,
    expected_origins_sha256: str,
    traceability_sha256: str,
) -> None:
    """Write human- and machine-readable evidence without local raw paths."""
    by_variant = (
        sidecar.group_by("canonical_variant", "row_status")
        .agg(
            pl.len().alias("row_count"),
            pl.col("eligible_for_corrected_pit_panel").sum().alias("eligible_row_count"),
        )
        .with_columns(
            (pl.col("row_count") - pl.col("eligible_row_count")).alias("excluded_row_count")
        )
        .sort("canonical_variant", "row_status")
    )
    by_incident = (
        sidecar.filter(~pl.col("eligible_for_corrected_pit_panel"))
        .group_by("canonical_variant", "session_date", "asset", "row_status")
        .agg(pl.len().alias("excluded_row_count"))
        .sort("canonical_variant", "session_date", "asset", "row_status")
    )
    by_variant.write_csv(artifact_dir / "b2_availability_by_variant_v22.csv")
    by_incident.write_csv(artifact_dir / "b2_availability_by_incident_v22.csv")
    manifest = {
        "schema_version": "2.2",
        "generation_mode": "deterministic_target_blind_rebuild",
        "scope": "target_blind_offline_no_provider_requests",
        "b2_availability_sidecar_status": "PASS_WITH_EXCLUSIONS",
        "corrected_pit_panel_preparation": "PASS_MASK_READY_REQUIRES_NEW_TARGET_BLIND_PANEL_BUILD",
        "safe_to_reconcile_existing_results": "NO",
        "sealed_result_reconciliation": "BLOCKED",
        "oos_payload_read": False,
        "model_or_metric_payload_read": False,
        "sidecar_storage": "D-resident derived artefact",
        "sidecar_sha256": sidecar_sha256,
        "expected_origins_sha256": expected_origins_sha256,
        "traceability_sha256": traceability_sha256,
        "summary": summary,
        "limitations": [
            "Unusual Whales created_at remains an operational availability proxy, "
            "not provider-proven publication or receipt time.",
            "The sidecar does not repair, rerun, or validate sealed model or evaluation results.",
            "Excluded rows require a new target-blind common-panel build before "
            "any future confirmation protocol can proceed.",
        ],
    }
    _atomic_write_json(artifact_dir / "b2_availability_manifest_v22.json", manifest)
    _atomic_write_json(artifact_dir / "b2_availability_summary_v22.json", summary)


def _atomic_write_parquet(path: Path, frame: pl.DataFrame) -> None:
    """Write a Parquet output atomically within its destination directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    frame.write_parquet(temporary, compression="zstd")
    os.replace(temporary, path)


def _atomic_write_json(path: Path, value: Any) -> None:
    """Write deterministic JSON atomically without embedding local paths."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", delete=False, dir=path.parent, suffix=".tmp"
    ) as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        temporary = Path(stream.name)
    os.replace(temporary, path)


def _sha256_file(path: Path) -> str:
    """Return a streaming SHA-256 digest for a file."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1_048_576), b""):
            digest.update(block)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
