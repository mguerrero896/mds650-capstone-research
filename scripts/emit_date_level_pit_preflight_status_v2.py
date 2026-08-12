"""Emit the current no-network date-level PIT-preflight v2 status record."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

from mds650.date_level_pit_preflight_status_v2 import (  # noqa: E402
    emit_current_date_level_pit_status_v2,
)


def _parse_args() -> argparse.Namespace:
    """Parse only versioned metadata paths and a commit identity."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--immutable-plan",
        type=Path,
        default=_ROOT / "artifacts" / "preflight" / "date_level_pit_preflight_plan_v1.json",
    )
    parser.add_argument(
        "--endpoint-catalog",
        type=Path,
        default=_ROOT / "config" / "date_level_pit_preflight_endpoint_catalog_v2.json",
    )
    parser.add_argument(
        "--request-budget",
        type=Path,
        default=(
            _ROOT / "artifacts" / "preflight" / "date_level_pit_preflight_request_budget_v2.json"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=_ROOT / "artifacts" / "preflight",
    )
    parser.add_argument("--source-commit", required=True)
    return parser.parse_args()


def main() -> int:
    """Emit and print one current status path without any provider transport."""
    args = _parse_args()
    output_path = emit_current_date_level_pit_status_v2(
        immutable_plan_path=args.immutable_plan,
        endpoint_catalog_path=args.endpoint_catalog,
        request_budget_path=args.request_budget,
        output_dir=args.output_dir,
        source_commit=args.source_commit,
    )
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
