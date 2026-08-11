"""Build the target-blind MDS650 PIT v2.2 claims-and-limitations ledger.

The script reads only target-blind manifests, provider-timing documentation and
availability summaries. It has no provider, target, forecast, metric or model
arguments and must not be used to inspect sealed evaluation artefacts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mds650.pit_v22_claim_ledger import (  # noqa: E402
    build_claim_ledger,
    render_claims_markdown,
)

DEFAULT_PANEL_MANIFEST = (
    ROOT / "artifacts" / "target_blind_v22" / "target_blind_common_predictor_manifest_v22.json"
)
DEFAULT_READINESS = ROOT / "artifacts" / "target_blind_v22" / "confirmation_readiness_v1.json"
DEFAULT_AVAILABILITY_MANIFEST = (
    ROOT / "artifacts" / "provider_timing_v22" / "b2_availability_manifest_v22.json"
)
DEFAULT_AVAILABILITY_SUMMARY = (
    ROOT / "artifacts" / "provider_timing_v22" / "b2_availability_summary_v22.json"
)
DEFAULT_PIT_CONTRACT = ROOT / "docs" / "provider_timing_pit_contract_v21.md"
DEFAULT_CLAIM_MATRIX = ROOT / "docs" / "provider_timing_claim_matrix_v21.md"
DEFAULT_OUTPUT = ROOT / "artifacts" / "target_blind_v22" / "pit_v22_claim_ledger_v1.json"
DEFAULT_MARKDOWN = ROOT / "docs" / "pit_v22_claims_and_limitations.md"


def main(argv: Sequence[str] | None = None) -> int:
    """Generate a self-hashing target-blind claim ledger and Markdown mirror.

    Parameters
    ----------
    argv:
        Optional local file arguments used by tests or a deterministic replay.

    Returns
    -------
    int
        Zero when both sanitized outputs are written.

    Raises
    ------
    ValueError
        If an input JSON mapping is invalid or cannot satisfy the strict
        target-blind claim contract.

    Notes
    -----
    The output uses only logical repository-relative evidence paths. It never
    writes personal absolute paths or secret values.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel-manifest", type=Path, default=DEFAULT_PANEL_MANIFEST)
    parser.add_argument("--readiness", type=Path, default=DEFAULT_READINESS)
    parser.add_argument("--availability-manifest", type=Path, default=DEFAULT_AVAILABILITY_MANIFEST)
    parser.add_argument("--availability-summary", type=Path, default=DEFAULT_AVAILABILITY_SUMMARY)
    parser.add_argument("--pit-contract", type=Path, default=DEFAULT_PIT_CONTRACT)
    parser.add_argument("--claim-matrix", type=Path, default=DEFAULT_CLAIM_MATRIX)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN)
    args = parser.parse_args(argv)

    source_paths = {
        "panel_manifest": args.panel_manifest,
        "confirmation_readiness": args.readiness,
        "availability_manifest": args.availability_manifest,
        "availability_summary": args.availability_summary,
        "pit_contract_v21": args.pit_contract,
        "claim_matrix_v21": args.claim_matrix,
    }
    ledger = build_claim_ledger(
        _read_mapping(args.panel_manifest, "PIT_V22_CLAIM_LEDGER_PANEL_JSON_INVALID"),
        _read_mapping(args.readiness, "PIT_V22_CLAIM_LEDGER_READINESS_JSON_INVALID"),
        _read_mapping(
            args.availability_manifest,
            "PIT_V22_CLAIM_LEDGER_AVAILABILITY_MANIFEST_JSON_INVALID",
        ),
        _read_mapping(
            args.availability_summary,
            "PIT_V22_CLAIM_LEDGER_AVAILABILITY_SUMMARY_JSON_INVALID",
        ),
        {key: _sha256_file(path) for key, path in source_paths.items()},
    )
    _write_json_atomic(args.output, ledger)
    _write_text_atomic(args.markdown_output, render_claims_markdown(ledger))
    print("PIT_V22_CLAIM_LEDGER_STATUS=PASS_TARGET_BLIND_CLAIMS_NO_EVALUATION")
    print("SAFE_TO_RECONCILE_EXISTING_RESULTS=NO")
    print("SAFE_TO_OPEN_OR_EVALUATE_OOS=NO")
    return 0


def _read_mapping(path: Path, error_code: str) -> Mapping[str, Any]:
    """Read one local JSON mapping without echoing an absolute filesystem path."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(error_code) from error
    if not isinstance(payload, Mapping):
        raise ValueError(error_code)
    return payload


def _sha256_file(path: Path) -> str:
    """Hash one evidence source incrementally without retaining its contents."""
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise ValueError("PIT_V22_CLAIM_LEDGER_EVIDENCE_SOURCE_UNREADABLE") from error
    return digest.hexdigest()


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    """Write deterministic JSON atomically to a local target-blind artefact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _write_text_atomic(path: Path, value: str) -> None:
    """Write deterministic UTF-8 text atomically with a single trailing newline."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value.rstrip() + "\n", encoding="utf-8")
    os.replace(temporary, path)


if __name__ == "__main__":
    raise SystemExit(main())
