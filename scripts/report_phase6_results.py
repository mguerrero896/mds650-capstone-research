"""Report the frozen Phase 6 OOS results exactly once after replication."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import polars as pl

from mds650.phase6_evaluation import evaluate_phase6
from mds650.study_design import canonical_sha256

ROOT = Path(__file__).resolve().parents[1]
PHASE6 = ROOT / "artifacts" / "phase6"
METHOD_PATH = PHASE6 / "method_freeze.json"
PREDICTIONS_PATH = PHASE6 / "oos_predictions.parquet"
SENSITIVITY_PATH = PHASE6 / "oos_sensitivity_predictions.parquet"
REPLICATION_PATH = PHASE6 / "replication_manifest.json"
ACCESS_LEDGER_PATH = PHASE6 / "oos_access_ledger.json"
RESULTS_PATH = PHASE6 / "results.json"
STABILITY_PATH = PHASE6 / "stability_results.parquet"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"PHASE6_JSON_OBJECT_REQUIRED:{path.name}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> None:
    """Validate frozen inputs, compute every registered view and seal the result."""
    if RESULTS_PATH.exists() or STABILITY_PATH.exists():
        raise RuntimeError("PHASE6_RESULTS_ALREADY_EXIST")
    method = _read_json(METHOD_PATH)
    replication = _read_json(REPLICATION_PATH)
    ledger = _read_json(ACCESS_LEDGER_PATH)
    if (
        method.get("manifest_sha256")
        != canonical_sha256(
            {key: value for key, value in method.items() if key != "manifest_sha256"}
        )
        or replication.get("manifest_sha256")
        != canonical_sha256(
            {
                key: value
                for key, value in replication.items()
                if key != "manifest_sha256"
            }
        )
        or replication.get("status") != "OOS_EVALUATION_COMPLETE_UNREPORTED"
        or replication.get("results_inspected") is not False
        or replication.get("predictions_sha256") != _sha256(PREDICTIONS_PATH)
        or replication.get("sensitivity_predictions_sha256")
        != _sha256(SENSITIVITY_PATH)
        or ledger.get("status") != "OOS_CONSUMED_RESULTS_UNREPORTED"
        or ledger.get("oos_read_count") != 1
        or ledger.get("results_inspected") is not False
    ):
        raise RuntimeError("PHASE6_REPORT_INPUT_INVALID")

    evaluated = evaluate_phase6(
        pl.read_parquet(PREDICTIONS_PATH),
        method,
        timing_predictions=pl.read_parquet(SENSITIVITY_PATH),
    )
    stability = pl.DataFrame(evaluated.pop("stability"), infer_schema_length=None)
    stability.write_parquet(STABILITY_PATH, compression="zstd")
    result = {
        "schema_version": "phase6-results-1.0",
        "status": "PASS_REGISTERED_EVALUATION_COMPLETE",
        **evaluated,
        "stability_row_count": stability.height,
        "stability_results_sha256": _sha256(STABILITY_PATH),
        "replication_manifest_sha256": replication["manifest_sha256"],
        "method_freeze_sha256": method["manifest_sha256"],
        "oos_read_count": 1,
        "all_signs_retained": True,
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
    }
    result["manifest_sha256"] = canonical_sha256(result)
    _write_json(RESULTS_PATH, result)
    reported = {
        **{
            key: value
            for key, value in ledger.items()
            if key != "manifest_sha256"
        },
        "status": "OOS_CONSUMED_RESULTS_REPORTED",
        "results_inspected": True,
        "results_sha256": _sha256(RESULTS_PATH),
        "stability_results_sha256": _sha256(STABILITY_PATH),
        "decision": result["decision"],
    }
    reported["manifest_sha256"] = canonical_sha256(reported)
    _write_json(ACCESS_LEDGER_PATH, reported)
    print(json.dumps({"decision": result["decision"], "status": result["status"]}))


if __name__ == "__main__":
    main()
