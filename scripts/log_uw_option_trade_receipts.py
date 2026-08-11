"""Build sanitized Unusual Whales receipt logs from a local replay only."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from mds650.provider_timing import build_uw_receipt_record


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse a fixture/replay-only UW receipt-log command."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay", type=Path, required=True, help="Local source JSONL replay.")
    parser.add_argument(
        "--output", type=Path, required=True, help="Sanitized receipt JSONL output."
    )
    parser.add_argument(
        "--received-at-utc",
        default=None,
        help="Fallback receipt time when a replay row has no received_at_utc field.",
    )
    parser.add_argument("--source", default="unusual_whales_replay")
    parser.add_argument("--connection-type", default="replay")
    parser.add_argument("--local-clock-offset", default="+00:00")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Emit sanitized receipt records for a local replay, never a live feed.

    Parameters
    ----------
    argv:
        Optional explicit command arguments.

    Returns
    -------
    int
        Zero after every replay line has produced one receipt record.
    """
    args = parse_args(argv)
    output_records: list[dict[str, object]] = []
    for number, message in enumerate(_read_jsonl(args.replay), start=1):
        received_at = message.get("received_at_utc", args.received_at_utc)
        if not isinstance(received_at, str) or not received_at:
            raise ValueError(f"UW_RECEIPT_TIME_REQUIRED:{number}")
        output_records.append(
            build_uw_receipt_record(
                message,
                received_at_utc=received_at,
                source=args.source,
                connection_type=args.connection_type,
                local_clock_offset=args.local_clock_offset,
            )
        )
    _write_jsonl(args.output, output_records)
    return 0


def _read_jsonl(path: Path) -> list[Mapping[str, object]]:
    """Read object-only JSON Lines from a local replay fixture."""
    records: list[Mapping[str, object]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        parsed: Any = json.loads(line)
        if not isinstance(parsed, dict):
            raise ValueError(f"UW_REPLAY_ROW_NOT_OBJECT:{number}")
        records.append(parsed)
    return records


def _write_jsonl(path: Path, records: Sequence[Mapping[str, object]]) -> None:
    """Write sanitized JSON Lines atomically without retaining raw source payloads."""
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = "".join(
        json.dumps(record, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
        for record in records
    )
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(serialized, encoding="utf-8")
    temporary.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
