"""Validate a local FMP timing replay; no live provider request is implemented."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from mds650.provider_timing import summarize_fmp_bar_replay


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse a fixture/replay-only FMP timing probe command."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay", type=Path, required=True, help="Local JSONL replay input.")
    parser.add_argument("--output", type=Path, required=True, help="Sanitized JSON output.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run a local replay validation and write a non-blocking probe status.

    Parameters
    ----------
    argv:
        Optional explicit command arguments.

    Returns
    -------
    int
        Zero after a local replay is validated and serialized.
    """
    args = parse_args(argv)
    records = _read_jsonl(args.replay)
    result = summarize_fmp_bar_replay(records)
    _write_json(args.output, result)
    return 0


def _read_jsonl(path: Path) -> list[Mapping[str, object]]:
    """Read object-only JSON Lines from a local replay fixture."""
    records: list[Mapping[str, object]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        parsed: Any = json.loads(line)
        if not isinstance(parsed, dict):
            raise ValueError(f"FMP_REPLAY_ROW_NOT_OBJECT:{number}")
        records.append(parsed)
    return records


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Write formatted, atomic and sanitized replay output."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
