"""Materialize the independent-replication evidence without rereading targets."""

# ruff: noqa: E501

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "artifacts" / "independent_replication"
DATA_ROOT = Path("D:/MDS650/independent_replication_30")
RESULTS = ARTIFACT / "independent_results.json"
STABILITY = ARTIFACT / "stability.parquet"
EVIDENCE_INDEX = ARTIFACT / "evidence_index.csv"
REPORT = ROOT / "docs" / "independent_replication_30_session_results.md"


def _sha256(path: Path) -> str:
    """Return the SHA-256 digest of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    """Read and validate a JSON object."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"INDEPENDENT_REPORT_JSON_OBJECT_REQUIRED:{path}")
    return payload


def _write_text(path: Path, content: str) -> None:
    """Write text atomically and create the parent directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _format_number(value: Any) -> str:
    """Format a numeric report value without hiding nulls."""
    if value is None:
        return "—"
    number = float(value)
    if abs(number) < 0.001 and number != 0:
        return f"{number:.3e}"
    return f"{number:.6f}"


def _format_p(value: Any) -> str:
    """Format a p-value for a human-readable table."""
    if value is None:
        return "—"
    return f"{float(value):.4f}"


def _table(headers: list[str], rows: list[list[str]]) -> str:
    """Render a small deterministic Markdown table."""
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


def _validate_results(results: dict[str, Any]) -> None:
    """Fail closed if the report would misrepresent the frozen evaluation."""
    required = {
        "status": "INDEPENDENT_REPLICATION_COMPLETE",
        "target": "RV30",
        "target_read_count": 1,
    }
    for key, expected in required.items():
        if results.get(key) != expected:
            raise RuntimeError(f"INDEPENDENT_REPORT_RESULT_GATE:{key}")
    evaluation = results.get("evaluation")
    if not isinstance(evaluation, dict) or evaluation.get("all_signs_retained") is not True:
        raise RuntimeError("INDEPENDENT_REPORT_ALL_SIGNS_NOT_RETAINED")
    if not results.get("mde_comparison"):
        raise RuntimeError("INDEPENDENT_REPORT_MDE_MISSING")


def _stability_frame(results: dict[str, Any]) -> pl.DataFrame:
    """Flatten asset, time, regime and hour stability rows into one artifact."""
    evaluation = results["evaluation"]
    rows: list[dict[str, Any]] = []
    for scope, key in (("strata", "stability"), ("hour", "hour_stability")):
        values = evaluation.get(key, [])
        if not isinstance(values, list):
            raise RuntimeError(f"INDEPENDENT_REPORT_STABILITY_LIST_REQUIRED:{key}")
        for row in values:
            if not isinstance(row, dict):
                raise RuntimeError(f"INDEPENDENT_REPORT_STABILITY_ROW_REQUIRED:{key}")
            rows.append(
                {
                    "analysis_scope": scope,
                    "model_role": row.get("model_role"),
                    "contrast": row.get("contrast"),
                    "dimension": row.get("dimension"),
                    "stratum": str(row.get("value")),
                    "estimate": row.get("estimate"),
                    "ci_low": row.get("ci_low"),
                    "ci_high": row.get("ci_high"),
                    "p_value_raw": row.get("p_value_raw"),
                    "p_value_holm": row.get("p_value_holm"),
                    "observations": row.get("observations"),
                    "clusters": row.get("clusters"),
                    "result_sign": row.get("result_sign"),
                    "baseline_mean_qlike": row.get("baseline_mean_qlike"),
                    "expanded_mean_qlike": row.get("expanded_mean_qlike"),
                    "repetitions": row.get("repetitions"),
                    "seed": row.get("seed"),
                    "definition": row.get("definition"),
                }
            )
    if not rows:
        raise RuntimeError("INDEPENDENT_REPORT_STABILITY_EMPTY")
    return pl.from_dicts(rows, infer_schema_length=None).sort(
        ["analysis_scope", "model_role", "contrast", "dimension", "stratum"]
    )


def _evidence_path(path: Path) -> tuple[str, str]:
    """Return a sanitized alias and storage class without exposing user paths."""
    if path.is_relative_to(ROOT):
        return path.relative_to(ROOT).as_posix(), "repository"
    if path.is_relative_to(DATA_ROOT):
        return "MDS650_DATA_ROOT/" + path.relative_to(DATA_ROOT).as_posix(), "D"
    raise RuntimeError(f"INDEPENDENT_REPORT_UNSAFE_PATH:{path}")


def _build_evidence_rows() -> list[dict[str, Any]]:
    """Hash the small evidence set and retained derived outputs."""
    repository_paths = [
        ("results", RESULTS),
        ("acquisition_manifest", ARTIFACT / "acquisition_manifest.json"),
        ("target_acquisition_summary", ARTIFACT / "target_acquisition_summary_v1.json"),
        ("b2_manifest", ARTIFACT / "b2_manifest.json"),
        ("target_access_ledger", ARTIFACT / "target_access_ledger.json"),
        ("method_freeze", ARTIFACT / "method_freeze.json"),
        ("parameter_freeze", ARTIFACT / "parameter_freeze.json"),
        ("panel_manifest", ARTIFACT / "independent_panel_manifest.json"),
        (
            "evaluation_incident",
            ARTIFACT / "evaluation_incidents" / "20260811_bootstrap_contract.json",
        ),
        (
            "acquisition_incident",
            ARTIFACT / "acquisition_incidents" / "2025-04-04_crc_failure.json",
        ),
        (
            "development_model_comparison",
            ROOT / "artifacts/methodology/development_model_comparison.json",
        ),
        ("development_contrasts", ROOT / "artifacts/methodology/development_contrasts_v2.json"),
        ("development_report", ROOT / "docs/model_and_mde_comparison_v2.md"),
        ("development_stability_report", ROOT / "docs/development_stability_audit_v2.md"),
        ("execution_contract", ROOT / "docs/independent_replication_execution.md"),
        ("stability_flattened", STABILITY),
        ("test_report", ARTIFACT / "test_report.txt"),
        ("human_report", REPORT),
    ]
    external_paths = [
        ("predictions", DATA_ROOT / "derived/independent_predictions.parquet"),
        ("timing_predictions", DATA_ROOT / "derived/independent_timing_predictions.parquet"),
        ("common_panel", DATA_ROOT / "derived/common_panel_90d.parquet"),
        ("common_complete_panel", DATA_ROOT / "derived/common_complete_90d.parquet"),
    ]
    rows: list[dict[str, Any]] = []
    for category, path in repository_paths + external_paths:
        if not path.is_file():
            raise RuntimeError(f"INDEPENDENT_REPORT_EVIDENCE_MISSING:{path}")
        alias, storage = _evidence_path(path)
        rows.append(
            {
                "artifact": alias,
                "category": category,
                "storage": storage,
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
                "secrets_emitted": False,
                "personal_paths_emitted": False,
            }
        )
    return sorted(rows, key=lambda row: (str(row["category"]), str(row["artifact"])))


def _write_evidence_index(rows: list[dict[str, Any]]) -> None:
    """Write a deterministic, sanitized CSV evidence index."""
    EVIDENCE_INDEX.parent.mkdir(parents=True, exist_ok=True)
    temporary = EVIDENCE_INDEX.with_suffix(EVIDENCE_INDEX.suffix + ".part")
    fields = [
        "artifact",
        "category",
        "storage",
        "bytes",
        "sha256",
        "secrets_emitted",
        "personal_paths_emitted",
    ]
    with temporary.open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(EVIDENCE_INDEX)


def _development_table(results: dict[str, Any]) -> str:
    """Render the preregistered development model comparison."""
    source = _read_json(ROOT / "artifacts/methodology/development_model_comparison.json")
    by_model: dict[str, dict[str, dict[str, Any]]] = {}
    for row in source["contrasts"]:
        by_model.setdefault(row["model_name"], {})[row["contrast"]] = row
    order = ["persistence", "har_rv", "ridge", "gamma_glm", "lightgbm"]
    rows: list[list[str]] = []
    for model in order:
        b1 = by_model[model]["delta_b1"]
        b2 = by_model[model]["delta_b2"]
        rows.append(
            [
                model,
                _format_number(b1["estimate"])
                + f" [{_format_number(b1['ci_low'])}, {_format_number(b1['ci_high'])}]",
                _format_p(b1.get("p_value_holm_within_model_family")),
                _format_number(b2["estimate"])
                + f" [{_format_number(b2['ci_low'])}, {_format_number(b2['ci_high'])}]",
                _format_p(b2.get("p_value_holm_within_model_family")),
                str(b2["result_sign"]),
            ]
        )
    return _table(
        ["Modelo", "Δ B1 (IC 95%)", "Holm p", "Δ B2 (IC 95%)", "Holm p", "Signo B2"], rows
    )


def _global_table(results: dict[str, Any]) -> str:
    """Render global nested contrasts and frozen MDE comparison."""
    rows: list[list[str]] = []
    for role, contrasts in results["evaluation"]["global"].items():
        for contrast_name in ("delta_b1v2", "delta_b2v2"):
            row = contrasts[contrast_name]
            mde = results["mde_comparison"][role][contrast_name]
            rows.append(
                [
                    role,
                    contrast_name,
                    _format_number(row["estimate"]),
                    f"[{_format_number(row['ci_low'])}, {_format_number(row['ci_high'])}]",
                    _format_p(row.get("p_value_holm")),
                    _format_number(mde["mde"]),
                    "YES" if mde["exceeds_mde"] else "NO",
                    row["result_sign"],
                ]
            )
    return _table(
        ["Rol", "Contraste", "Estimación", "IC 95%", "Holm p", "MDE", "Supera MDE", "Signo"],
        rows,
    )


def _stability_table(results: dict[str, Any], dimension: str, role: str) -> str:
    """Render one stability dimension for the B2 contrast."""
    rows: list[list[str]] = []
    for row in results["evaluation"]["stability"]:
        if (
            row["dimension"] == dimension
            and row["model_role"] == role
            and row["contrast"] == "delta_b2v2"
        ):
            rows.append(
                [
                    str(row["value"]),
                    _format_number(row["estimate"]),
                    f"[{_format_number(row['ci_low'])}, {_format_number(row['ci_high'])}]",
                    _format_p(row.get("p_value_raw")),
                    row["result_sign"],
                ]
            )
    rows.sort(key=lambda row: row[0])
    return _table(["Estrato", "Δ B2", "IC 95%", "p", "Signo"], rows) if rows else "Sin filas."


def _hour_table(results: dict[str, Any]) -> str:
    """Render all registered New York-hour B2 contrasts."""
    rows: list[list[str]] = []
    for row in results["evaluation"]["hour_stability"]:
        if row["contrast"] != "delta_b2v2":
            continue
        rows.append(
            [
                row["model_role"],
                str(row["value"]),
                _format_number(row["estimate"]),
                f"[{_format_number(row['ci_low'])}, {_format_number(row['ci_high'])}]",
                _format_p(row.get("p_value_raw")),
                row["result_sign"],
            ]
        )
    rows.sort(key=lambda row: (row[0], int(row[1])))
    return _table(["Rol", "Hora NY", "Δ B2", "IC 95%", "p", "Signo"], rows)


def _timing_table(results: dict[str, Any]) -> str:
    """Render all registered timing-sensitivity B2 contrasts."""
    rows: list[list[str]] = []
    for row in results["evaluation"]["timing"]:
        if row["contrast"] != "delta_b2v2":
            continue
        rows.append(
            [
                row["model_role"],
                row["timing_variant"],
                _format_number(row["estimate"]),
                f"[{_format_number(row['ci_low'])}, {_format_number(row['ci_high'])}]",
                _format_p(row.get("p_value_raw")),
                row["result_sign"],
            ]
        )
    rows.sort(key=lambda row: (row[0], row[1]))
    return _table(["Rol", "Sensibilidad", "Δ B2", "IC 95%", "p", "Signo"], rows)


def _calibration_table(results: dict[str, Any]) -> str:
    """Render calibration diagnostics without selecting a model."""
    rows: list[list[str]] = []
    for row in results["evaluation"]["calibration"]:
        rows.append(
            [
                row["model_role"],
                row["information_set"],
                _format_number(row["mean_actual"]),
                _format_number(row["mean_forecast"]),
                _format_number(row["mean_forecast_minus_actual"]),
                _format_number(row["median_actual_to_forecast"]),
            ]
        )
    return _table(
        [
            "Rol",
            "Información",
            "RV30 media",
            "Pronóstico medio",
            "Sesgo medio",
            "Mediana real/pronóstico",
        ],
        rows,
    )


def _render_report(
    results: dict[str, Any], acquisition: dict[str, Any], summary: dict[str, Any]
) -> str:
    """Render the evidence-first human report from frozen JSON inputs."""
    target = summary["target_body_acquisition"]
    incident = acquisition.get("excluded_provider_sessions", [])
    gamma_b2 = results["evaluation"]["global"]["gamma_glm_confirmatory"]["delta_b2v2"]
    lgbm_b2 = results["evaluation"]["global"]["lightgbm_robustness"]["delta_b2v2"]
    lines = [
        "# Independent 30-Session Replication — RV30 B2",
        "",
        "> Evidence generated from frozen manifests and `independent_results.json`; no target reread or network request is performed by this report.",
        "",
        "## Executive conclusion",
        "",
        "The preregistered Gamma GLM confirms a positive global B1-to-B2 QLIKE contrast that exceeds the training-only MDE. The LightGBM robustness challenger has the opposite sign and remains below its MDE. Therefore the replication supports a **model-dependent B2 signal**, not a universal or trading-profitability claim.",
        "",
        f"- Registered decision: `{results['decision']}`.",
        f"- Gamma B2 contrast: {_format_number(gamma_b2['estimate'])} (IC 95% {_format_number(gamma_b2['ci_low'])} to {_format_number(gamma_b2['ci_high'])}).",
        f"- LightGBM B2 contrast: {_format_number(lgbm_b2['estimate'])} (IC 95% {_format_number(lgbm_b2['ci_low'])} to {_format_number(lgbm_b2['ci_high'])}).",
        "- All positive, negative and null variants remain registered; no model was selected after inspecting the target outcome.",
        "",
        "## 1. Acquisition and provider incident",
        "",
        f"- Target dates: `{target['date_start']}` through `{target['date_end']}`; {target['completed_sessions']}/{target['expected_sessions']} target sessions present.",
        f"- Target responses: HTTP {target['http_statuses'][0]}, one schema fingerprint, {target['duplicate_event_ids_total']} duplicate event IDs.",
        f"- Target rows: {target['rows_seen_total']:,} seen and {target['rows_retained_total']:,} retained; raw {target['raw_bytes_total']:,} bytes; Parquet {target['parquet_bytes_total']:,} bytes.",
        f"- Warm-up status: `{acquisition.get('status')}` with explicit provider exclusion `{', '.join(incident) if incident else 'none'}`.",
        "- The excluded warm-up archive is not represented as a no-event session and was not imputed; it is retained as a provider incident.",
        "- Historical file availability is proven for the downloaded target dates only; Range metadata alone does not prove independent publication-time semantics for `created_at`.",
        "",
        "## 2. Frozen protocol",
        "",
        "- Target: RV30, using the fully observed origin close plus 30 future one-minute closes (31 prices and 30 log returns).",
        "- Information sets: B0v2, B1v2a and B2v2; B2 primary cutoff `created_at <= forecast_origin - 60 seconds`.",
        "- Primary loss: QLIKE; MAE and RMSE are descriptive only.",
        "- Roles: Gamma GLM confirmatory; LightGBM robustness challenger.",
        "- Inference: 10,000 paired bootstrap repetitions by XNYS session date with all assets kept together; Holm multiplicity control.",
        "- Target access ledger: one read; no new tuning after acquisition; 30-minute purge/embargo retained.",
        "",
        "## 3. Development-only model comparison",
        "",
        "The development panel contains 15,548 common origins over 80 sessions. The MDE is a training-only planning quantity estimated from outer-fold daily effects; it is not an economic hurdle and was not tuned on independent outcomes.",
        "",
        _development_table(results),
        "",
        "Elastic Net remains registered as a possible extension but was not fitted in this gate; adding it after seeing independent outcomes would violate the freeze.",
        "",
        "## 4. Independent global contrasts and MDE",
        "",
        f"The independent target contains {results['primary_origin_count']:,} origins and {results['primary_forecast_row_count']:,} paired forecast rows.",
        "",
        _global_table(results),
        "",
        "Positive Δ means the richer information set has lower QLIKE. Statistical significance and exceeding the frozen MDE are separate criteria.",
        "",
        "## 5. Stability by asset",
        "",
        "### Gamma GLM — B2",
        "",
        _stability_table(results, "asset", "gamma_glm_confirmatory"),
        "",
        "### LightGBM — B2",
        "",
        _stability_table(results, "asset", "lightgbm_robustness"),
        "",
        "## 6. Stability by session tercile and volatility regime",
        "",
        "### Gamma GLM — session tercile",
        "",
        _stability_table(results, "session_tercile", "gamma_glm_confirmatory"),
        "",
        "### LightGBM — session tercile",
        "",
        _stability_table(results, "session_tercile", "lightgbm_robustness"),
        "",
        "### Gamma GLM — volatility regime",
        "",
        _stability_table(results, "volatility_regime", "gamma_glm_confirmatory"),
        "",
        "### LightGBM — volatility regime",
        "",
        _stability_table(results, "volatility_regime", "lightgbm_robustness"),
        "",
        "## 7. Stability by New York hour",
        "",
        _hour_table(results),
        "",
        "## 8. Timing sensitivities",
        "",
        "The Gamma B2 sign remains positive under the registered FMP delay and UW latency/window variants. LightGBM remains heterogeneous; these are sensitivity results, not a new selection rule.",
        "",
        _timing_table(results),
        "",
        "## 9. Calibration diagnostics",
        "",
        _calibration_table(results),
        "",
        "Calibration rows are descriptive and do not authorize recalibration after target inspection.",
        "",
        "## 10. Limitations and decision",
        "",
        "- The provider incident removes one warm-up date; the missing date is explicit and not imputed.",
        "- `created_at` is an operational availability proxy, not demonstrated publication time or evidence of trader intent.",
        "- The positive Gamma result is not reproduced by LightGBM; the evidence does not establish a model-independent global edge.",
        "- No profitability, execution, transaction-cost or capital-readiness claim is made.",
        "- RL and deep learning are outside this frozen evaluation and would require a new preregistration and a distinct justification.",
        "",
        "## Evidence paths",
        "",
        "- Results: `artifacts/independent_replication/independent_results.json`.",
        "- Flattened stability: `artifacts/independent_replication/stability.parquet`.",
        "- Sanitized evidence index: `artifacts/independent_replication/evidence_index.csv`.",
        "- Acquisition incident: `artifacts/independent_replication/acquisition_incidents/2025-04-04_crc_failure.json`.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    """Generate the report, stability artifact and sanitized evidence index."""
    results = _read_json(RESULTS)
    acquisition = _read_json(ARTIFACT / "acquisition_manifest.json")
    summary = _read_json(ARTIFACT / "target_acquisition_summary_v1.json")
    _validate_results(results)
    stability = _stability_frame(results)
    STABILITY.parent.mkdir(parents=True, exist_ok=True)
    stability.write_parquet(STABILITY, compression="zstd")
    _write_text(REPORT, _render_report(results, acquisition, summary))
    _write_evidence_index(_build_evidence_rows())
    print(
        json.dumps(
            {
                "status": "PASS_INDEPENDENT_REPLICATION_REPORT",
                "stability_rows": stability.height,
                "report": str(REPORT.relative_to(ROOT)).replace("\\", "/"),
                "evidence_index": str(EVIDENCE_INDEX.relative_to(ROOT)).replace("\\", "/"),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
