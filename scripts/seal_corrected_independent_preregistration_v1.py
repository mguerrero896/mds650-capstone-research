"""Freeze corrected independent B1 and authorize one fixed reevaluation."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import polars as pl

from mds650.independent_corrected_reevaluation_v1 import (
    audit_corrected_b1,
    build_preregistration,
)
from mds650.study_design import canonical_sha256

ROOT = Path(__file__).resolve().parents[1]
DATA = Path("D:/MDS650/independent_replication_30/derived")
ARTIFACT = ROOT / "artifacts" / "independent_replication_pit_v2"
OUTPUT = ARTIFACT / "preregistration.json"
ORIGINS = DATA / "origins_90d.parquet"
ATTEMPTS = DATA / "b1_pit_v2" / "iv_attempts_90d_pit_v2.parquet"
FEATURES = DATA / "b1_pit_v2" / "b1v2a_90d_pit_v2.parquet"


def _sha(path: Path) -> str:
    """Return byte SHA-256 for one file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _b2_activity_bundle_hash() -> str:
    """Bind every cached B2 timing-sensitivity partition by relative path."""
    root = DATA / "b2_activity"
    members = {
        path.relative_to(root).as_posix(): _sha(path)
        for path in sorted(root.glob("*/*.parquet"))
    }
    if not members:
        raise RuntimeError("CORRECTED_PREREG_B2_ACTIVITY_MISSING")
    return canonical_sha256(members)


def _input_hashes() -> dict[str, str]:
    """Return hashes for every analytical input used by the corrected run."""
    paths = {
        "corrected_b1_attempts": ATTEMPTS,
        "corrected_b1_features": FEATURES,
        "origins": ORIGINS,
        "underlying_bars": DATA / "underlying_1min_90d.parquet",
        "b0_warmup": DATA / "b0_warmup_60d.parquet",
        "target_b0": DATA / "b0_target_30d.parquet",
        "b2_primary": DATA / "b2_primary_90d.parquet",
        "window_manifest": ROOT / "artifacts/independent_replication/window_manifest.json",
        "method_freeze": ROOT / "artifacts/independent_replication/method_freeze.json",
        "parameter_freeze": ROOT / "artifacts/independent_replication/parameter_freeze.json",
        "target_access_ledger": ROOT
        / "artifacts/independent_replication/target_access_ledger.json",
        "acquisition_manifest": ROOT
        / "artifacts/independent_replication/acquisition_manifest.json",
        "fmp_manifest": ROOT / "artifacts/independent_replication/fmp_manifest.json",
        "b2_manifest": ROOT / "artifacts/independent_replication/b2_manifest.json",
        "b1_repair_manifest": ROOT
        / "artifacts/independent_replication/b1_pit_v2_manifest.json",
        "phase6_training_mde": ROOT / "artifacts/phase6/method_freeze.json",
    }
    missing = [name for name, path in paths.items() if not path.is_file()]
    if missing:
        raise RuntimeError(f"CORRECTED_PREREG_INPUT_MISSING:{','.join(missing)}")
    return {
        **{name: _sha(path) for name, path in paths.items()},
        "b2_activity_bundle": _b2_activity_bundle_hash(),
    }


def _source_hashes() -> dict[str, str]:
    """Return hashes for the frozen code and environment lock."""
    paths = {
        "evaluation_runner": ROOT / "scripts/run_corrected_independent_replication.py",
        "legacy_evaluation_core": ROOT / "scripts/run_independent_replication.py",
        "preregistration_sealer": Path(__file__),
        "b1_repair_builder": ROOT / "scripts/build_independent_b1.py",
        "phase6_features": ROOT / "src/mds650/phase6.py",
        "phase6_evaluation": ROOT / "src/mds650/phase6_evaluation.py",
        "modeling": ROOT / "src/mds650/modeling.py",
        "lockfile": ROOT / "uv.lock",
    }
    missing = [name for name, path in paths.items() if not path.is_file()]
    if missing:
        raise RuntimeError(f"CORRECTED_PREREG_SOURCE_MISSING:{','.join(missing)}")
    return {name: _sha(path) for name, path in paths.items()}


def seal(source_commit: str) -> dict[str, Any]:
    """Validate target-blind B1 and write an immutable preregistration."""
    origins = pl.read_parquet(ORIGINS)
    features = pl.read_parquet(FEATURES)
    attempts = pl.read_parquet(ATTEMPTS)
    audit = audit_corrected_b1(origins=origins, features=features, attempts=attempts)
    preregistration = build_preregistration(
        b1_audit=audit,
        input_hashes=_input_hashes(),
        source_hashes=_source_hashes(),
        source_commit=source_commit,
    )
    encoded = json.dumps(preregistration, indent=2, sort_keys=True) + "\n"
    if OUTPUT.exists():
        if OUTPUT.read_text(encoding="utf-8") != encoded:
            raise RuntimeError("CORRECTED_PREREG_CONFLICT")
        return preregistration
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(".json.part")
    temporary.write_text(encoded, encoding="utf-8")
    temporary.replace(OUTPUT)
    return preregistration


def main() -> None:
    """Seal the corrected independent preregistration from CLI."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    payload = seal(args.source_commit)
    print(
        json.dumps(
            {
                "status": payload["status"],
                "preregistration_sha256": payload["preregistration_sha256"],
                "origin_count": payload["b1_audit"]["origin_count"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
