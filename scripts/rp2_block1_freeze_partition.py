"""Block 1 — freeze the discovery/validation/confirmation partition (Research Program v2).

Enumerates every locally available point-in-time option-trade session, assigns the
frozen ``D < V < C`` roles, and writes a hash-frozen partition artifact.  The sealed
confirmation cohort is recorded from its protocol document and never enumerated.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from mds650.b1v3_confirmation import canonical_sha256
from mds650.rp2.partition import (
    DEFAULT_DATA_ROOT,
    SEALED_CONFIRMATION,
    TAPE_SOURCES,
    discover_sessions,
    inventory_digest,
    role_summary,
    temporal_ordering_holds,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "artifacts" / "rp2_block1_partition"


def build_document(data_root: Path) -> dict[str, object]:
    """Assemble the frozen partition document for one data root."""

    files = discover_sessions(TAPE_SOURCES, data_root)
    if not files:
        raise SystemExit(f"RP2_BLOCK1_NO_SESSIONS_FOUND under {data_root}")
    ordering_ok = temporal_ordering_holds(files)
    summary = role_summary(files)
    sealed = asdict(SEALED_CONFIRMATION)
    sealed["first_session"] = SEALED_CONFIRMATION.first_session.isoformat()
    sealed["last_session"] = SEALED_CONFIRMATION.last_session.isoformat()
    body: dict[str, object] = {
        "block": 1,
        "program": "docs/research_program_v2.md",
        "label": "EXPLORATORY_MECHANISM_DISCOVERY",
        "data_root": data_root.as_posix(),
        "sources": [source.name for source in TAPE_SOURCES],
        "roles": summary,
        "sealed_confirmation": sealed,
        "temporal_ordering_D_lt_V_lt_C": ordering_ok,
        "inventory_sha256": inventory_digest(files),
        "inventory_rows": len(files),
    }
    body["partition_sha256"] = canonical_sha256(body)
    return body


def write_artifacts(document: dict[str, object], output_dir: Path, data_root: Path) -> None:
    """Persist the partition document plus the per-file inventory."""

    output_dir.mkdir(parents=True, exist_ok=True)
    document = dict(document)
    document["generated_at_utc"] = datetime.now(UTC).isoformat()
    (output_dir / "partition.json").write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    rows = [item.as_row() for item in discover_sessions(TAPE_SOURCES, data_root)]
    with (output_dir / "inventory.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    document = build_document(args.data_root)
    write_artifacts(document, args.output_dir, args.data_root)
    print(json.dumps({k: v for k, v in document.items() if k != "roles"}, indent=2))
    roles = document["roles"]
    assert isinstance(roles, dict)
    for role, stats in roles.items():
        print(f"{role}: {stats}")
    return 0 if document["temporal_ordering_D_lt_V_lt_C"] else 1


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
