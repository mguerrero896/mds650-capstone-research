"""Write the target-blind FMP B1Q documentation-review artifact."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mds650.fmp_b1q_exogenous_docs_review_v1 import (  # noqa: E402
    write_fmp_b1q_exogenous_docs_review_v1,
)

DEFAULT_OUTPUT = (
    ROOT / "artifacts" / "provider_timing_v21" / "fmp_b1q_exogenous_docs_review_v1_20260812.json"
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the sole local output path without provider or secret options."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Write or verify the immutable documentation-only review artifact."""
    args = parse_args(argv)
    write_fmp_b1q_exogenous_docs_review_v1(args.output)
    print("FMP_B1Q_EXOGENOUS_DOCS_REVIEW_WRITTEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
