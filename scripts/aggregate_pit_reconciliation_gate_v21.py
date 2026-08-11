"""Build the local, target-blind PIT v2.1 reconciliation gate."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from mds650.pit_reconciliation_gate_v21 import write_pit_reconciliation_gate_v21


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse local evidence paths for the PIT v2.1 gate.

    Parameters
    ----------
    argv:
        Optional argument sequence. ``None`` uses process arguments.

    Returns
    -------
    argparse.Namespace
        Parsed, local filesystem paths only.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--massive-artifact",
        type=Path,
        default=Path(
            "artifacts/provider_timing_v21/"
            "massive_reselection_sensitivity_v21_recomputed_20260812.json"
        ),
    )
    parser.add_argument(
        "--uw-artifact",
        type=Path,
        default=Path("artifacts/provider_timing_v21/uw_anomaly_evidence_v21.json"),
    )
    parser.add_argument(
        "--pit-contract",
        type=Path,
        default=Path("docs/provider_timing_pit_contract_v21.md"),
    )
    parser.add_argument(
        "--decision-ledger",
        type=Path,
        default=Path("docs/pit_v21_decision_ledger.md"),
    )
    parser.add_argument(
        "--b2-availability-manifest-v22",
        type=Path,
        default=Path("artifacts/provider_timing_v22/b2_availability_manifest_v22.json"),
    )
    parser.add_argument(
        "--pit-contract-v22",
        type=Path,
        default=Path("docs/provider_timing_pit_contract_v22.md"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/provider_timing_v21/pit_reconciliation_gate_v21_20260812.json"),
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Build the gate and emit a compact, path-free status record.

    Parameters
    ----------
    argv:
        Optional argument sequence for :func:`parse_args`.

    Returns
    -------
    int
        Zero when the deterministic artifact is created or byte-identically
        retained.
    """
    args = parse_args(argv)
    document = write_pit_reconciliation_gate_v21(
        massive_artifact_path=args.massive_artifact,
        uw_artifact_path=args.uw_artifact,
        pit_contract_path=args.pit_contract,
        decision_ledger_path=args.decision_ledger,
        b2_availability_manifest_v22_path=args.b2_availability_manifest_v22,
        pit_contract_v22_path=args.pit_contract_v22,
        output_path=args.output,
    )
    print(
        json.dumps(
            {
                "aggregation_sha256": document["aggregation_sha256"],
                "status": document["status"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
