"""Compare two RP2-v3 scorecards field by field and say what moved.

The plan asks for a before/after table. Writing one by hand invites the two columns to come
from different places, so this reads both scorecards and reports every field that differs,
including the ones that did not.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def flatten(payload: Any, prefix: str = "") -> dict[str, Any]:
    """Every leaf of a scorecard, keyed by its dotted path."""

    flat: dict[str, Any] = {}
    if isinstance(payload, dict):
        for key, value in payload.items():
            flat.update(flatten(value, f"{prefix}.{key}" if prefix else str(key)))
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            flat.update(flatten(value, f"{prefix}[{index}]"))
    else:
        flat[prefix] = payload
    return flat


#: Fields that record when or how long, not what. They differ between any two runs.
VOLATILE = ("runtime_seconds", "peak_memory_bytes", "run_id", "generated_at")


def compare(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    """Every field of either scorecard, with what it was and what it became."""

    old, new = flatten(before), flatten(after)
    rows: list[dict[str, Any]] = []
    for key in sorted(set(old) | set(new)):
        if any(volatile in key for volatile in VOLATILE):
            continue
        was, now = old.get(key), new.get(key)
        moved = was != now
        if isinstance(was, float) and isinstance(now, float):
            moved = not math.isclose(was, now, rel_tol=1e-12, abs_tol=0.0)
        rows.append({"field": key, "before": was, "after": now, "moved": moved})
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--only-moved", action="store_true")
    args = parser.parse_args(argv)

    rows = compare(
        json.loads(args.before.read_text(encoding="utf-8")),
        json.loads(args.after.read_text(encoding="utf-8")),
    )
    moved = [row for row in rows if row["moved"]]
    for row in moved if args.only_moved else rows:
        mark = "*" if row["moved"] else " "
        print(f"{mark} {row['field']:<52} {row['before']!r:>26} -> {row['after']!r}")
    print(f"\n{len(moved)} of {len(rows)} comparable fields moved")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
