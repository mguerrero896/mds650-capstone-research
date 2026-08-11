"""Build the offline provider-timing PIT v2 evidence bundle.

The command never calls an API. It reads only acquired, target-free provenance
fields and writes compact sanitized evidence into the repository.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from mds650.provider_timing_v2 import (
    DEFAULT_BUFFERS_SECONDS,
    audit_massive_cache_sample,
    audit_massive_selected_quotes,
    audit_uw_b2_feature_windows,
    build_pit_claim_matrix_v2,
    build_provider_timing_gates_v2,
    canonical_sha256,
    fmp_timing_evidence_v2,
    official_source_records_v2,
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse target-free offline audit paths and bounded scan parameters.

    Parameters
    ----------
    argv:
        Optional argument vector. ``None`` uses the process command line.

    Returns
    -------
    argparse.Namespace
        Validated command options. Default bulk paths remain on ``D:``.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--event-root",
        type=Path,
        default=Path(r"D:\MDS650\phase6\data\option_events"),
    )
    parser.add_argument(
        "--origins-path",
        type=Path,
        default=Path(r"D:\MDS650\phase6\data\b1q\phase6_b1_origins.parquet"),
    )
    parser.add_argument(
        "--origin-matrix-path",
        type=Path,
        default=Path(r"D:\MDS650\phase6\data\b1q\b1_origin_matrix_20d.parquet"),
    )
    parser.add_argument(
        "--iv-attempts-path",
        type=Path,
        default=Path(r"D:\MDS650\phase6\data\b1q\b1_iv_attempts_20d.parquet"),
    )
    parser.add_argument(
        "--massive-cache-root",
        type=Path,
        default=Path(r"D:\MDS650\phase6\cache\massive_v4"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/provider_timing_v2"),
    )
    parser.add_argument(
        "--buffers-seconds",
        type=int,
        nargs="+",
        default=list(DEFAULT_BUFFERS_SECONDS),
    )
    parser.add_argument("--batch-size", type=int, default=131_072)
    parser.add_argument("--cache-sample-size", type=int, default=512)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Write deterministic PIT v2 evidence from existing local data only.

    Parameters
    ----------
    argv:
        Optional command arguments. No credential option is accepted.

    Returns
    -------
    int
        Zero after all compact JSON and CSV artifacts have been written.

    Raises
    ------
    FileNotFoundError
        If required acquired timing evidence is missing.
    ValueError
        If a source schema or registered timing buffer is invalid.
    """
    args = parse_args(argv)
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    claims = build_pit_claim_matrix_v2()
    source_records = official_source_records_v2()
    fmp_audit = fmp_timing_evidence_v2()
    uw_audit = audit_uw_b2_feature_windows(
        event_root=args.event_root,
        origins_path=args.origins_path,
        buffers_seconds=tuple(args.buffers_seconds),
        batch_size=args.batch_size,
    )
    massive_audit = audit_massive_selected_quotes(
        origin_matrix_path=args.origin_matrix_path,
        iv_attempts_path=args.iv_attempts_path,
    )
    massive_cache_audit = audit_massive_cache_sample(
        cache_root=args.massive_cache_root,
        sample_size=args.cache_sample_size,
    )
    gates = build_provider_timing_gates_v2(
        uw_audit=uw_audit,
        massive_audit=massive_audit,
        massive_cache_audit=massive_cache_audit,
    )
    _write_source_records(output_dir / "official_sources", source_records)
    _write_json(output_dir / "pit_claim_matrix_v2.json", {"claims": claims})
    _write_json(output_dir / "massive_quote_audit_v2.json", massive_audit)
    _write_csv(
        output_dir / "uw_b2_retention_by_buffer.csv",
        list(uw_audit["feature_window_summary"]),
    )
    _write_csv(
        output_dir / "uw_b2_retention_by_asset.csv",
        _summarize_by_asset(list(uw_audit["feature_window_eligibility"])),
    )
    manifest: dict[str, Any] = {
        "schema_version": "provider-timing-v2.0",
        "scope": "official_documentation_and_existing_acquired_target_free_provider_evidence",
        "no_provider_http_requests_performed": True,
        "no_targets_or_predictive_metrics_read": True,
        "no_canonical_artifacts_modified": True,
        "official_source_ids": [str(record["source_id"]) for record in source_records],
        "official_source_record_sha256": {
            str(record["source_id"]): str(record["archive_record_sha256"])
            for record in source_records
        },
        "claim_matrix_sha256": canonical_sha256(claims),
        "fmp": fmp_audit,
        "uw": uw_audit,
        "massive": massive_audit,
        "massive_cache_schema_sample": massive_cache_audit,
        "gates": gates,
    }
    _write_json(output_dir / "pit_timing_audit_v2.json", manifest)
    return 0


def _write_source_records(directory: Path, records: Sequence[dict[str, Any]]) -> None:
    """Write one deterministic official-source archive record per provider source."""
    directory.mkdir(parents=True, exist_ok=True)
    for record in records:
        source_id = str(record["source_id"])
        _write_json(directory / f"{source_id}.json", record)


def _write_json(path: Path, payload: object) -> None:
    """Write stable human-readable JSON without source filesystem paths."""
    serialized = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True)
    if _contains_personal_path(serialized):
        raise ValueError("TIMING_V2_PERSONAL_PATH_IN_OUTPUT")
    path.write_text(serialized + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    """Write a deterministic compact CSV or a schema-only CSV for empty rows."""
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})


def _summarize_by_asset(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate B2 feature-window counts by asset and buffer without raw data."""
    grouped: dict[tuple[str, int], dict[str, int]] = defaultdict(
        lambda: {
            "asset_date_groups": 0,
            "origin_count": 0,
            "candidate_trade_count": 0,
            "eligible_trade_count": 0,
            "late_record_count": 0,
            "created_at_missing_candidate_count": 0,
            "origins_with_candidate_activity": 0,
            "origins_with_eligible_activity": 0,
        }
    )
    for row in rows:
        key = (str(row["asset"]), int(row["buffer_seconds"]))
        values = grouped[key]
        values["asset_date_groups"] += 1
        for column in (
            "origin_count",
            "candidate_trade_count",
            "eligible_trade_count",
            "late_record_count",
            "created_at_missing_candidate_count",
            "origins_with_candidate_activity",
            "origins_with_eligible_activity",
        ):
            values[column] += int(row[column])
    output: list[dict[str, Any]] = []
    for (asset, buffer), values in sorted(grouped.items()):
        candidates = values["candidate_trade_count"]
        output.append(
            {
                "asset": asset,
                "buffer_seconds": buffer,
                **values,
                "eligible_trade_retention_share": (
                    None if candidates == 0 else values["eligible_trade_count"] / candidates
                ),
            }
        )
    return output


def _contains_personal_path(value: str) -> bool:
    """Reject Windows user-profile paths before committing compact evidence."""
    normalized = value.replace("/", "\\").lower()
    return "c:\\users\\" in normalized or "d:\\users\\" in normalized


if __name__ == "__main__":  # pragma: no cover - command entry point
    raise SystemExit(main())
