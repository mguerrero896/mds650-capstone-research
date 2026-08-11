"""Run the target-free Provider Timing PIT v2.1 audit."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from mds650.provider_timing_v21 import (
    audit_b2_canonical_traceability,
    audit_forecast_origin_session_bounds,
    audit_massive_reselection,
    audit_uw_session_asset_incidents,
    canonical_sha256,
)

ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = Path(r"D:\MDS650\phase6\data")
CACHE_ROOT = Path(r"D:\MDS650\phase6\cache\massive_v4")


def _session_dates(event_root: Path) -> tuple[str, ...]:
    """Return deterministic existing ISO date partitions.

    Parameters
    ----------
    event_root
        Existing Full Tape partition root.

    Returns
    -------
    tuple[str, ...]
        ISO-like date directory identifiers.
    """
    values = [
        path.name.removeprefix("date=")
        for path in event_root.glob("date=*")
        if path.is_dir()
    ]
    return tuple(sorted(value for value in values if len(value) == 10))


def _assets(event_root: Path, dates: Iterable[str]) -> tuple[str, ...]:
    """Return deterministic assets observed in existing partitions.

    Parameters
    ----------
    event_root
        Existing Full Tape partition root.
    dates
        Existing session dates.

    Returns
    -------
    tuple[str, ...]
        Unique lexical asset identifiers.
    """
    values: set[str] = set()
    for session_date in dates:
        values.update(
            path.name.removeprefix("asset=")
            for path in (event_root / f"date={session_date}").glob("asset=*")
            if path.is_dir()
        )
    return tuple(sorted(values))


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    """Write one deterministic rectangular CSV sidecar.

    Parameters
    ----------
    path
        Output path.
    rows
        Mapping rows.

    Raises
    ------
    ValueError
        If there are no fields.
    """
    fieldnames = sorted({key for row in rows for key in row})
    if not fieldnames:
        raise ValueError("TIMING_V21_CSV_ROWS_EMPTY")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="raise")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})


def _read_csv(path: Path) -> list[dict[str, str]]:
    """Read a sanitised CSV sidecar without coercing its fields.

    Parameters
    ----------
    path
        Existing CSV sidecar.

    Returns
    -------
    list[dict[str, str]]
        Rows in file order.
    """
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _summarize_incidents(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Summarise UW incident rows without predictive interpretation.

    Parameters
    ----------
    rows
        Existing provider timing incident rows.

    Returns
    -------
    dict[str, Any]
        Counts and the preselected forensic incident dates.
    """
    states = Counter(str(row["source_temporal_state"]) for row in rows)
    named_dates = {"2025-08-21", "2025-09-18", "2025-10-20", "2026-01-29"}
    named = [row for row in rows if str(row["session_date"]) in named_dates]
    return {
        "session_asset_row_count": len(rows),
        "source_temporal_state_counts": dict(sorted(states.items())),
        "named_session_incident_rows": named,
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Create the target-free Provider Timing PIT v2.1 audit.

    Parameters
    ----------
    argv
        Optional CLI arguments.

    Returns
    -------
    int
        Zero after local audit completion.

    Raises
    ------
    ValueError
        If mutually exclusive flags or compact reuse evidence are invalid.
    FileNotFoundError
        If compact reuse evidence is missing.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-root", type=Path, default=DATA_ROOT / "option_events")
    parser.add_argument(
        "--b2-matrix-root", type=Path, default=DATA_ROOT / "b2" / "raw_activity_by_session"
    )
    parser.add_argument(
        "--expected-origins-path",
        type=Path,
        default=DATA_ROOT / "b1q" / "phase6_b1_origins.parquet",
    )
    parser.add_argument(
        "--iv-attempts-path", type=Path, default=DATA_ROOT / "b1q" / "b1_iv_attempts_20d.parquet"
    )
    parser.add_argument("--massive-cache-root", type=Path, default=CACHE_ROOT)
    parser.add_argument(
        "--output-dir", type=Path, default=ROOT / "artifacts" / "provider_timing_v21"
    )
    parser.add_argument("--batch-size", type=int, default=131_072)
    parser.add_argument("--skip-massive", action="store_true")
    parser.add_argument(
        "--reuse-massive-json",
        type=Path,
        help="Reuse a prior compact Massive sensitivity result; never reopen the raw cache.",
    )
    parser.add_argument(
        "--reuse-incidents-csv",
        type=Path,
        help="Reuse an already generated compact UW incident CSV; never rescan Full Tape.",
    )
    args = parser.parse_args(argv)
    if args.skip_massive and args.reuse_massive_json is not None:
        raise ValueError("TIMING_V21_SKIP_AND_REUSE_MASSIVE_CONFLICT")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    if args.reuse_incidents_csv is None:
        dates = _session_dates(args.event_root)
        assets = _assets(args.event_root, dates)
        incidents = audit_uw_session_asset_incidents(
            event_root=args.event_root,
            session_dates=dates,
            assets=assets,
            batch_size=args.batch_size,
        )
    else:
        incidents = _read_csv(args.reuse_incidents_csv)
    origin_session_bounds = audit_forecast_origin_session_bounds(
        origins_path=args.expected_origins_path,
        batch_size=args.batch_size,
    )
    traceability, b2_gate = audit_b2_canonical_traceability(
        matrix_root=args.b2_matrix_root,
        incidents=incidents,
        expected_origins_path=args.expected_origins_path,
    )
    _write_csv(args.output_dir / "uw_session_asset_incidents_v21.csv", incidents)
    _write_csv(args.output_dir / "b2_canonical_traceability_v21.csv", traceability)

    massive: dict[str, Any]
    if args.reuse_massive_json is not None:
        if not args.reuse_massive_json.is_file():
            raise FileNotFoundError("TIMING_V21_REUSED_MASSIVE_RESULT_MISSING")
        reused_massive = json.loads(args.reuse_massive_json.read_text(encoding="utf-8"))
        if not isinstance(reused_massive, dict):
            raise ValueError("TIMING_V21_REUSED_MASSIVE_RESULT_INVALID")
        massive = reused_massive
    elif args.skip_massive:
        massive = {"status": "SKIPPED_BY_EXPLICIT_CLI_FLAG"}
    else:
        massive = audit_massive_reselection(
            attempts_path=args.iv_attempts_path,
            cache_root=args.massive_cache_root,
            batch_size=args.batch_size,
        )
    (args.output_dir / "massive_reselection_sensitivity_v21.json").write_text(
        json.dumps(massive, indent=2, sort_keys=True), encoding="utf-8"
    )
    massive_status = str(
        massive.get(
            "status",
            "PASS"
            if not massive.get("cache_identity_failures")
            and massive.get("quote_existence_coverage_monotonic_nonincreasing") is True
            else "FAIL_CACHE_IDENTITY_OR_MONOTONICITY",
        )
    )
    reconciliation_gate_reasons: list[str] = []
    if b2_gate != "PASS":
        reconciliation_gate_reasons.append("B2_ACTIVITY_AVAILABILITY_GATE_NOT_CLOSED")
    if massive_status != "PASS":
        reconciliation_gate_reasons.append("MASSIVE_CACHE_IDENTITY_GATE_NOT_PASS")
    if origin_session_bounds["status"] != "PASS":
        reconciliation_gate_reasons.append("FORECAST_ORIGIN_SESSION_GATE_NOT_PASS")
    safe_to_reconcile_existing_results = not reconciliation_gate_reasons
    audit = {
        "schema_version": "provider-timing-v2.1",
        "scope": "offline_existing_acquired_provider_inputs_only",
        "no_provider_http_requests_performed": True,
        "no_targets_or_predictive_metrics_read": True,
        "uw": _summarize_incidents(incidents),
        "b2": {
            "traceability_row_count": len(traceability),
            "b2_activity_availability_gate": b2_gate,
            "coding_status_counts": dict(
                sorted(Counter(str(row["coding_status"]) for row in traceability).items())
            ),
        },
        "forecast_origin_session_bounds": origin_session_bounds,
        "massive": {
            "status": massive_status,
            "quote_existence_coverage_monotonic_nonincreasing": massive.get(
                "quote_existence_coverage_monotonic_nonincreasing"
            ),
        },
        "reconciliation_gate": {
            "safe_to_reconcile_existing_results": safe_to_reconcile_existing_results,
            "reasons": reconciliation_gate_reasons,
            "scope": (
                "Existing sealed results may be reconciled only after every listed "
                "provider-timing gate is closed; this audit never reads those results."
            ),
        },
    }
    audit["audit_sha256"] = canonical_sha256(audit)
    (args.output_dir / "pit_timing_audit_v21.json").write_text(
        json.dumps(audit, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": "PASS",
                "uw_session_asset_rows": len(incidents),
                "b2_traceability_rows": len(traceability),
                "b2_activity_availability_gate": b2_gate,
                "massive_status": massive_status,
                "safe_to_reconcile_existing_results": safe_to_reconcile_existing_results,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
