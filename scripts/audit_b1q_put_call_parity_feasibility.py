"""Build a target-free B1Q put-call-parity feasibility report from local cache data."""

from __future__ import annotations

import argparse
import hashlib
import sys
from collections.abc import Sequence
from pathlib import Path

import polars as pl

from mds650.b1q_put_call_parity_feasibility import (
    ALLOWED_ATTEMPT_COLUMNS,
    assess_put_call_parity_feasibility,
    write_json_if_new_or_identical,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ATTEMPTS_PATH = Path("D:/MDS650/data/b1q/phase5_missing_55/b1_iv_attempts_20d.parquet")
DEFAULT_OUTPUT_PATH = (
    ROOT / "artifacts" / "corrected_development_v1" / "b1q_put_call_parity_feasibility_v1.json"
)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse bounded, local-only diagnostic paths and filters.

    Parameters
    ----------
    argv:
        Optional CLI arguments.  ``None`` reads the current process arguments.

    Returns
    -------
    argparse.Namespace
        Validated command-line values for a local source and immutable report.

    Examples
    --------
    >>> _parse_args(["--quote-age-limit-seconds", "60"]).quote_age_limit_seconds
    60.0
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attempts-path", type=Path, default=DEFAULT_ATTEMPTS_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--quote-age-limit-seconds", type=float, default=60.0)
    parser.add_argument("--relative-spread-limit", type=float, default=0.25)
    return parser.parse_args(argv)


def _sha256_file(path: Path) -> str:
    """Return the SHA-256 digest of a local file without loading it fully into memory.

    Parameters
    ----------
    path:
        Existing local source file.

    Returns
    -------
    str
        Lowercase hexadecimal SHA-256 digest.

    Raises
    ------
    OSError
        If the file cannot be opened or read.
    """
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    """Run the local, target-free parity feasibility diagnostic.

    The command reads exactly the allowlisted B1Q quote-attempt columns from
    an existing local Parquet file.  It makes no network request, reads no
    target or metric, and writes a deterministic JSON report only when the
    destination is new or byte-identical.

    Parameters
    ----------
    argv:
        Optional CLI argument sequence.

    Returns
    -------
    int
        Zero on a successful immutable write or identical replay; two for an
        invalid source or diagnostic contract failure.

    Examples
    --------
    >>> # main(["--attempts-path", "D:/MDS650/.../b1_iv_attempts_20d.parquet"])
    """
    args = _parse_args(argv)
    if not args.attempts_path.is_file():
        print("B1Q_PARITY_ATTEMPTS_FILE_NOT_FOUND", file=sys.stderr)
        return 2
    try:
        attempts = pl.read_parquet(args.attempts_path, columns=list(ALLOWED_ATTEMPT_COLUMNS))
        report = assess_put_call_parity_feasibility(
            attempts,
            source_file_sha256=_sha256_file(args.attempts_path),
            quote_age_limit_seconds=args.quote_age_limit_seconds,
            relative_spread_limit=args.relative_spread_limit,
        )
        write_state = write_json_if_new_or_identical(args.output, report)
    except (OSError, ValueError, pl.exceptions.PolarsError) as error:
        print(str(error), file=sys.stderr)
        return 2
    print(f"B1Q_PARITY_FEASIBILITY_STATUS={report['status']}")
    print(f"B1Q_PARITY_REPORT_WRITE={write_state}")
    print(f"B1Q_PARITY_REPORT_SHA256={report['semantic_self_hash']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
