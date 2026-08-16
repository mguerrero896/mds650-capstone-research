"""Create the final Phase 6 evidence index and evidence-first handoff."""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from mds650.study_design import canonical_sha256

ROOT = Path(__file__).resolve().parents[1]
PHASE6 = ROOT / "artifacts" / "phase6"
REPORT_PATH = ROOT / "reports" / "CODEX_PHASE6_FINAL_HANDOFF.md"
INDEX_PATH = PHASE6 / "evidence_index.csv"
REQUIRED = (
    "preregistration.json",
    "origins.parquet",
    "fmp_manifest.json",
    "b0v2.parquet",
    "b0v2_sensitivities.parquet",
    "b0v2_manifest.json",
    "b1v2.parquet",
    "b1v2_coverage.json",
    "b2v2.parquet",
    "b2v2_sensitivities.parquet",
    "b2v2_manifest.json",
    "common_panel.parquet",
    "common_panel_manifest.json",
    "method_freeze.json",
    "training_mde_oof_forecasts.parquet",
    "oos_predictions.parquet",
    "oos_sensitivity_predictions.parquet",
    "oos_variant_ledger.json",
    "replication_manifest.json",
    "results.json",
    "stability_results.parquet",
    "oos_access_ledger.json",
    "test_report.txt",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json(name: str) -> dict[str, Any]:
    payload = json.loads((PHASE6 / name).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"PHASE6_JSON_OBJECT_REQUIRED:{name}")
    return payload


def _contrast_line(name: str, row: dict[str, Any]) -> str:
    return (
        f"- `{name}`: estimate={float(row['estimate']):.10g}, "
        f"95% CI=[{float(row['ci_low']):.10g}, {float(row['ci_high']):.10g}], "
        f"p_raw={float(row['p_value_raw']):.6g}, "
        f"p_Holm={float(row.get('p_value_holm', float('nan'))):.6g}."
    )


def main() -> None:
    """Fail closed unless every required final artifact exists and is coherent."""
    missing = [name for name in REQUIRED if not (PHASE6 / name).is_file()]
    if missing:
        raise RuntimeError(f"PHASE6_FINAL_EVIDENCE_MISSING:{','.join(missing)}")
    results = _json("results.json")
    ledger = _json("oos_access_ledger.json")
    b1 = _json("b1v2_coverage.json")
    common = _json("common_panel_manifest.json")
    method = _json("method_freeze.json")
    if (
        results.get("manifest_sha256")
        != canonical_sha256(
            {key: value for key, value in results.items() if key != "manifest_sha256"}
        )
        or results.get("status") != "PASS_REGISTERED_EVALUATION_COMPLETE"
        or ledger.get("status") != "OOS_CONSUMED_RESULTS_REPORTED"
        or ledger.get("oos_read_count") != 1
        or ledger.get("results_sha256") != _sha256(PHASE6 / "results.json")
        or b1.get("status") != "PASS_B1V2A_COVERAGE"
        or common.get("status") != "SEALED_BEFORE_OOS"
    ):
        raise RuntimeError("PHASE6_FINAL_EVIDENCE_INVALID")

    rows = [
        {
            "path": f"artifacts/phase6/{name}",
            "bytes": (PHASE6 / name).stat().st_size,
            "sha256": _sha256(PHASE6 / name),
        }
        for name in REQUIRED
    ]
    with INDEX_PATH.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=("path", "bytes", "sha256"))
        writer.writeheader()
        writer.writerows(rows)

    gamma = results["global"]["gamma_glm_confirmatory"]
    challenger = results["global"]["lightgbm_robustness"]
    branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    report = "\n".join(
        (
            "# CODEX PHASE 6 FINAL HANDOFF",
            "",
            f"**Decision:** `{results['decision']}`  ",
            f"**Branch:** `{branch}`  ",
            f"**Base commit:** `{commit}`  ",
            "**Target:** RV30 (31 prices, 30 one-minute log returns).",
            "",
            "## Confirmatory Gamma QLIKE contrasts",
            "",
            _contrast_line("Delta_B1v2 = QLIKE(B0v2)-QLIKE(B1v2a)", gamma["delta_b1v2"]),
            _contrast_line("Delta_B2v2 = QLIKE(B1v2a)-QLIKE(B2v2)", gamma["delta_b2v2"]),
            "",
            "## LightGBM robustness contrasts",
            "",
            _contrast_line("Delta_B1v2", challenger["delta_b1v2"]),
            _contrast_line("Delta_B2v2", challenger["delta_b2v2"]),
            "",
            "## Frozen MDE and confirmation status",
            "",
            f"- Delta_B1v2 MDE: {float(method['training_mde']['delta_b1v2']):.10g}.",
            f"- Delta_B2v2 MDE: {float(method['training_mde']['delta_b2v2']):.10g}.",
            "- Global confirmed contrasts: "
            + (", ".join(results["confirmed_contrasts"]) or "none")
            + ".",
            "- Positive confidence intervals alone do not satisfy the frozen MDE rule.",
            "",
            "## Scientific controls",
            "",
            f"- Common-panel origins: {common['common_origin_count']}.",
            f"- B1v2a global coverage: {float(b1['global']['b1v2a']):.2%}.",
            f"- OOS reads: {ledger['oos_read_count']}.",
            f"- All signs retained: {results['all_signs_retained']}.",
            f"- Stability rows: {results['stability_row_count']}.",
            "- No result-driven feature, asset, model or timing redesign was performed.",
            "",
            "## Evidence",
            "",
            "See `artifacts/phase6/evidence_index.csv` and `artifacts/phase6/test_report.txt`.",
            "",
        )
    )
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(json.dumps({"decision": results["decision"], "evidence_files": len(rows)}))


if __name__ == "__main__":
    main()
