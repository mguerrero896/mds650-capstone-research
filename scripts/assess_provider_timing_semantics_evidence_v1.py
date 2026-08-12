"""Assess one sanitized provider-timing evidence submission without network access."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from mds650.provider_timing_semantics_evidence_intake_v1 import (
    write_provider_timing_semantics_evidence_assessment_v1,
)


def _parser() -> argparse.ArgumentParser:
    """Build the narrow local-only command-line interface."""
    parser = argparse.ArgumentParser(
        description=(
            "Validate one sanitized provider-timing evidence submission and write a "
            "fail-closed review assessment. No provider HTTP request is sent."
        )
    )
    parser.add_argument(
        "--submission",
        required=True,
        type=Path,
        help="Sanitized submission JSON following the v1 input schema.",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Immutable assessment JSON destination.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the local, fail-closed provider evidence intake command.

    Parameters
    ----------
    argv
        Optional argument sequence.  ``None`` reads process arguments.

    Returns
    -------
    int
        Zero after an immutable assessment write or byte-identical replay;
        two after a sanitized validation failure.

    Notes
    -----
    The command validates local JSON only. It sends no provider request,
    reads no secret, and cannot authorize network access, reconciliation,
    OOS access, model fitting, or metric evaluation.
    """
    args = _parser().parse_args(argv)
    try:
        write_provider_timing_semantics_evidence_assessment_v1(
            submission_path=args.submission,
            output_path=args.output,
        )
    except (OSError, ValueError) as exc:
        print(f"PIT_EVIDENCE_ASSESSMENT_FAILED:{exc}", file=sys.stderr)
        return 2
    print("PIT_EVIDENCE_ASSESSMENT_WRITTEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
