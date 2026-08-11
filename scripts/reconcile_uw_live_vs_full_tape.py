"""Reconcile locally replayed UW receipts against locally replayed Full Tape rows."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from mds650.provider_timing import reconcile_uw_replay_records


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the strictly local UW replay reconciliation command."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt-replay", type=Path, required=True)
    parser.add_argument("--full-tape-replay", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Compare two local replays and retain the non-live evidence boundary.

    Parameters
    ----------
    argv:
        Optional explicit command arguments.

    Returns
    -------
    int
        Zero after the local reconciliation output is atomically written.
    """
    args = parse_args(argv)
    result = reconcile_uw_replay_records(
        _read_jsonl(args.receipt_replay),
        _read_jsonl(args.full_tape_replay),
    )
    _write_json(args.output, result)
    return 0


def _read_jsonl(path: Path) -> list[Mapping[str, object]]:
    """Read object-only JSON Lines from one local replay file."""
    records: list[Mapping[str, object]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        parsed: Any = json.loads(line)
        if not isinstance(parsed, dict):
            raise ValueError(f"UW_RECONCILIATION_ROW_NOT_OBJECT:{number}")
        records.append(parsed)
    return records


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Write formatted JSON atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
