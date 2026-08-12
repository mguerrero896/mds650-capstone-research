"""Freeze independent-replication model parameters before target access."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from mds650.study_design import canonical_sha256

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "artifacts" / "independent_replication"
OOS_LEDGER = ROOT / "artifacts" / "phase6" / "oos_variant_ledger.json"
METHOD_FREEZE = ARTIFACT / "method_freeze.json"
OUT = ARTIFACT / "parameter_freeze.json"


def _sha(path: Path) -> str:
    """Return the SHA-256 digest of a local artifact."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json(path: Path) -> dict[str, Any]:
    """Read one JSON object."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path.name}")
    return payload


def main() -> None:
    """Persist the predeclared first-development-fold parameter contract."""
    method = _json(METHOD_FREEZE)
    ledger = _json(OOS_LEDGER)
    unsigned_ledger = {key: value for key, value in ledger.items() if key != "manifest_sha256"}
    if ledger.get("manifest_sha256") != canonical_sha256(unsigned_ledger):
        raise RuntimeError("PHASE6_VARIANT_LEDGER_HASH_INVALID")
    if method.get("status") != "FROZEN_BEFORE_TARGET_OUTCOME_READ":
        raise RuntimeError("INDEPENDENT_METHOD_FREEZE_INVALID")
    selected = [
        row
        for row in ledger.get("selected_variants", [])
        if isinstance(row, dict) and int(row.get("fold", -1)) == 1
    ]
    required = {
        (information_set, role)
        for information_set in ("B0v2", "B1v2a", "B2v2")
        for role in ("gamma_glm_confirmatory", "lightgbm_robustness")
    }
    observed = {(str(row.get("information_set")), str(row.get("model_role"))) for row in selected}
    if observed != required:
        raise RuntimeError("PHASE6_FOLD1_PARAMETER_SET_INCOMPLETE")
    parameters = {
        f"{row['information_set']}:{row['model_role']}": row["parameters"]
        for row in sorted(
            selected,
            key=lambda item: (str(item["information_set"]), str(item["model_role"])),
        )
    }
    payload: dict[str, Any] = {
        "schema_version": "b2-independent-replication-parameter-freeze-1.0",
        "status": "FROZEN_BEFORE_INDEPENDENT_TARGET_OUTCOME_READ",
        "selection_rule": "PHASE6_FOLD_1_SELECTED_VARIANT_BY_INFORMATION_SET_AND_ROLE",
        "no_new_tuning_after_acquisition": True,
        "parameters": parameters,
        "target_outcome_read": False,
        "source_hashes": {
            "method_freeze": _sha(METHOD_FREEZE),
            "phase6_oos_variant_ledger": _sha(OOS_LEDGER),
        },
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
    }
    payload["manifest_sha256"] = canonical_sha256(payload)
    OUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "target_outcome_read": False}))


if __name__ == "__main__":
    main()
