"""Prepare a date-level PIT preflight report without wiring a real network transport."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mds650.date_level_pit_preflight_v1 import (
    PreflightError,
    load_endpoint_descriptors,
    load_plan,
    render_report,
    run_date_level_pit_preflight,
    write_if_identical,
)

DEFAULT_PLAN = Path("artifacts/preflight/date_level_pit_preflight_plan_v1.json")
DEFAULT_OUTPUT = Path("artifacts/preflight/date_level_pit_preflight_report_v1.json")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--approved-plan-semantic-hash")
    parser.add_argument("--assert-zero-incremental-spend", action="store_true")
    parser.add_argument("--endpoint-descriptors", type=Path)
    args = parser.parse_args()
    try:
        plan = load_plan(args.plan)
        descriptors = (
            load_endpoint_descriptors(args.endpoint_descriptors)
            if args.endpoint_descriptors is not None
            else {}
        )
        report = run_date_level_pit_preflight(
            plan,
            execute=args.execute,
            approved_plan_semantic_hash=args.approved_plan_semantic_hash,
            zero_incremental_spend_asserted=args.assert_zero_incremental_spend,
            endpoint_descriptors=descriptors,
            request_fn=None,
        )
        output_state = write_if_identical(args.output, render_report(report))
    except PreflightError as exc:
        print(json.dumps({"status": "FAILED_CLOSED", "code": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps({"status": report["status"], "output_state": output_state}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
