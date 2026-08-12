"""CLI wrapper for the metadata-only target-blind comparison-contract sealer."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(_REPOSITORY_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT / "src"))

from mds650.target_blind_comparison_contract_v1 import (  # noqa: E402
    seal_target_blind_comparison_contract,
)


def _parse_args() -> argparse.Namespace:
    """Parse only metadata paths and a source commit for this sealed contract."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--preregistration-v4",
        type=Path,
        default=(
            _REPOSITORY_ROOT
            / "artifacts"
            / "target_blind_v24_sourcebound_20260812"
            / "next_confirmation_preregistration_v4.json"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=_REPOSITORY_ROOT / "artifacts" / "target_blind_v25_comparison_contract_20260812",
    )
    parser.add_argument("--source-commit", required=True)
    return parser.parse_args()


def main() -> int:
    """Seal and print only the path of a validated, target-blind contract."""
    args = _parse_args()
    output_path = seal_target_blind_comparison_contract(
        preregistration_v4_path=args.preregistration_v4,
        output_dir=args.output_dir,
        source_commit=args.source_commit,
    )
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
