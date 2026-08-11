# ruff: noqa: E501
"""Render a portable, evidence-bound defense package from canonical RV30 artifacts.

The renderer deliberately consumes compact sanitized canonical evidence rather than raw
commercial data.  It neither fits a model nor calls a provider.  Its output is a reusable
report, presentation outline, tables and SVG figures for the approved capstone documents.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import io
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

_ARTIFACT_ROOT = "artifacts/canonical_validation_v1"
_EXPECTED_ELIGIBILITY = {
    "delta_b1v2": "MODEL_FAMILY_DEPENDENT",
    "delta_b2v2": "MODEL_FAMILY_DEPENDENT",
}
_REGISTERED_ROLES = ("gamma_glm_confirmatory", "lightgbm_robustness")
_BLOCK_ORDER = {"phase6": 0, "independent_replication": 1}
_ROLE_ORDER = {role: index for index, role in enumerate(_REGISTERED_ROLES)}
_CONTRAST_ORDER = {"delta_b1v2": 0, "delta_b2v2": 1}
_INPUT_FILES = ("report_manifest.json", "contrasts.json")
_OUTPUT_FILES = (
    Path("MDS650_Canonical_RV30_Defense_Report.md"),
    Path("MDS650_Canonical_RV30_Defense_Report.html"),
    Path("MDS650_Canonical_RV30_Defense_Slides.md"),
    Path("tables/canonical_registered_contrasts.csv"),
    Path("figures/canonical_qlike_contrasts.svg"),
    Path("figures/canonical_design_flow.svg"),
)


def _sha256(path: Path) -> str:
    """Return the SHA-256 digest for one regular file.

    Parameters
    ----------
    path
        Existing file to hash.

    Returns
    -------
    str
        Lowercase hexadecimal SHA-256 digest.

    Raises
    ------
    RuntimeError
        If ``path`` is not a regular file.
    """

    if not path.is_file():
        raise RuntimeError("CANONICAL_DEFENSE_INPUT_INVALID")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    """Load one canonical JSON artifact with a fail-closed error code.

    Parameters
    ----------
    path
        JSON artifact to load.

    Returns
    -------
    dict[str, Any]
        Parsed top-level object.

    Raises
    ------
    RuntimeError
        If the file is absent, invalid JSON, or has a non-object top level.
    """

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError("CANONICAL_DEFENSE_INPUT_INVALID") from error
    if not isinstance(payload, dict):
        raise RuntimeError("CANONICAL_DEFENSE_INPUT_INVALID")
    return payload


def _require_mapping(value: object) -> Mapping[str, object]:
    """Return a mapping or reject a malformed canonical artifact."""

    if not isinstance(value, Mapping):
        raise RuntimeError("CANONICAL_DEFENSE_INPUT_INVALID")
    return value


def _require_text(value: object) -> str:
    """Return a required non-empty text field or reject malformed evidence."""

    if not isinstance(value, str) or not value:
        raise RuntimeError("CANONICAL_DEFENSE_INPUT_INVALID")
    return value


def _require_float(value: object) -> float:
    """Return a finite numeric field or reject malformed evidence."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RuntimeError("CANONICAL_DEFENSE_INPUT_INVALID")
    result = float(value)
    if not result == result or result in {float("inf"), float("-inf")}:
        raise RuntimeError("CANONICAL_DEFENSE_INPUT_INVALID")
    return result


def _require_positive_int(value: object) -> int:
    """Return a positive integer count or reject malformed canonical evidence."""

    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise RuntimeError("CANONICAL_DEFENSE_INPUT_INVALID")
    return value


def load_validated_contrasts(source: Path) -> tuple[dict[str, Any], list[dict[str, object]]]:
    """Load registered contrast rows only after validating the canonical contract.

    Parameters
    ----------
    source
        Directory containing ``report_manifest.json`` and ``contrasts.json``.

    Returns
    -------
    tuple[dict[str, Any], list[dict[str, object]]]
        Canonical report manifest and deterministically ordered registered contrast rows.

    Raises
    ------
    RuntimeError
        If canonical source status, pairing, eligibility, or registered rows are invalid.

    Notes
    -----
    This function intentionally excludes post-read extension rows from the primary defense
    table. They are described as diagnostics in the report, not reclassified as confirmation.
    """

    if not source.is_dir():
        raise RuntimeError("CANONICAL_DEFENSE_INPUT_INVALID")
    report_manifest = _load_json(source / "report_manifest.json")
    contrasts_payload = _load_json(source / "contrasts.json")
    if report_manifest.get("status") != "PASS_CANONICAL_REPORT":
        raise RuntimeError("CANONICAL_DEFENSE_INPUT_INVALID")
    if contrasts_payload.get("status") != "PASS":
        raise RuntimeError("CANONICAL_DEFENSE_INPUT_INVALID")
    for payload in (report_manifest, contrasts_payload):
        if payload.get("personal_paths_emitted") is not False:
            raise RuntimeError("CANONICAL_DEFENSE_INPUT_INVALID")
        if payload.get("secret_values_emitted") is not False:
            raise RuntimeError("CANONICAL_DEFENSE_INPUT_INVALID")
    if contrasts_payload.get("all_signs_retained") is not True:
        raise RuntimeError("CANONICAL_DEFENSE_INPUT_INVALID")
    integrity = _require_mapping(contrasts_payload.get("contrast_integrity"))
    if integrity.get("status") != "PASS" or integrity.get("unpaired_rows") != 0:
        raise RuntimeError("CANONICAL_DEFENSE_INPUT_INVALID")
    eligibility = _require_mapping(contrasts_payload.get("claim_eligibility"))
    if dict(eligibility) != _EXPECTED_ELIGIBILITY:
        raise RuntimeError("CANONICAL_DEFENSE_INPUT_INVALID")
    rows_value = contrasts_payload.get("contrasts")
    if not isinstance(rows_value, list):
        raise RuntimeError("CANONICAL_DEFENSE_INPUT_INVALID")

    rows: list[dict[str, object]] = []
    for value in rows_value:
        row = _require_mapping(value)
        role = _require_text(row.get("model_role"))
        if role not in _REGISTERED_ROLES:
            continue
        block = _require_text(row.get("block"))
        contrast = _require_text(row.get("contrast"))
        if block not in _BLOCK_ORDER or contrast not in _CONTRAST_ORDER:
            raise RuntimeError("CANONICAL_DEFENSE_INPUT_INVALID")
        if row.get("registered_status") != "REGISTERED_OOS":
            raise RuntimeError("CANONICAL_DEFENSE_INPUT_INVALID")
        _require_positive_int(row.get("paired_rows"))
        required = (
            "baseline",
            "expanded",
            "definition",
            "result_sign",
            "positive_direction",
            "status",
        )
        for name in required:
            _require_text(row.get(name))
        for name in ("estimate", "ci_low", "ci_high", "mde", "p_value_holm"):
            _require_float(row.get(name))
        rows.append(dict(row))

    rows.sort(
        key=lambda row: (
            _BLOCK_ORDER[str(row["block"])],
            _ROLE_ORDER[str(row["model_role"])],
            _CONTRAST_ORDER[str(row["contrast"])],
        )
    )
    expected = len(_BLOCK_ORDER) * len(_REGISTERED_ROLES) * len(_CONTRAST_ORDER)
    if len(rows) != expected:
        raise RuntimeError("CANONICAL_DEFENSE_INPUT_INVALID")
    return report_manifest, rows


def _format_signed(value: object) -> str:
    """Format one numeric contrast with a stable sign and eight decimal places."""

    return f"{_require_float(value):+.8f}"


def _format_interval(row: Mapping[str, object]) -> str:
    """Format a confidence interval from one validated contrast row."""

    return f"[{_format_signed(row['ci_low'])}, {_format_signed(row['ci_high'])}]"


def _table_float(value: str) -> float:
    """Parse a renderer-owned signed table value for a visual-only bar length."""

    try:
        return float(value)
    except ValueError as error:
        raise RuntimeError("CANONICAL_DEFENSE_OUTPUT_INVALID") from error


def _model_label(role: str) -> str:
    """Return the human-readable registered model name for a stored role."""

    return {
        "gamma_glm_confirmatory": "Gamma generalized linear model (confirmatory)",
        "lightgbm_robustness": "LightGBM nonlinear tree model (robustness)",
    }[role]


def _block_label(block: str) -> str:
    """Return the human-readable label for one validated evidence block."""

    return {
        "phase6": "Phase 6 historical OOS block",
        "independent_replication": "Independent historical replication block",
    }[block]


def _comparison_label(contrast: str) -> str:
    """Return the plain-language name of one nested information comparison."""

    return {
        "delta_b1v2": "B1a ordinary option state versus B0 underlying/market",
        "delta_b2v2": "B2 trade activity versus B1a ordinary option state",
    }[contrast]


def _table_rows(rows: Sequence[Mapping[str, object]]) -> list[dict[str, str]]:
    """Create portable CSV records from registered canonical contrasts."""

    records: list[dict[str, str]] = []
    for row in rows:
        records.append(
            {
                "block": str(row["block"]),
                "block_label": _block_label(str(row["block"])),
                "model_role": str(row["model_role"]),
                "model": _model_label(str(row["model_role"])),
                "contrast": str(row["contrast"]),
                "comparison": _comparison_label(str(row["contrast"])),
                "qlike_delta": _format_signed(row["estimate"]),
                "ci_95": _format_interval(row),
                "holm_p": f"{_require_float(row['p_value_holm']):.8f}",
                "frozen_mde": f"{_require_float(row['mde']):.8f}",
                "mde_met": "yes" if row["mde_pass"] is True else "no",
                "result_sign": str(row["result_sign"]),
                "paired_origins": str(_require_positive_int(row["paired_rows"])),
                "evidence_status": str(row["registered_status"]),
            }
        )
    return records


def _csv_bytes(records: Sequence[Mapping[str, str]]) -> bytes:
    """Return deterministic CSV bytes for registered contrast records."""

    fieldnames = (
        "block",
        "block_label",
        "model_role",
        "model",
        "contrast",
        "comparison",
        "qlike_delta",
        "ci_95",
        "holm_p",
        "frozen_mde",
        "mde_met",
        "result_sign",
        "paired_origins",
        "evidence_status",
    )
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(records)
    return stream.getvalue().encode("utf-8")


def _markdown_result_table(records: Sequence[Mapping[str, str]]) -> str:
    """Render a concise registered-result table in Markdown."""

    lines = [
        "| Evidence block | Model | Comparison | QLIKE delta | 95% interval | Holm p | Frozen MDE met? |",
        "| --- | --- | --- | ---: | --- | ---: | --- |",
    ]
    for row in records:
        lines.append(
            "| {block_label} | {model} | {comparison} | {qlike_delta} | {ci_95} | "
            "{holm_p} | {mde_met} |".format(**row)
        )
    return "\n".join(lines)


def _report_markdown(records: Sequence[Mapping[str, str]]) -> str:
    """Render the complete professor-readable report from registered evidence only."""

    result_table = _markdown_result_table(records)
    return f"""# MDS650 Canonical RV30 Validation — Defense Report

## Executive answer

**Primary research question.** At each five-minute forecast origin, does the ordinary
state of the options market improve a 30-minute realised-variance (RV30) forecast beyond
underlying and market controls, and does trade-derived option activity add further
incremental information?

**Canonical answer.** `MODEL_FAMILY_DEPENDENT` for both comparisons. The study preserves
positive and negative outcomes: the confirmatory Gamma generalized linear model (Gamma GLM)
shows a targeted positive B2 result in the independent block, while the registered LightGBM
robustness model has the opposite B2 sign in that same block. The evidence therefore does not
support an all-model conclusion.

## What one row means

One row is one eligible outcome asset at one five-minute New York Stock Exchange forecast
origin. RV30 uses the fully observed close at the origin and the next thirty consecutive
one-minute closes, producing exactly thirty one-minute log returns. Predictors are available
at or before the origin; missing observations are not interpolated or replaced.

## Information sets and data provenance

- **B0:** point-in-time underlying and market controls.
- **B1a:** B0 plus at-the-money implied volatility from qualifying historical option quotes
  in the 30–60 days-to-expiry bucket. It is an ordinary-option-state benchmark, not a claimed
  full skew or term-structure surface.
- **B2:** B1a plus nine frozen, target-blind option-trade activity features. The conservative
  availability rule is `created_at <= origin - 60 seconds`; this is an operational proxy, not
  a statement about publication time, trader intention, or informed trading.

The data are licensed commercial data rather than a public classroom download. Reproducibility
is addressed through code, fixed study contracts, source hashes, sanitized manifests, exact
origin pairing, and a portable evidence index; licensed raw payloads remain outside Git. A
future date qualifies only after its historical Full Tape availability, hash, market-calendar,
and point-in-time checks pass.

## Why these models were used

Gamma GLM is the registered confirmatory estimator. LightGBM is the pre-registered nonlinear
robustness estimator. HAR-RV, Ridge, and Elastic Net are retained only as post-read fixed
extensions and do not upgrade the registered evidence. A deep neural network is not introduced
because the independent unit is trading day rather than the raw number of overlapping rows;
it would add material model-selection risk without resolving the current disagreement.
Reinforcement learning is not appropriate for this question because it would change RV30
forecasting into a sequential trading-policy problem requiring action, reward, execution-cost,
and risk contracts that are not part of this study.

## Registered out-of-sample results

`QLIKE delta = QLIKE(baseline) - QLIKE(expanded information set)`. A positive value favours
the expanded information set. Confidence intervals use a paired bootstrap clustered by trading
day, with all assets from a day retained together. Holm adjustment applies to the two declared
nested contrasts in each model/block. The minimum detectable effects (MDEs) were frozen before
the relevant out-of-sample outcomes were read.

{result_table}

## What can be said, precisely

- **B1a over B0:** not established as a general improvement. Gamma changes from positive in
  Phase 6 to negative in independent replication. LightGBM is positive in both blocks, but its
  independent interval crosses zero and its gain is below the frozen MDE.
- **B2 over B1a:** a targeted Gamma result exists in the independent block: `+0.03291534`,
  95% interval `[+0.02444358, +0.04162629]`, above the frozen B2 MDE `0.00503510`.
  It is bounded by the adverse independent LightGBM B2 result `-0.00180221`.
- **Scientific status:** the disagreement is informative. It prevents selective reporting and
  identifies the precise condition that a future, newly sealed replication must resolve.

## Quality controls already passed

- Identical B0/B1a/B2 origins within every comparison; canonical unpaired rows: zero.
- Temporal train-before-test audit; minimum retained separation: 1,115 minutes.
- Six outcome assets: AAPL, AMZN, META, MSFT, NVDA, and TSLA. SPY and QQQ are market-control
  inputs, so their absence from outcome rows is a data-role rule rather than performance-based
  asset removal.
- All registered signs, intervals, MDE decisions, and negative robustness findings are retained.

## Supervisor-feedback checklist

| Supervisor concern | Direct response in this package |
| --- | --- |
| Goals and objectives were unclear | The single primary question and row-level target are stated above before any acronym-heavy result. |
| Dataset is not standard/public | The commercial-data boundary, audit trail, and reproducibility mechanism are stated explicitly. |
| Literature feasibility was missing | The verified study matrix and evidence ledger are retained at `docs/literature_matrix.csv` and `docs/literature_evidence_ledger.csv`; they provide recent empirical motivation, not a substitute for this dataset's PIT validation. |
| No baseline was selected | B0, B1a, and B2 are explicit nested information sets, with Gamma GLM and LightGBM registered roles shown above. |

## Limits and next scientific step

This is an RV30 forecast-loss study, not proof of a deployable strategy, causal mechanism, or
trader intent. The next valid strengthening step is a newly sealed replication with the method
frozen before its outcomes are read; it must retain both registered model families and all
outcomes. No new model family, feature redesign, or result-selection rule should be introduced
to manufacture agreement.

## Evidence index

- Canonical result source: `artifacts/canonical_validation_v1/contrasts.json`.
- Source validation: `artifacts/canonical_validation_v1/report_manifest.json`.
- Claims and limitations ledger: `docs/canonical_claims_and_limitations.md`.
- Causal audit: `artifacts/canonical_validation_v1/phase6/causal_audit.parquet` and
  `artifacts/canonical_validation_v1/independent_replication/causal_audit.parquet`.
"""


def _report_html(markdown: str, records: Sequence[Mapping[str, str]]) -> str:
    """Render a dependency-free HTML report with the same textual evidence as Markdown."""

    rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(record['block_label'])}</td>"
        f"<td>{html.escape(record['model'])}</td>"
        f"<td>{html.escape(record['comparison'])}</td>"
        f"<td class=\"numeric\">{html.escape(record['qlike_delta'])}</td>"
        f"<td class=\"numeric\">{html.escape(record['ci_95'])}</td>"
        f"<td class=\"numeric\">{html.escape(record['holm_p'])}</td>"
        f"<td>{html.escape(record['mde_met'])}</td>"
        "</tr>"
        for record in records
    )
    narrative = html.escape(markdown).replace("\n", "<br>\n")
    return f"""<!doctype html>
<html lang=\"en\">
<head>
<meta charset=\"utf-8\">
<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
<title>MDS650 Canonical RV30 Validation — Defense Report</title>
<style>
body {{ font-family: Arial, sans-serif; color: #172033; line-height: 1.48; margin: 2rem auto; max-width: 1120px; padding: 0 1rem; }}
h1, h2 {{ color: #123c69; }}
.decision {{ background: #eef5fb; border-left: .35rem solid #123c69; padding: 1rem; font-weight: 700; }}
table {{ border-collapse: collapse; width: 100%; font-size: .9rem; margin: 1rem 0 2rem; }}
th, td {{ border: 1px solid #c9d3df; padding: .55rem; vertical-align: top; text-align: left; }}
th {{ background: #e8f0f7; }}
.numeric {{ font-variant-numeric: tabular-nums; white-space: nowrap; }}
.source {{ background: #f6f8fa; padding: .9rem; white-space: pre-wrap; }}
</style>
</head>
<body>
<h1>MDS650 Canonical RV30 Validation — Defense Report</h1>
<p class=\"decision\">Canonical decision: MODEL_FAMILY_DEPENDENT. The package keeps every registered positive and negative sign.</p>
<h2>Registered out-of-sample results</h2>
<p>A positive QLIKE delta favours the expanded information set. The table displays only registered Gamma GLM and LightGBM roles.</p>
<table><thead><tr><th>Evidence block</th><th>Model</th><th>Comparison</th><th>QLIKE delta</th><th>95% interval</th><th>Holm p</th><th>Frozen MDE met?</th></tr></thead><tbody>
{rows}
</tbody></table>
<h2>Full evidence-bound narrative</h2>
<div class=\"source\">{narrative}</div>
</body>
</html>
"""


def _slides_markdown(records: Sequence[Mapping[str, str]]) -> str:
    """Render a concise, manually transferable presentation outline."""

    independent_gamma_b2 = next(
        row
        for row in records
        if row["block"] == "independent_replication"
        and row["model_role"] == "gamma_glm_confirmatory"
        and row["contrast"] == "delta_b2v2"
    )
    independent_lgbm_b2 = next(
        row
        for row in records
        if row["block"] == "independent_replication"
        and row["model_role"] == "lightgbm_robustness"
        and row["contrast"] == "delta_b2v2"
    )
    return f"""# MDS650 RV30 — Defense Slide Outline

> Portable outline only. It does not modify the approved PowerPoint source.

## Slide 1 — One question

Can ordinary option state improve a 30-minute realised-variance forecast beyond
underlying/market controls, and can trade-derived activity add further value?

## Slide 2 — What is forecast

- A row = an asset at a five-minute forecast origin.
- RV30 = thirty one-minute log returns from 31 observed minute closes.
- No predictor is allowed after the forecast origin.

## Slide 3 — Three nested information sets

- B0: underlying and market controls.
- B1a: B0 + point-in-time ATM implied volatility.
- B2: B1a + nine target-blind trade-activity features.

## Slide 4 — Why the data are credible but not public

- Licensed historical datasets are retained outside Git.
- Reproducibility comes from hashes, manifests, causal audits, fixed contracts, and portable code.
- Each future Full Tape session requires availability, hash, calendar, and point-in-time validation.

## Slide 5 — Evaluation protocol

- Gamma GLM confirmatory; LightGBM nonlinear robustness.
- Identical origins across B0/B1a/B2.
- QLIKE primary; bootstrap clustered by trading day; Holm adjustment; MDE frozen before outcomes.

## Slide 6 — Registered results

- Independent Gamma B2: {independent_gamma_b2['qlike_delta']} with 95% interval {independent_gamma_b2['ci_95']}; MDE met: {independent_gamma_b2['mde_met']}.
- Independent LightGBM B2: {independent_lgbm_b2['qlike_delta']} with 95% interval {independent_lgbm_b2['ci_95']}; MDE met: {independent_lgbm_b2['mde_met']}.
- Full signed table: `tables/canonical_registered_contrasts.csv`.

## Slide 7 — Correct conclusion

`MODEL_FAMILY_DEPENDENT`: targeted Gamma evidence is not an all-model claim because the
registered LightGBM robustness model disagrees. This is a result to report, not a reason to
remove or replace a model.

## Slide 8 — Boundaries and next step

- No claim of trader intent, causality, or deployable strategy.
- No new DL/RL method is added after outcomes are read.
- A newly sealed replication, with method frozen before target access, is required to test
  whether the disagreement persists.
"""


def _qlike_svg(records: Sequence[Mapping[str, str]]) -> str:
    """Render a standalone signed-bar SVG for all registered contrasts."""

    numeric_values = [_table_float(row["qlike_delta"]) for row in records]
    maximum = max(max(abs(value) for value in numeric_values), 0.001)
    axis_x = 570
    scale = 390 / maximum
    line_height = 42
    height = 90 + line_height * len(records)
    elements = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="{height}" viewBox="0 0 1200 {height}">',
        '<style>text{font-family:Arial,sans-serif;fill:#172033}.title{font-size:20px;font-weight:bold}.label{font-size:12px}.value{font-size:12px;font-weight:bold}</style>',
        '<rect width="100%" height="100%" fill="white"/>',
        '<text x="24" y="32" class="title">Registered QLIKE contrasts: all signs retained</text>',
        '<text x="24" y="54" class="label">Positive bars favour the expanded information set; zero is the vertical reference.</text>',
        f'<line x1="{axis_x}" y1="68" x2="{axis_x}" y2="{height - 18}" stroke="#34495e" stroke-width="2"/>',
    ]
    for index, record in enumerate(records):
        value = _table_float(record["qlike_delta"])
        y = 86 + index * line_height
        width = abs(value) * scale
        x = axis_x if value >= 0 else axis_x - width
        color = "#167a49" if value >= 0 else "#b34036"
        label = (
            f"{record['block']} | {record['model_role']} | {record['contrast']}"
        )
        elements.extend(
            [
                f'<text x="20" y="{y + 15}" class="label">{html.escape(label)}</text>',
                f'<rect x="{x:.2f}" y="{y}" width="{width:.2f}" height="20" fill="{color}"/>',
                f'<text x="{axis_x + 8 if value >= 0 else axis_x - width - 75:.2f}" y="{y + 15}" class="value">{_format_signed(value)}</text>',
            ]
        )
    elements.append("</svg>")
    return "\n".join(elements)


def _design_flow_svg() -> str:
    """Render a compact conceptual design flow without numerical inference."""

    boxes = (
        (22, "PIT data contract", "provider timestamps and availability"),
        (242, "Shared forecast origins", "same B0/B1a/B2 origin IDs"),
        (462, "RV30 target", "31 closes, 30 log returns"),
        (682, "Nested QLIKE tests", "B0 -> B1a -> B2"),
        (902, "Bounded conclusion", "daily bootstrap, Holm, frozen MDE"),
    )
    elements = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1120" height="220" viewBox="0 0 1120 220">',
        '<style>text{font-family:Arial,sans-serif;fill:#172033}.title{font-size:19px;font-weight:bold}.head{font-size:14px;font-weight:bold}.body{font-size:11px}</style>',
        '<rect width="100%" height="100%" fill="white"/>',
        '<text x="20" y="28" class="title">Canonical RV30 design: evidence before conclusion</text>',
        '<defs><marker id="arrow" markerWidth="9" markerHeight="7" refX="8" refY="3.5" orient="auto"><polygon points="0 0, 9 3.5, 0 7" fill="#123c69"/></marker></defs>',
    ]
    for index, (x, heading, body) in enumerate(boxes):
        elements.extend(
            [
                f'<rect x="{x}" y="78" width="180" height="90" rx="8" fill="#eef5fb" stroke="#123c69"/>',
                f'<text x="{x + 12}" y="108" class="head">{html.escape(heading)}</text>',
                f'<text x="{x + 12}" y="133" class="body">{html.escape(body)}</text>',
            ]
        )
        if index < len(boxes) - 1:
            elements.append(
                f'<line x1="{x + 184}" y1="123" x2="{x + 216}" y2="123" stroke="#123c69" stroke-width="2" marker-end="url(#arrow)"/>'
            )
    elements.append("</svg>")
    return "\n".join(elements)


def _build_outputs(records: Sequence[Mapping[str, str]]) -> dict[Path, bytes]:
    """Build deterministic output bytes without touching the filesystem."""

    markdown = _report_markdown(records)
    return {
        Path("MDS650_Canonical_RV30_Defense_Report.md"): markdown.encode("utf-8"),
        Path("MDS650_Canonical_RV30_Defense_Report.html"): _report_html(
            markdown, records
        ).encode("utf-8"),
        Path("MDS650_Canonical_RV30_Defense_Slides.md"): _slides_markdown(records).encode(
            "utf-8"
        ),
        Path("tables/canonical_registered_contrasts.csv"): _csv_bytes(records),
        Path("figures/canonical_qlike_contrasts.svg"): _qlike_svg(records).encode("utf-8"),
        Path("figures/canonical_design_flow.svg"): _design_flow_svg().encode("utf-8"),
    }


def _write_equal(path: Path, payload: bytes) -> bool:
    """Write stable bytes atomically, rejecting any different pre-existing artifact.

    Parameters
    ----------
    path
        Desired output path under the package root.
    payload
        Fully rendered deterministic bytes.

    Returns
    -------
    bool
        ``True`` when an existing artifact is byte-identical; ``False`` when newly written.

    Raises
    ------
    RuntimeError
        If a pre-existing output is not the expected byte-identical artifact.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if not path.is_file() or path.read_bytes() != payload:
            raise RuntimeError("CANONICAL_DEFENSE_OUTPUT_CONFLICT")
        return True
    temporary = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    try:
        temporary.write_bytes(payload)
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return False


def build_defense_package(source: Path, output: Path) -> dict[str, object]:
    """Render only validated canonical RV30 evidence into defense artifacts.

    Parameters
    ----------
    source
        Canonical artifact directory containing the validated report manifest and contrasts.
    output
        New or byte-identical package directory. This location must not contain a divergent
        prior report because silently overwriting presentation evidence is disallowed.

    Returns
    -------
    dict[str, object]
        Sanitized package manifest with logical paths, source/output hashes, eligibility, and
        either a pass or byte-identical-reuse status.

    Raises
    ------
    RuntimeError
        If source evidence is invalid or a pre-existing output differs from the deterministic
        package bytes.

    Examples
    --------
    >>> build_defense_package(
    ...     Path("artifacts/canonical_validation_v1"),
    ...     Path("reports/canonical_validation_v1"),
    ... )["status"]
    'PASS_CANONICAL_DEFENSE_PACKAGE'
    """

    report_manifest, rows = load_validated_contrasts(source)
    records = _table_rows(rows)
    output_payloads = _build_outputs(records)
    if tuple(output_payloads) != _OUTPUT_FILES:
        raise RuntimeError("CANONICAL_DEFENSE_OUTPUT_INVALID")

    existing = [
        _write_equal(output / relative, payload)
        for relative, payload in output_payloads.items()
    ]
    input_paths = [f"{_ARTIFACT_ROOT}/{name}" for name in _INPUT_FILES]
    output_paths = [relative.as_posix() for relative in _OUTPUT_FILES] + [
        "MDS650_Defense_Package_Manifest.json"
    ]
    manifest_payload: dict[str, object] = {
        "schema_version": "1.0",
        "status": "PASS_CANONICAL_DEFENSE_PACKAGE",
        "source_status": report_manifest["status"],
        "claim_eligibility": _EXPECTED_ELIGIBILITY,
        "input_paths": input_paths,
        "input_hashes": {
            f"{_ARTIFACT_ROOT}/{name}": _sha256(source / name) for name in _INPUT_FILES
        },
        "output_paths": output_paths,
        "output_hashes": {
            relative.as_posix(): hashlib.sha256(payload).hexdigest()
            for relative, payload in output_payloads.items()
        },
        "registered_models": list(_REGISTERED_ROLES),
        "all_signs_retained": True,
        "personal_paths_emitted": False,
        "secret_values_emitted": False,
    }
    manifest_bytes = (
        json.dumps(manifest_payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    ).encode("utf-8")
    manifest_existing = _write_equal(
        output / "MDS650_Defense_Package_Manifest.json", manifest_bytes
    )
    result = dict(manifest_payload)
    result["status"] = (
        "REUSED_HASH_VERIFIED"
        if all(existing) and manifest_existing
        else "PASS_CANONICAL_DEFENSE_PACKAGE"
    )
    return result


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse offline package-rendering command arguments."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("artifacts/canonical_validation_v1"),
        help="Validated canonical artifact directory.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/canonical_validation_v1"),
        help="Portable defense-package directory.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Create the offline defense package and print its sanitized manifest."""

    args = _parse_args(argv)
    result = build_defense_package(args.source, args.output)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
