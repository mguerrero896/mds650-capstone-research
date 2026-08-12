"""Audit offline readiness for a future MDS650 confirmation acquisition.

No provider request, target, forecast, QLIKE, model or sealed OOS payload is
accepted or read.  The script only verifies bound target-blind artefacts and
reports whether a separately proposed acquisition has supplied operational
preflight metadata.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mds650.confirmation_readiness_v1 import (  # noqa: E402
    ConfirmationReadinessConfig,
    build_confirmation_readiness,
)

PANEL_MANIFEST = (
    ROOT / "artifacts" / "target_blind_v22" / "target_blind_common_predictor_manifest_v22.json"
)
PREREGISTRATION = (
    ROOT / "artifacts" / "target_blind_v22" / "next_confirmation_preregistration_v2.json"
)
DEFAULT_OUTPUT = ROOT / "artifacts" / "target_blind_v22" / "confirmation_readiness_v1.json"
DEFAULT_PANEL = (
    Path("D:/MDS650/phase6/derived/target_blind_v22") / "target_blind_common_predictors_v22.parquet"
)
DEFAULT_COMMON = (
    Path("D:/MDS650/phase6/derived/target_blind_v22") / "target_blind_common_complete_v22.parquet"
)
DEFAULT_SIDECAR = (
    Path("D:/MDS650/phase6/derived/provider_timing_v22") / "b2_row_availability_v22.parquet"
)
DEFAULT_DATA_ROOT = Path("D:/MDS650")


def main(argv: Sequence[str] | None = None) -> int:
    """Write a sanitized confirmation-readiness snapshot.

    Parameters
    ----------
    argv:
        Optional command-line arguments for testing.  Omitting
        ``--acquisition-requested`` produces a readiness-only report and does
        not test credentials, cost authority, or a write probe.

    Returns
    -------
    int
        Zero when the report was written, including an intentionally blocked
        report.  Invalid local JSON or an invalid declared peak raises.

    Raises
    ------
    ValueError
        If an input JSON mapping is malformed or the declared storage peak is
        non-positive.

    Notes
    -----
    The output never contains secret values, a provider URL, market data, or
    an absolute personal path.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel-manifest", type=Path, default=PANEL_MANIFEST)
    parser.add_argument("--preregistration", type=Path, default=PREREGISTRATION)
    parser.add_argument("--panel-path", type=Path, default=DEFAULT_PANEL)
    parser.add_argument("--common-path", type=Path, default=DEFAULT_COMMON)
    parser.add_argument("--availability-sidecar", type=Path, default=DEFAULT_SIDECAR)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--acquisition-requested", action="store_true")
    parser.add_argument("--projected-peak-additional-bytes", type=int)
    parser.add_argument("--cost-authorization-id")
    args = parser.parse_args(argv)

    panel_manifest = _read_mapping(args.panel_manifest, "CONFIRMATION_PANEL_MANIFEST_INVALID")
    preregistration = _read_mapping(args.preregistration, "CONFIRMATION_PREREGISTRATION_INVALID")
    report = build_confirmation_readiness(
        ConfirmationReadinessConfig(
            panel_manifest=panel_manifest,
            preregistration=preregistration,
            panel_path=args.panel_path,
            common_path=args.common_path,
            availability_sidecar_path=args.availability_sidecar,
            data_root=args.data_root,
            acquisition_requested=args.acquisition_requested,
            projected_peak_additional_bytes=args.projected_peak_additional_bytes,
            cost_authorization_id=args.cost_authorization_id,
            environment=os.environ,
        )
    )
    _write_json_atomic(args.output, report)
    print(f"CONFIRMATION_READINESS_STATUS={report['status']}")
    print(f"READY_FOR_CONFIRMATION={report['ready_for_confirmation']}")
    print(f"SAFE_TO_ACQUIRE_NEW_SAMPLE={report['safe_to_acquire_new_sample']}")
    print("SAFE_TO_OPEN_OR_EVALUATE_OOS=NO")
    return 0


def _read_mapping(path: Path, error_code: str) -> Mapping[str, Any]:
    """Read one local JSON mapping without exposing its path in the failure."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(error_code) from error
    if not isinstance(payload, Mapping):
        raise ValueError(error_code)
    return payload


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    """Write deterministic JSON atomically to a local, sanitized artefact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


if __name__ == "__main__":
    raise SystemExit(main())
