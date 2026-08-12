"""Build sanitized timing evidence from already-acquired provider data only.

The script is deliberately offline.  It reads the filtered Unusual Whales Full
Tape Parquet files already stored under ``MDS650_DATA_ROOT`` and writes compact
statistics to the repository.  It never fetches a provider endpoint, reads a
research target or changes a canonical result.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from mds650.provider_timing import (
    FMP_BAR_LABEL_SEMANTICS,
    FMP_LIVE_PROBE_STATUS,
    FMP_OFFICIAL_DOCUMENTATION_INDEX_URL,
    FMP_OFFICIAL_DOCUMENTATION_URL,
    FMP_PROVIDER_CONFIRMED_LATENCY,
    FMP_RESEARCH_AVAILABILITY_RULE,
    audit_uw_full_tape,
    provider_timing_gates,
)

ROOT = Path(__file__).resolve().parents[1]
# ``MDS650_DATA_ROOT`` historically points at ``D:\MDS650\data`` for panel
# construction.  Full Tape cohorts are sibling storage roots, so this audit has
# an explicit bulk-root override instead of silently appending the wrong path.
DEFAULT_BULK_ROOT = Path(os.environ.get("MDS650_BULK_ROOT", r"D:\MDS650"))
DEFAULT_OUTPUT = ROOT / "artifacts" / "provider_timing"
EVIDENCE_DATE = "2026-08-11"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse offline timing-audit options.

    Parameters
    ----------
    argv:
        Optional explicit command arguments for testable invocation.

    Returns
    -------
    argparse.Namespace
        Validated local source roots, output root and bounded scan settings.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase6-event-root",
        type=Path,
        default=DEFAULT_BULK_ROOT / "phase6" / "data" / "option_events",
        help="Existing filtered Full Tape Phase 6 root; no download occurs.",
    )
    parser.add_argument(
        "--independent-event-root",
        type=Path,
        default=DEFAULT_BULK_ROOT / "independent_replication_30" / "data" / "option_events",
        help="Existing filtered Full Tape independent-replication root; no download occurs.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Sanitized artifact directory.",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=250_000,
        help="Approximate deterministic sample size for non-session quantiles.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=262_144,
        help="Bounded Parquet batch size in rows.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Write deterministic FMP/UW timing artifacts from local evidence only.

    Parameters
    ----------
    argv:
        Optional explicit command arguments.

    Returns
    -------
    int
        Zero after all sanitized output files have been written.

    Raises
    ------
    FileNotFoundError
        If an expected existing Full Tape root is missing.
    ValueError
        If a Full Tape partition or timestamp schema is invalid.
    """
    args = parse_args(argv)
    audit = audit_uw_full_tape(
        {
            "independent_replication_30": args.independent_event_root,
            "phase6": args.phase6_event_root,
        },
        sample_size=args.sample_size,
        batch_size=args.batch_size,
    )
    fmp_documentation = _fmp_documentation_record()
    payload: dict[str, Any] = {
        "schema_version": "provider-timing-semantics-audit-1.0",
        "evidence_date": EVIDENCE_DATE,
        "scope": "offline_existing_provider_evidence_only",
        "fmp": {
            **fmp_documentation,
            "fmp_bar_label_semantics": FMP_BAR_LABEL_SEMANTICS,
            "fmp_provider_confirmed_latency": FMP_PROVIDER_CONFIRMED_LATENCY,
            "fmp_research_availability_rule": FMP_RESEARCH_AVAILABILITY_RULE,
            "primary_availability_delay_seconds": 60,
            "sensitivity_availability_delay_seconds": 120,
            "live_probe_status": FMP_LIVE_PROBE_STATUS,
        },
        "unusual_whales": audit.payload,
        "gates": provider_timing_gates(),
        "no_targets_or_predictive_metrics_read": True,
        "no_provider_http_requests_performed": True,
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
    }
    payload["manifest_sha256"] = _canonical_sha256(payload)
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "provider_timing_semantics_audit_v1.json", payload)
    _write_json(output_dir / "fmp_official_documentation_v1.json", fmp_documentation)
    _write_csv(output_dir / "uw_historical_latency_summary.csv", audit.summary)
    _write_csv(output_dir / "uw_historical_latency_by_session.csv", audit.by_session)
    _write_csv(output_dir / "uw_historical_latency_by_asset.csv", audit.by_asset)
    print(
        json.dumps(
            {
                "status": "PASS_OFFLINE_TIMING_AUDIT",
                "manifest_sha256": payload["manifest_sha256"],
                "historical_uw_classification": audit.payload["historical_uw_classification"],
                "output_dir": _logical_output_dir(output_dir),
            },
            sort_keys=True,
        )
    )
    return 0


def _fmp_documentation_record() -> dict[str, Any]:
    """Return the archival, evidence-scoped record of official FMP documentation."""
    return {
        "archive_type": "sanitized_official_documentation_citation_record",
        "retrieved_on": EVIDENCE_DATE,
        "official_sources": [
            {
                "url": FMP_OFFICIAL_DOCUMENTATION_URL,
                "title": "FMP 1 Min Interval Stock Chart API",
                "observed_statement": (
                    "The official page describes real-time or historical one-minute OHLCV data "
                    "through the historical-chart/1min endpoint."
                ),
            },
            {
                "url": FMP_OFFICIAL_DOCUMENTATION_INDEX_URL,
                "title": "FMP official documentation index",
                "observed_statement": (
                    "The official index lists the one-minute intraday chart endpoint and "
                    "identifies "
                    "open, high, low, close and volume for each minute."
                ),
            },
        ],
        "not_stated_by_documentation": [
            "timezone carried by the response timestamp",
            "whether the response timestamp labels interval start or interval close",
            "provider publication latency for a completed minute bar",
        ],
        "interpretation": (
            "The official documentation supports the endpoint and one-minute OHLCV scope, but does "
            "not support an exact timestamp-label or provider-latency claim."
        ),
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Write stable formatted JSON atomically."""
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    """Write a deterministic CSV with a stable scope-first column order."""
    preferred = ["granularity", "cohort", "session_date", "asset"]
    fieldnames = preferred + sorted({key for row in rows for key in row if key not in preferred})
    temporary = path.with_suffix(path.suffix + ".part")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in fieldnames})
    temporary.replace(path)


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    """Hash a JSON-compatible mapping without importing research-result modules."""
    import hashlib

    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _logical_output_dir(path: Path) -> str:
    """Return a distributable output identifier without emitting a user path."""
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return "external_sanitized_output"


if __name__ == "__main__":
    raise SystemExit(main())
