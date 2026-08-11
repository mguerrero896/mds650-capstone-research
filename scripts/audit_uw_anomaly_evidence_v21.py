"""Create target-blind forensic evidence for selected UW Full Tape incidents.

The command accepts no credentials and performs no network request. It reads only
existing Full Tape timestamp fields and canonical B2 feature/provenance fields.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from mds650.uw_anomaly_evidence_v21 import (
    build_uw_anomaly_evidence_v21,
    write_uw_anomaly_evidence_v21,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVENT_ROOT = Path(r"D:\MDS650\phase6\data\option_events")
DEFAULT_MATRIX_ROOT = Path(r"D:\MDS650\phase6\data\b2\raw_activity_by_session")
DEFAULT_OUTPUT = ROOT / "artifacts" / "provider_timing_v21" / "uw_anomaly_evidence_v21.json"
DEFAULT_INCIDENT_DATES = ("2025-08-21", "2025-09-18", "2025-10-20", "2026-01-29")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse offline Full Tape/B2 evidence arguments.

    Parameters
    ----------
    argv:
        Optional command arguments. ``None`` reads the process command line.

    Returns
    -------
    argparse.Namespace
        Target-free, local-only audit configuration.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-root", type=Path, default=DEFAULT_EVENT_ROOT)
    parser.add_argument("--matrix-root", type=Path, default=DEFAULT_MATRIX_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--session-date",
        action="append",
        dest="session_dates",
        help="Existing ISO session date. Repeated arguments replace the default forensic scope.",
    )
    parser.add_argument(
        "--asset",
        action="append",
        dest="assets",
        help="Existing Full Tape asset. Omit to infer only partition names for the chosen dates.",
    )
    parser.add_argument("--batch-size", type=int, default=131_072)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Write one deterministic, Schema-valid anomaly-evidence document.

    Parameters
    ----------
    argv:
        Optional command arguments.

    Returns
    -------
    int
        Zero after successful local validation and write.

    Raises
    ------
    FileNotFoundError
        If the caller's existing local evidence is unavailable.
    ValueError
        If input schema, timing values, or output sanitisation are invalid.
    """
    args = parse_args(argv)
    session_dates = tuple(args.session_dates) if args.session_dates else DEFAULT_INCIDENT_DATES
    raw_assets = tuple(args.assets) if args.assets else None
    evidence = build_uw_anomaly_evidence_v21(
        event_root=args.event_root,
        matrix_root=args.matrix_root,
        session_dates=session_dates,
        raw_assets=raw_assets,
        batch_size=args.batch_size,
    )
    artifact_sha256 = write_uw_anomaly_evidence_v21(output_path=args.output, evidence=evidence)
    summary: dict[str, Any] = {
        "status": "PASS",
        "artifact_sha256": artifact_sha256,
        "activity_availability_gate": evidence["activity_availability_gate"],
        "activity_availability_gate_reasons": evidence["activity_availability_gate_reasons"],
        "source_incident_count": len(evidence["source_incidents"]),
        "canonical_row_count": len(evidence["canonical_rows"]),
        "no_provider_http_requests_performed": True,
        "no_targets_or_predictive_metrics_read": True,
    }
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
