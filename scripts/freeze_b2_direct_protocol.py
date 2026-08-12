"""Freeze the direct B2 protocol before any new independent acquisition."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from mds650.development_models import B0_FEATURES, B1_FEATURES, B2_FEATURES
from mds650.study_design import canonical_sha256

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "methodology" / "b2_direct_protocol_freeze_v1.json"
DOC = ROOT / "docs" / "b2_direct_protocol_freeze_v1.md"
PREREG = ROOT / "artifacts" / "methodology" / "b2_mechanism_search_preregistration.json"
DEVELOPMENT = ROOT / "artifacts" / "methodology" / "development_model_comparison.json"
RESIDUAL_RESULTS = ROOT / "artifacts" / "methodology" / "b2_mechanism_results.json"
METHOD_FREEZE = ROOT / "artifacts" / "phase6" / "method_freeze.json"


def _sha256(path: Path) -> str:
    """Hash one local evidence file without emitting its contents."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest() -> dict[str, Any]:
    """Build a direct-B2 freeze manifest without reading independent outcomes."""
    required = (PREREG, DEVELOPMENT, RESIDUAL_RESULTS, METHOD_FREEZE)
    missing = [path.name for path in required if not path.exists()]
    if missing:
        raise RuntimeError(f"B2_FREEZE_SOURCE_MISSING:{','.join(missing)}")
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    development = json.loads(DEVELOPMENT.read_text(encoding="utf-8"))
    residual = json.loads(RESIDUAL_RESULTS.read_text(encoding="utf-8"))
    mde = float(prereg["inference"]["mde"])
    retained = list(development.get("retained_b2_candidates_by_development_rule", []))
    if "gamma_glm" not in retained:
        raise RuntimeError("B2_FREEZE_GAMMA_NOT_DEVELOPMENT_RETAINED")
    if residual.get("oos_read_count") != 0 or residual.get("independent_samples_read"):
        raise RuntimeError("B2_FREEZE_RESIDUAL_OOS_READ_DETECTED")
    manifest: dict[str, Any] = {
        "schema_version": "b2-direct-protocol-freeze-1.0",
        "status": "FROZEN_DIRECT_B2_BEFORE_NEW_BLOCK_ACQUISITION",
        "selection_source": [
            "artifacts/methodology/development_model_comparison.json",
            "artifacts/methodology/b2_mechanism_results.json",
        ],
        "selection_sample": {
            "panel": "artifacts/phase5/common_development_80d.parquet",
            "session_count": 80,
            "date_start": "2026-03-24",
            "date_end": "2026-07-17",
            "independent_samples_read": False,
        },
        "information_sets": {
            "B0": list(B0_FEATURES),
            "B1": list(B1_FEATURES),
            "B2": list(B2_FEATURES),
            "B2_increment_only": [name for name in B2_FEATURES if name not in B1_FEATURES],
        },
        "models": {
            "confirmatory": "gamma_glm",
            "robustness": "lightgbm",
            "registered_challengers": ["har_rv", "ridge", "elastic_net"],
        },
        "timing": {
            "b2_primary_window_minutes": 5,
            "uw_created_at_cutoff": "forecast_origin - 60 seconds",
            "fmp_available_at": "timestamp_raw + 1 minute",
            "quote_and_event_fields_must_be_at_or_before_origin": True,
        },
        "inference": {
            "primary_metric": "QLIKE",
            "definition": "QLIKE(B1)-QLIKE(B2_direct)",
            "bootstrap_unit": "XNYS_SESSION_DATE_WITH_ALL_ASSETS",
            "bootstrap_repetitions": int(prereg["inference"]["bootstrap_repetitions"]),
            "multiple_comparisons": "Holm",
            "mde": mde,
            "seed": int(prereg["inference"]["seed"]),
        },
        "residual_learner": {
            "implemented": True,
            "development_status": "NO_VARIANT_RETAINED",
            "result_artifact": "artifacts/methodology/b2_mechanism_results.json",
            "reason": (
                "Raw signed residual corrections hit the forecast floor under unstable "
                "Gamma B1 outliers."
            ),
        },
        "new_blocks": {
            "minimum_sessions_per_block": int(prereg["oos_guard"]["minimum_sessions_per_block"]),
            "required_blocks": int(prereg["oos_guard"]["new_blocks_required_after_freeze"]),
            "must_be_disjoint_from_all_observed_samples": True,
            "download_started": False,
        },
        "source_hashes": {path.name: _sha256(path) for path in required},
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
    }
    manifest["manifest_sha256"] = canonical_sha256(manifest)
    return manifest


def main() -> None:
    """Write the immutable direct-B2 freeze manifest and human-readable note."""
    if OUT.exists():
        raise RuntimeError("B2_FREEZE_ALREADY_EXISTS")
    manifest = build_manifest()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    DOC.parent.mkdir(parents=True, exist_ok=True)
    DOC.write_text(
        "# B2 direct protocol freeze v1\n\n"
        "Status: `FROZEN_DIRECT_B2_BEFORE_NEW_BLOCK_ACQUISITION`.\n\n"
        "The confirmatory protocol is direct B2 augmentation of B1 with Gamma GLM; "
        "LightGBM is a pre-registered robustness challenger. The residual learner was "
        "implemented and evaluated, but no residual variant passed the development gate.\n\n"
        "No independent outcomes were read to select this protocol. New blocks must be "
        "metadata-probed first, then downloaded once, and remain disjoint from every "
        "previously observed outcome sample.\n\n"
        "Manifest: `artifacts/methodology/b2_direct_protocol_freeze_v1.json`.\n",
        encoding="utf-8",
    )
    print(
        json.dumps({"status": manifest["status"], "manifest_sha256": manifest["manifest_sha256"]})
    )


if __name__ == "__main__":
    main()
