"""Stamp every Research Program v2 artifact with the provenance of its inputs.

An artifact that hashes only its own result document proves the document was not edited
afterwards. It says nothing about the file the numbers came from, which is the thing a
reader actually needs in order to reproduce or refute them: two runs over different data
produce documents that are equally well-hashed.

This writes a `provenance.json` sidecar beside each block artifact recording, per input,
the byte SHA-256, the schema digest, the row count, the time span and the provider.
`--verify` re-hashes and names what drifted, which is the only way a stale artifact
announces itself.

Two classes of input are treated differently, on purpose:

* **Derived panels** are hashed byte for byte. They are this repository's own output and
  hashing them is affordable.
* **The licensed raw option tape** is pinned by the partition inventory, which lists every
  file path and its size and is itself hashed byte for byte. Content-hashing the tape means
  reading tens of gigabytes on every run. The weaker guarantee is recorded as such in the
  sidecar rather than presented as a byte hash.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from mds650.rp2.provenance import (
    InputRecord,
    describe_input,
    provenance_block,
    verify_inputs,
)

ROOT = Path(__file__).resolve().parents[1]

#: Every block artifact directory, with the inputs that produced it and how each is read.
#: `(name, relative path, provider, time column)`.
BLOCK_INPUTS: dict[str, tuple[tuple[str, str, str, str | None], ...]] = {
    # Block 4 reads the raw bar sources directly rather than block 3's panel, so its
    # provenance is the bar inventory, not a derived artifact.
    "rp2_block3_target": (
        ("bar_inventory", "artifacts/rp2_block1_partition/inventory.jsonl", "massive", None),
    ),
    "rp2_block4_b0": (
        ("bar_inventory", "artifacts/rp2_block1_partition/inventory.jsonl", "massive", None),
    ),
    "rp2_block5_surface": (
        ("b0_panel", "artifacts/rp2_block4_b0/b0_panel.parquet", "derived", "session_date"),
        ("tape_inventory", "artifacts/rp2_block1_partition/inventory.jsonl", "massive", None),
    ),
    "rp2_block6_flow": (
        ("b0_panel", "artifacts/rp2_block4_b0/b0_panel.parquet", "derived", "session_date"),
        ("tape_inventory", "artifacts/rp2_block1_partition/inventory.jsonl", "massive", None),
    ),
    "rp2_block7_dml": (
        ("b0_panel", "artifacts/rp2_block4_b0/b0_panel.parquet", "derived", "session_date"),
        (
            "b1_panel",
            "artifacts/rp2_block5_surface/b1_surface_panel.parquet",
            "derived",
            "session_date",
        ),
        ("b2_panel", "artifacts/rp2_block6_flow/b2_flow_panel.parquet", "derived", "session_date"),
    ),
    "rp2_block8_ladder": (
        ("b0_panel", "artifacts/rp2_block4_b0/b0_panel.parquet", "derived", "session_date"),
        (
            "b1_panel",
            "artifacts/rp2_block5_surface/b1_surface_panel.parquet",
            "derived",
            "session_date",
        ),
        ("b2_panel", "artifacts/rp2_block6_flow/b2_flow_panel.parquet", "derived", "session_date"),
    ),
    "rp2_block10_inference": (
        ("b0_panel", "artifacts/rp2_block4_b0/b0_panel.parquet", "derived", "session_date"),
        (
            "b1_panel",
            "artifacts/rp2_block5_surface/b1_surface_panel.parquet",
            "derived",
            "session_date",
        ),
        ("b2_panel", "artifacts/rp2_block6_flow/b2_flow_panel.parquet", "derived", "session_date"),
    ),
    "rp2_block11_economics": (
        ("b0_panel", "artifacts/rp2_block4_b0/b0_panel.parquet", "derived", "session_date"),
        (
            "b1_panel",
            "artifacts/rp2_block5_surface/b1_surface_panel.parquet",
            "derived",
            "session_date",
        ),
        ("b2_panel", "artifacts/rp2_block6_flow/b2_flow_panel.parquet", "derived", "session_date"),
    ),
}

#: Inputs pinned by a listing rather than by content, and why.
INDIRECT: dict[str, str] = {
    "bar_inventory": (
        "the licensed minute bars are pinned by this inventory's path and size listing, "
        "which is itself byte-hashed; content-hashing them means reading tens of "
        "gigabytes per run"
    ),
    "tape_inventory": (
        "the licensed option tape is pinned by this inventory's path and size listing, "
        "which is itself byte-hashed; content-hashing the tape means reading tens of "
        "gigabytes per run"
    ),
}


def code_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
        )
    except (subprocess.CalledProcessError, OSError):
        return None
    return result.stdout.strip() or None


def collect(block: str) -> dict[str, InputRecord]:
    """Describe every declared input of one block, failing closed on a missing file."""

    records: dict[str, InputRecord] = {}
    for name, relative, provider, time_column in BLOCK_INPUTS[block]:
        records[name] = describe_input(ROOT / relative, provider=provider, time_column=time_column)
    return records


def stamp(block: str, *, run_id: str) -> Path:
    directory = ROOT / "artifacts" / block
    directory.mkdir(parents=True, exist_ok=True)
    records = collect(block)
    payload = provenance_block(records, run_id=run_id, code_commit=code_commit())
    payload["indirect_inputs"] = {
        name: reason for name, reason in INDIRECT.items() if name in records
    }
    target = directory / "provenance.json"
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def verify(block: str) -> list[str]:
    """Names of inputs whose bytes no longer match what the sidecar recorded."""

    sidecar = ROOT / "artifacts" / block / "provenance.json"
    if not sidecar.is_file():
        return [f"{block}:NO_PROVENANCE"]
    stored = json.loads(sidecar.read_text(encoding="utf-8"))["inputs"]
    records = {name: _record(entry) for name, entry in stored.items()}
    return [f"{block}:{name}" for name in verify_inputs(records)]


def _record(entry: dict[str, Any]) -> InputRecord:
    """Rebuild a record from JSON, where the column tuple round-trips as a list."""

    columns = entry.get("columns")
    return InputRecord(
        path=str(entry["path"]),
        provider=str(entry["provider"]),
        sha256=str(entry["sha256"]),
        bytes=int(entry["bytes"]),
        rows=entry.get("rows"),
        columns=None if columns is None else tuple(str(name) for name in columns),
        schema_sha256=entry.get("schema_sha256"),
        time_column=entry.get("time_column"),
        time_min=entry.get("time_min"),
        time_max=entry.get("time_max"),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="rp2v2-remediation")
    parser.add_argument("--verify", action="store_true", help="re-hash instead of writing")
    parser.add_argument("--blocks", default=",".join(BLOCK_INPUTS))
    args = parser.parse_args(argv)

    blocks = [name.strip() for name in str(args.blocks).split(",") if name.strip()]
    unknown = [name for name in blocks if name not in BLOCK_INPUTS]
    if unknown:
        raise SystemExit(f"RP2_PROVENANCE_UNKNOWN_BLOCK:{unknown}")

    if args.verify:
        drifted = [entry for block in blocks for entry in verify(block)]
        for entry in drifted:
            print(f"DRIFTED {entry}")
        if drifted:
            raise SystemExit("RP2_PROVENANCE_DRIFT")
        print(f"verified {len(blocks)} blocks: every recorded input is byte-identical")
        return 0

    for block in blocks:
        directory = ROOT / "artifacts" / block
        if not directory.is_dir():
            print(f"skipped {block}: not built yet")
            continue
        try:
            target = stamp(block, run_id=str(args.run_id))
        except FileNotFoundError as error:
            print(f"skipped {block}: {error}")
            continue
        print(f"stamped {target.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
