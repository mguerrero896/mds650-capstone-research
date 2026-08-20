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


def build_payload(run_dir: Path, *, branch: str, supersedes: str | None) -> dict[str, Any]:
    """Assemble what the transaction needs, from the run's own manifest and artifacts."""

    manifest = _read(run_dir / "run_manifest.json")
    scorecard = _read(run_dir / "scorecard.json")
    ladder = _read(run_dir / "rp2_block8_ladder" / "ladder.json")
    run_id = str(manifest["run_id"])

    artifacts = manifest.get("steps", [])
    inputs = [
        {
            "input_name": name,
            "path": f"artifacts/rp2_v3/{run_id}/{name}",
            "provider": DERIVED,
            "sha256": digest,
            "bytes": (run_dir / name).stat().st_size,
            "rows": None,
            "schema_sha256": None,
            "time_min": None,
            "time_max": None,
        }
        for step in artifacts
        for name, digest in step.get("artifacts", {}).items()
        if (run_dir / name).is_file()
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
            "common_mask_sha256": scorecard["forecast"]["gamma_glm"]["D"]["common_mask_sha256"],
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
