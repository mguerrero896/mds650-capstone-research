"""Populate the RP2 block register in Supabase from the artifacts on disk.

The register carries `artifact_sha256` and `run_id` columns and every row held NULL in both:
the migration that added them had no writer, so the table asserted provenance it did not
have. A NULL there is worse than an absent column — it looks like the field is supported.

This reads each block's result document, takes the digest the block itself computed, takes
the run id from the `provenance.json` sidecar beside it, and upserts. Aggregates only: no
licensed provider value passes through, because nothing here reads a panel.

Run:  $env:SUPABASE_SERVICE_KEY set, then
      uv run python scripts/sync_supabase_rp2_blocks.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx

REPO = Path(__file__).resolve().parents[1]
PROJECT_REF = "eqpyjikcewqaegnbaemf"
#: The rebuild these artifacts came from. Recorded rather than taken from the wall clock so a
#: re-sync of the same artifacts does not invent a second run time for them.
STAMPED_AT = "2026-08-19T13:37:19+00:00"
REST = f"https://{PROJECT_REF}.supabase.co/rest/v1"

#: `block_id` -> (artifact file, the key inside it holding that block's own digest).
BLOCK_ARTIFACTS: dict[str, tuple[str, str]] = {
    "03": ("artifacts/rp2_block3_target/comparison.json", "comparison_sha256"),
    "04": ("artifacts/rp2_block4_b0/ladder.json", "b0_sha256"),
    "05": ("artifacts/rp2_block5_surface/surface_coverage.json", "surface_sha256"),
    "06": ("artifacts/rp2_block6_flow/flow_coverage.json", "flow_sha256"),
    "07": ("artifacts/rp2_block7_dml/dml.json", "dml_sha256"),
    "08": ("artifacts/rp2_block8_ladder/ladder.json", "ladder_sha256"),
    "09": ("artifacts/rp2_block9_generalization/generalization.json", "generalization_sha256"),
    "10": ("artifacts/rp2_block10_inference/inference.json", "inference_sha256"),
    "11": ("artifacts/rp2_block11_economics/economics.json", "economics_sha256"),
}

#: Where each block's provenance sidecar lives, when it has one.
SIDECARS: dict[str, str] = {
    "03": "artifacts/rp2_block3_target/provenance.json",
    "04": "artifacts/rp2_block4_b0/provenance.json",
    "05": "artifacts/rp2_block5_surface/provenance.json",
    "06": "artifacts/rp2_block6_flow/provenance.json",
    "07": "artifacts/rp2_block7_dml/provenance.json",
    "08": "artifacts/rp2_block8_ladder/provenance.json",
    "10": "artifacts/rp2_block10_inference/provenance.json",
    "11": "artifacts/rp2_block11_economics/provenance.json",
}


def _digest(block: str) -> str | None:
    relative, key = BLOCK_ARTIFACTS[block]
    path = REPO / relative
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    value = payload.get(key)
    return str(value) if isinstance(value, str) else None


def _run_id(block: str) -> str | None:
    relative = SIDECARS.get(block)
    if relative is None:
        return None
    path = REPO / relative
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    value = payload.get("run_id")
    return str(value) if isinstance(value, str) else None


def rows() -> list[dict[str, Any]]:
    """One row per block whose artifact is present, with what the artifact actually says."""

    out: list[dict[str, Any]] = []
    for block in sorted(BLOCK_ARTIFACTS):
        digest = _digest(block)
        if digest is None:
            continue
        out.append({"block_id": block, "artifact_sha256": digest, "run_id": _run_id(block)})
    return out


def run_manifest(run_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The run row and its input rows, assembled from every provenance sidecar.

    A block row may not reference a run that does not exist — the foreign key added with the
    provenance columns enforces that, which is the point of having it. Registering the run
    means registering what it actually read, so the inputs are collected from the sidecars
    rather than asserted.
    """

    inputs: dict[tuple[str, str], dict[str, Any]] = {}
    commit: str | None = None
    inputs_digest: str | None = None
    for relative in SIDECARS.values():
        path = REPO / relative
        if not path.is_file():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("run_id") != run_id:
            continue
        commit = commit or payload.get("code_commit")
        inputs_digest = inputs_digest or payload.get("inputs_sha256")
        for name, record in payload.get("inputs", {}).items():
            # One row per distinct file, keyed on its identity rather than the block that
            # happened to declare it: the same panel feeds several blocks.
            inputs[(str(record["path"]), str(record["sha256"]))] = {
                "run_id": run_id,
                "input_name": name,
                "path": str(record["path"]),
                "provider": str(record["provider"]),
                "sha256": str(record["sha256"]),
                "bytes": int(record["bytes"]),
                "rows": record.get("rows"),
                "schema_sha256": record.get("schema_sha256"),
                "time_min": record.get("time_min"),
                "time_max": record.get("time_max"),
            }
    rows = list(inputs.values())
    run = {
        "run_id": run_id,
        "started_at": STAMPED_AT,
        "completed_at": STAMPED_AT,
        # The register admits RUNNING / PUBLISHED / FAILED / SUPERSEDED and nothing else.
        "status": "PUBLISHED",
        "code_commit": commit,
        "inputs_sha256": inputs_digest,
        "input_count": len(rows),
        "rows_published": 0,
        "note": "RP2-v2 remediation rebuild: blocks 3-11 re-run and provenance-stamped",
    }
    return run, rows


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="rp2v2-remediation")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    payload = rows()
    run, run_inputs = run_manifest(str(args.run_id))
    for row in payload:
        print(f"{row['block_id']}  {row['artifact_sha256'][:16]}  run={row['run_id']}")
    print(f"run {run['run_id']}: {run['input_count']} distinct inputs, commit {run['code_commit']}")
    if args.dry_run:
        print(f"dry run: {len(payload)} block rows and {len(run_inputs)} input rows not sent")
        return 0
    if not payload:
        print("nothing to sync: no block artifact carries a digest")
        return 0

    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not key:
        raise SystemExit("SUPABASE_SERVICE_KEY_MISSING")
    # PATCH, not upsert: the register rows already exist and carry required columns this
    # script has no business inventing. An upsert would insert a stub row for any block_id
    # that had drifted, which is how a provenance sync turns into a data loss.
    updated = 0
    with httpx.Client(
        timeout=30.0, headers={"apikey": key, "Authorization": f"Bearer {key}"}
    ) as client:
        for table, body, conflict in (
            ("ingestion_runs", [run], "run_id"),
            ("ingestion_inputs", run_inputs, "run_id,input_name"),
        ):
            if not body:
                continue
            response = client.post(
                f"{REST}/{table}",
                params={"on_conflict": conflict},
                json=body,
                headers={"Prefer": "resolution=merge-duplicates"},
            )
            if response.status_code >= 400:
                raise SystemExit(
                    f"RP2_RUN_REGISTER_REJECTED:{table}:{response.status_code}:{response.text}"
                )
        for row in payload:
            block = row.pop("block_id")
            response = client.patch(
                f"{REST}/rp2_blocks",
                params={"block_id": f"eq.{block}"},
                json=row,
                headers={"Prefer": "return=representation"},
            )
            if response.status_code >= 400:
                # PostgREST names the offending column in the body; a bare 400 says nothing.
                raise SystemExit(
                    f"RP2_BLOCK_SYNC_REJECTED:{block}:{response.status_code}:{response.text}"
                )
            if not response.json():
                print(f"skipped {block}: no such row in the register")
                continue
            updated += 1
    print(f"synced {updated} block rows")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
