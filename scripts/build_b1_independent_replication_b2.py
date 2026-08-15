"""Build corrected target-blind B2 predictors for the frozen replication."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from mds650.b1_replication_b2 import (
    build_replication_b2_artifacts,
    load_replication_full_tape_contract,
)
from mds650.b1v3_confirmation import canonical_sha256

ROOT = Path(__file__).resolve().parents[1]


def _arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--preregistration",
        type=Path,
        default=ROOT
        / "artifacts/b1_diagnostic_replication/preregistration/preregistration.json",
    )
    parser.add_argument(
        "--provider-report",
        type=Path,
        default=ROOT
        / "artifacts/b1_diagnostic_replication/provider_preflight/"
        "provider_preflight_report.json",
    )
    parser.add_argument(
        "--full-tape-manifest",
        type=Path,
        default=ROOT
        / "artifacts/b1_diagnostic_replication/acquisition/"
        "full_tape_acquisition_manifest.json",
    )
    parser.add_argument(
        "--full-tape-schema",
        type=Path,
        default=ROOT
        / "specs/001-pit-options-rv30/contracts/"
        "b1-independent-replication-full-tape-v1.schema.json",
    )
    parser.add_argument(
        "--base-manifest",
        type=Path,
        default=ROOT
        / "artifacts/b1_diagnostic_replication/panel/base_predictor_manifest.json",
    )
    parser.add_argument(
        "--origins",
        type=Path,
        default=Path(
            "D:/MDS650/b1_diagnostic_replication/predictors/"
            "forecast_origins_target_blind.parquet"
        ),
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path("D:/MDS650/b1_diagnostic_replication"),
    )
    parser.add_argument(
        "--event-root",
        type=Path,
        default=Path("D:/MDS650/b1_diagnostic_replication/data/option_events"),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("D:/MDS650/b1_diagnostic_replication/predictors/b2"),
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT
        / "artifacts/b1_diagnostic_replication/panel/b2_predictor_manifest.json",
    )
    parser.add_argument(
        "--schema",
        type=Path,
        default=ROOT
        / "specs/001-pit-options-rv30/contracts/"
        "b1-independent-replication-b2-v1.schema.json",
    )
    return parser.parse_args(argv)


def _read(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("REPLICATION_B2_REQUIRED_JSON_INVALID")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    """Build three B2 timing variants and print sanitized identities."""
    args = _arguments(argv)
    preregistration = _read(args.preregistration)
    stored = preregistration.get("manifest_sha256")
    unsigned = {
        key: value for key, value in preregistration.items() if key != "manifest_sha256"
    }
    raw_sessions = preregistration.get("replication_sessions")
    if (
        not isinstance(stored, str)
        or stored != canonical_sha256(unsigned)
        or preregistration.get("replication_target_reads") != 0
        or not isinstance(raw_sessions, list)
    ):
        raise ValueError("REPLICATION_B2_PREREGISTRATION_INVALID")
    provider_report = _read(args.provider_report)
    provider_hash = provider_report.get("report_sha256")
    provider_unsigned = {
        key: value for key, value in provider_report.items() if key != "report_sha256"
    }
    if (
        not isinstance(provider_hash, str)
        or provider_hash != canonical_sha256(provider_unsigned)
        or provider_report.get("outcome_read_count") != 0
    ):
        raise ValueError("REPLICATION_B2_PROVIDER_REPORT_INVALID")
    sessions = tuple(str(value) for value in raw_sessions)
    contract = load_replication_full_tape_contract(
        args.full_tape_manifest,
        schema_path=args.full_tape_schema,
        preregistration_sha256=stored,
        provider_report_sha256=provider_hash,
        sessions=sessions,
    )
    artifacts = build_replication_b2_artifacts(
        preregistration_sha256=stored,
        full_tape_contract=contract,
        base_manifest_path=args.base_manifest,
        origins_path=args.origins,
        sessions=sessions,
        data_root=args.data_root,
        event_root=args.event_root,
        output_root=args.output_root,
        manifest_path=args.manifest,
        manifest_schema_path=args.schema,
    )
    print(
        json.dumps(
            {
                "status": "PASS_TARGET_BLIND_B2_PREDICTORS",
                "session_count": len(sessions),
                "outcome_read_count": 0,
                "manifest_file_sha256": artifacts.manifest_file_sha256,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
