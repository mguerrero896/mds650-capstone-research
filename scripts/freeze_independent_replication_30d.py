"""Freeze the independent replication method before reading target outcomes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "artifacts" / "independent_replication"
WINDOW = ARTIFACT / "window_manifest.json"
OUT = ARTIFACT / "method_freeze.json"


def _sha(path: Path) -> str:
    """Return a SHA-256 hash for one file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load(path: Path) -> dict[str, Any]:
    """Load one JSON object."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path.name}")
    return payload


def main() -> None:
    """Write the immutable method contract for one independent evaluation."""
    window = _load(WINDOW)
    if window.get("status") != "READY_FOR_BOUNDED_BODY_ACQUISITION":
        raise RuntimeError("REPLICATION_WINDOW_NOT_READY_FOR_METHOD_FREEZE")
    payload: dict[str, Any] = {
        "schema_version": "b2-independent-replication-method-freeze-1.0",
        "status": "FROZEN_BEFORE_TARGET_OUTCOME_READ",
        "target": {"name": "RV30", "horizon_minutes": 30, "price_count": 31, "return_count": 30},
        "information_sets": ["B0v2", "B1v2a", "B2v2"],
        "model_roles": {
            "confirmatory": "gamma_glm_confirmatory",
            "robustness": "lightgbm_robustness",
        },
        "primary_metric": "QLIKE",
        "descriptive_metrics": ["MAE", "RMSE"],
        "inference": {
            "bootstrap": "paired_by_XNYS_session_date_with_all_assets",
            "repetitions": 10000,
            "multiplicity": "Holm",
            "mde_source": "training_only_frozen_before_target_outcome",
        },
        "timing": {
            "b2_cutoff": "created_at <= forecast_origin - 60 seconds",
            "purge_embargo_minutes": 30,
            "natural_prevalence": True,
        },
        "warmup_count": window["warmup_count"],
        "target_count": window["target_count"],
        "target_outcome_read": False,
        "no_new_tuning_after_acquisition": True,
        "source_hashes": {
            "window_manifest": _sha(WINDOW),
            "phase6_method_freeze": _sha(ROOT / "artifacts" / "phase6" / "method_freeze.json"),
            "phase6_training_mde": _sha(
                ROOT / "artifacts" / "phase6" / "training_mde_variant_ledger.json"
            ),
            "lockfile": _sha(ROOT / "uv.lock"),
        },
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
    }
    payload["manifest_sha256"] = hashlib.sha256(
        json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    OUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": payload["status"],
                "target_outcome_read": False,
                "secret_values_emitted": False,
            }
        )
    )


if __name__ == "__main__":
    main()
