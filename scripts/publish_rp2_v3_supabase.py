"""Publish one RP2-v3 run to Supabase, atomically, from the artifacts it produced.

The publication is a single call to `public.publish_rp2_v3`, because a function body is a
transaction. Eight REST calls from a script can leave a run marked RUNNING with half its
results published and the previous run already stood down, and nothing in the database
would say which half is missing.

Nothing origin-level is sent. What leaves the repository is the run's identity, the digests
of its inputs, one row per block outcome and one row per nested contrast - the same
aggregates the public report is written from.

    $env:SUPABASE_SERVICE_KEY = "..."
    uv run python scripts/publish_rp2_v3_supabase.py --run-root artifacts/rp2_v3/<run_id>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:  # pragma: no cover - import bootstrap
    sys.path.insert(0, str(ROOT / "src"))

PROJECT_REF = "eqpyjikcewqaegnbaemf"
REST = f"https://{PROJECT_REF}.supabase.co/rest/v1"
SPEC_VERSION = "rp2-v3"
#: Providers the ingestion contract allows. A derived panel is `derived`; anything else
#: has to name the provider whose licence it is held under.
DERIVED = "derived"


def _read(path: Path) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return payload


def contrast_rows(ladder: dict[str, Any], run_id: str) -> list[dict[str, Any]]:
    """One row per nested contrast, per role, per primary family.

    Only the families the research contract decides on are published. The robustness
    families stay in the artifact: a reader who wants them can hash the artifact and read
    it, and a table that mixes deciding and robustness rows invites a later query that
    forgets the difference.
    """

    from mds650.rp2.ladder import PRIMARY_MODELS

    rows: list[dict[str, Any]] = []
    for role in ("D", "V"):
        role_block = ladder.get(role, {})
        if role_block.get("status") != "MEASURED":
            continue
        for family in PRIMARY_MODELS:
            model = role_block.get("models", {}).get(family)
            if not model:
                continue
            for label, contrast in model.get("contrasts", {}).items():
                raw = contrast.get("raw", {})
                if not raw.get("common_mask_sha256"):
                    raise SystemExit(f"RP2_PUBLISH_CONTRAST_WITHOUT_MASK:{role}:{family}:{label}")
                rows.append(
                    {
                        "role": role,
                        "model_family": family,
                        "base_information_set": raw["base_information_set"],
                        "expanded_information_set": raw["expanded_information_set"],
                        "estimate": raw["estimate"],
                        "ci_low": raw["ci_low"],
                        "ci_high": raw["ci_high"],
                        "p_value": raw["p_value"],
                        "sessions": raw["sessions"],
                        "block_length": raw["block_length"],
                        "mde": raw["mde"],
                        "equivalence_bound": raw["equivalence_bound"],
                        "common_mask_sha256": raw["common_mask_sha256"],
                    }
                )
    return rows


def assert_artifacts_match_manifest(run_dir: Path, manifest: dict[str, Any]) -> None:
    """Every artifact this publisher reads is the one the run recorded.

    The manifest is written when the run finishes; the publication happens afterwards. A
    file changed in between would be read and published as though the run had produced it,
    and the digests in the manifest would say otherwise while nobody compared them.
    """

    from mds650.rp2.run_manifest import file_digest

    for step in manifest.get("steps", []):
        for name, digest in step.get("artifacts", {}).items():
            path = run_dir / name
            if not path.is_file():
                raise SystemExit(f"RP2_PUBLISH_ARTIFACT_MISSING:{name}")
            if file_digest(path) != digest:
                raise SystemExit(f"RP2_PUBLISH_ARTIFACT_CHANGED:{name}")


def _mask_digest(scorecard: dict[str, Any]) -> str:
    """One digest identifying the evaluation masks of every role the run fitted.

    A single role's mask under a run-level field says the other role's contrasts were scored
    on rows they never saw. The per-contrast digests remain the authority; this identifies
    the set.
    """

    masks = {
        role: values.get("common_mask_sha256")
        for family in scorecard.get("forecast", {}).values()
        for role, values in family.items()
    }
    if not masks or any(value is None for value in masks.values()):
        raise SystemExit("RP2_PUBLISH_MASK_DIGEST_INCOMPLETE")
    canonical = json.dumps(masks, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_payload(run_dir: Path, *, branch: str, supersedes: str | None) -> dict[str, Any]:
    """Assemble what the transaction needs, from the run's own manifest and artifacts."""

    manifest = _read(run_dir / "run_manifest.json")
    assert_artifacts_match_manifest(run_dir, manifest)
    scorecard = _read(run_dir / "scorecard.json")
    ladder = _read(run_dir / "rp2_block8_ladder" / "ladder.json")
    run_id = str(manifest["run_id"])

    artifacts = manifest.get("steps", [])
    # What the run *read*, from step 1's own record. Populating this from the step outputs
    # described the panels and reports the run produced, so a consumer following
    # `ingestion_inputs` to find out what the results were built on found the results.
    resolved = _read(run_dir / "input_manifest.json")
    inputs = [
        {
            "input_name": "gated_manifest",
            "path": "data/GATED_DATA_POINTERS.json",
            "provider": DERIVED,
            "sha256": resolved["gated_manifest_sha256"],
            "bytes": int(resolved.get("gated_files", 0)) or 1,
            "rows": resolved.get("gated_files"),
            "schema_sha256": None,
            "time_min": None,
            "time_max": None,
        },
        {
            "input_name": "option_tape",
            "path": "artifacts/rp2_block1_partition/inventory.jsonl",
            "provider": DERIVED,
            "sha256": resolved["tape_fingerprint_sha256"],
            "bytes": int(resolved["tape_bytes"]),
            "rows": int(resolved["tape_files"]),
            "schema_sha256": resolved["tape_inventory_sha256"],
            "time_min": None,
            "time_max": None,
        },
        *(
            {
                "input_name": f"bars_{name}",
                "path": f"bars/{name}",
                "provider": "fmp",
                "sha256": digest,
                "bytes": 1,
                "rows": None,
                "schema_sha256": None,
                "time_min": None,
                "time_max": None,
            }
            for name, digest in sorted(resolved.get("bar_sources_sha256", {}).items())
        ),
    ]

    blocks = [
        {
            "block_id": step["name"],
            "status": "MEASURED" if step["exit_code"] == 0 else "FAILED",
            "verdict": "SEE_ARTIFACT",
            "document": "docs/rp2_v3/REBUILD_RUNBOOK.md",
            "artifact_sha256": digest,
            "supersedes_run_id": supersedes,
        }
        for step in artifacts
        for digest in list(step.get("artifacts", {}).values())[:1]
    ]

    return {
        "run": {
            "run_id": run_id,
            "code_commit": manifest["code_commit"],
            "inputs_sha256": manifest["input_manifest_sha256"],
            "spec_version": SPEC_VERSION,
            "branch_name": branch,
            "feature_registry_sha256": manifest["feature_registry_sha256"],
            "model_config_sha256": manifest["model_config_sha256"],
            "inference_config_sha256": manifest["scientific_sha256"],
            # A digest over every role's mask, not one role's. The run-level field used to
            # carry D's, which attributed the V contrasts to rows they were never scored
            # on; each contrast row still carries its own.
            "common_mask_sha256": _mask_digest(scorecard),
            "note": f"RP2-v3 rebuild, scientific hash {manifest['scientific_sha256'][:16]}",
        },
        "inputs": inputs,
        "blocks": blocks,
        "contrasts": contrast_rows(ladder, run_id),
    }


def publish(payload: dict[str, Any], key: str, *, timeout: float = 120.0) -> dict[str, Any]:
    """One call, one transaction. A failure is recorded by a separate call, not by a retry."""

    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=timeout, headers=headers) as client:
        response = client.post(f"{REST}/rpc/publish_rp2_v3", json={"payload": payload})
        if response.status_code not in (200, 201):
            client.post(
                f"{REST}/rpc/record_rp2_v3_failure",
                json={
                    "failed_run_id": payload["run"]["run_id"],
                    "reason": response.text[:400],
                },
            )
            raise SystemExit(f"RP2_PUBLISH_FAILED:{response.status_code}:{response.text[:300]}")
        return dict(response.json())


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--branch", default="results/rp2-v3-rebuild")
    parser.add_argument("--supersedes", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    payload = build_payload(args.run_root, branch=args.branch, supersedes=args.supersedes)
    if args.dry_run:
        print(json.dumps(payload, indent=2, sort_keys=True)[:4000])
        print(
            f"[dry-run] {len(payload['inputs'])} inputs, {len(payload['blocks'])} blocks, "
            f"{len(payload['contrasts'])} contrasts"
        )
        return 0

    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not key:
        raise SystemExit("SUPABASE_SERVICE_KEY missing (User env var; see DATA_ACCESS.md).")
    result = publish(payload, key)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
