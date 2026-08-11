"""Render deterministic human-readable provider-timing documentation from evidence JSON."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = (
    ROOT / "artifacts" / "provider_timing" / "provider_timing_semantics_audit_v1.json"
)
DEFAULT_DOCS = ROOT / "docs"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse local evidence and documentation output paths."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--docs-dir", type=Path, default=DEFAULT_DOCS)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Generate four required timing documents from sanitized evidence.

    Parameters
    ----------
    argv:
        Optional explicit command arguments.

    Returns
    -------
    int
        Zero after documentation is atomically written.

    Raises
    ------
    ValueError
        If the evidence manifest lacks required timing sections.
    """
    args = parse_args(argv)
    payload = _read_mapping(args.manifest)
    docs_dir = args.docs_dir
    _write_text(docs_dir / "provider_timing_semantics_audit_v1.md", _semantics_markdown(payload))
    _write_text(docs_dir / "provider_timing_gate_amendment_v1.md", _gate_markdown(payload))
    _write_text(docs_dir / "provider_support_questions.md", _support_questions_markdown())
    _write_text(
        docs_dir / "provider_timing_future_execution_guide.md",
        _future_execution_markdown(payload),
    )
    return 0


def _semantics_markdown(payload: Mapping[str, Any]) -> str:
    """Render the primary FMP/UW evidence interpretation."""
    fmp = _require_mapping(payload, "fmp")
    uw = _require_mapping(payload, "unusual_whales")
    global_summary = _require_mapping(uw, "global")
    documentation = fmp.get("official_sources")
    if not isinstance(documentation, list):
        raise ValueError("TIMING_DOCUMENTATION_SOURCES_MISSING")
    citations = "\n".join(
        f"- [{_as_text(source.get('title'))}]({_as_text(source.get('url'))}): "
        f"{_as_text(source.get('observed_statement'))}"
        for source in documentation
        if isinstance(source, Mapping)
    )
    fmp_rows = [
        (
            "FMP_BAR_LABEL_SEMANTICS",
            _as_text(fmp.get("fmp_bar_label_semantics")),
            "Do not claim start or close labeling.",
        ),
        (
            "FMP_PROVIDER_CONFIRMED_LATENCY",
            _as_text(fmp.get("fmp_provider_confirmed_latency")),
            "Do not claim verified provider latency.",
        ),
        (
            "FMP_RESEARCH_AVAILABILITY_RULE",
            _as_text(fmp.get("fmp_research_availability_rule")),
            "Use `timestamp + 1 minute`; report `+2 minutes` as sensitivity.",
        ),
        (
            "FMP live probe",
            _as_text(fmp.get("live_probe_status")),
            "Pending prospective measurement; not a current failure.",
        ),
    ]
    fmp_table_rows = [
        f"| {name} | `{status}` | {consequence} |"
        for name, status, consequence in fmp_rows
    ]
    metric_rows = [
        ("Rows in scope", _number(global_summary.get("row_count"), 0)),
        (
            "`executed_at` completeness",
            _percent(global_summary.get("executed_at_completeness")),
        ),
        (
            "`created_at` completeness",
            _percent(global_summary.get("created_at_completeness")),
        ),
        (
            "Negative `created_at - executed_at` values",
            _number(global_summary.get("negative_latency_count"), 0),
        ),
        ("P1 latency seconds", _decimal(global_summary.get("latency_p1_seconds"))),
        ("P5 latency seconds", _decimal(global_summary.get("latency_p5_seconds"))),
        ("P50 latency seconds", _decimal(global_summary.get("latency_p50_seconds"))),
        ("P90 latency seconds", _decimal(global_summary.get("latency_p90_seconds"))),
        ("P95 latency seconds", _decimal(global_summary.get("latency_p95_seconds"))),
        ("P99 latency seconds", _decimal(global_summary.get("latency_p99_seconds"))),
        ("Maximum latency seconds", _decimal(global_summary.get("latency_max_seconds"))),
        (
            "Within 60-second latency ceiling",
            _percent(global_summary.get("latency_within_60_seconds_share")),
        ),
        (
            "Within 120-second latency ceiling",
            _percent(global_summary.get("latency_within_120_seconds_share")),
        ),
        (
            "Within 300-second latency ceiling",
            _percent(global_summary.get("latency_within_300_seconds_share")),
        ),
    ]
    metric_table_rows = [f"| {name} | {value} |" for name, value in metric_rows]
    historical_classification = _as_text(uw.get("historical_uw_classification"))
    lines = [
        "# Provider Timing Semantics Audit v1",
        "",
        "## Scope and boundary",
        "",
        "This is an offline audit of already-acquired, filtered Unusual Whales Full Tape "
        "data and a static review of official FMP documentation. It does not read RV30, "
        "QLIKE, model predictions or targets; it makes no provider HTTP request.",
        "",
        "## FMP official documentation archive",
        "",
        f"Retrieved on: `{_as_text(fmp.get('retrieved_on'))}`.",
        "",
        citations,
        "",
        "The documentation confirms a one-minute OHLCV endpoint, but does **not** state the "
        "response timestamp timezone, whether it labels interval start or close, or the "
        "publication latency of a completed bar.",
        "",
        "| Decision | Status | Consequence |",
        "|---|---|---|",
        *fmp_table_rows,
        "",
        "`timestamp + 1 minute` is a conservative research rule, not a provider-confirmed "
        "publication timestamp.",
        "",
        "## Unusual Whales historical Full Tape audit",
        "",
        f"Historical contract classification: `{historical_classification}`.",
        "",
        "| Metric | Observed value |",
        "|---|---:|",
        *metric_table_rows,
        "",
        "Global, cohort and asset percentiles use a deterministic hash sample; each session "
        "uses its complete timestamp distribution. The associated CSV files retain the exact "
        "counts, field missingness, cutoff shares and the appropriate quantile method.",
        "",
        "The audit demonstrates only the observed relationship between two provider fields. "
        "It does **not** demonstrate client receipt time, provider publication time, trader "
        "intent or informed trading. Therefore `created_at` remains an operational "
        "availability proxy, never a publication-time label.",
        "",
        "## Cohort comparison",
        "",
        _cohort_comparison_markdown(_require_mapping(uw, "cohort_stability")),
        "",
        "## Evidence files",
        "",
        "- `artifacts/provider_timing/provider_timing_semantics_audit_v1.json`",
        "- `artifacts/provider_timing/fmp_official_documentation_v1.json`",
        "- `artifacts/provider_timing/uw_historical_latency_summary.csv`",
        "- `artifacts/provider_timing/uw_historical_latency_by_session.csv`",
        "- `artifacts/provider_timing/uw_historical_latency_by_asset.csv`",
        "",
    ]
    return "\n".join(lines)


def _gate_markdown(payload: Mapping[str, Any]) -> str:
    """Render the explicit amendment that supersedes an undifferentiated NO-GO."""
    gates = _require_mapping(payload, "gates")
    rows = "\n".join(
        f"| `{name}` | `{_as_text(value)}` | {_gate_consequence(name)} |"
        for name, value in gates.items()
    )
    return "\n".join(
        [
            "# Provider Timing Gate Amendment v1",
            "",
            "## Decision",
            "",
            "This amendment replaces a single absolute timing NO-GO with evidence-scoped "
            "decisions. `UNVERIFIED` means an evidence boundary, not automatically false and "
            "not automatically a hard blocker for work already frozen under explicit timing "
            "assumptions.",
            "",
            "| Gate | Status | Consequence |",
            "|---|---|---|",
            rows,
            "",
            "## Scope protection",
            "",
            "This amendment does not alter, re-read or recompute canonical RV30/QLIKE results, "
            "features, model fits, evidence hashes or conclusions. It authorizes only the "
            "scientific reconciliation of existing canonical evidence under its registered "
            "timing assumptions. A future historical sample still needs a date-level PIT "
            "preflight; a future prospective sample still needs a validated receipt logger.",
            "",
            "The pending prospective probe must not block reconciliation of existing QLIKE, "
            "MAE, RMSE, calibration, MDE or already-frozen results.",
            "",
        ]
    )


def _support_questions_markdown() -> str:
    """Render narrowly scoped written questions for the two providers."""
    return """# Provider Support Questions — Timing Semantics

## Financial Modeling Prep

1. For `stable/historical-chart/1min`, what timezone is carried by the returned
   `date`/timestamp field for US equities and ETFs?
2. Does that timestamp label the start of the one-minute interval, its completed
   close, or another convention?
3. After an XNYS one-minute interval completes, what is the documented or
   measured availability latency of the completed OHLCV bar through this endpoint?
4. Are historical intraday bars ever corrected after initial availability? If so,
   how are corrections timestamped and versioned?

## Unusual Whales

1. In historical Full Tape, what precisely do `executed_at` and `created_at`
   represent, including their clock source and UTC convention?
2. Is `created_at` a trade-record creation time, an ingestion time, an alert
   creation time, or a customer-visible publication time?
3. Can a historical Full Tape record be revised after `created_at`? If yes, is
   there a version, update timestamp or correction feed?
4. Is there a documented event identifier that is stable between live delivery
   and the subsequently archived Full Tape file?
5. Which live transport, if any, delivers the same option-trade records, and is
   client receipt time available for audit?

Until written provider confirmation exists, these questions preserve the
distinction between an operational availability proxy and a verified provider
publication or client-receipt timestamp.
"""


def _future_execution_markdown(payload: Mapping[str, Any]) -> str:
    """Render the intentionally non-executing future XNYS capture runbook."""
    fmp = _require_mapping(payload, "fmp")
    return f"""# Provider Timing Future Execution Guide

## Current status

`{_as_text(fmp.get('live_probe_status'))}`

This status is pending and non-blocking. No market-open wait, provider HTTP
request, WebSocket connection or real-time capture was performed by this audit.

## Before a future authorized XNYS capture

1. Obtain explicit authorization for a prospective measurement window.
2. Synchronize the workstation clock and record the clock offset.
3. Store normalized provider messages in restricted storage, never in Git.
4. Ensure every persisted record includes when available: `event_id`, `trade_id`,
   `aggregated_trade_id`, `executed_at`, `created_at`, `received_at_utc`, `source`,
   `connection_type`, `local_clock_offset` and `raw_message_hash`.
5. Preserve raw payloads separately from sanitized receipt logs and never place
   API keys or personal paths in distributable artifacts.

## Local replay validation commands

```powershell
pwsh -NoProfile -File .\\scripts\\run_provider_timing_capture_once.ps1 -Mode Prepare

# Only after a future operator has saved local replay fixtures:
pwsh -NoProfile -File .\\scripts\\run_provider_timing_capture_once.ps1 `
  -Mode Replay -ReplayDirectory D:\\MDS650\\restricted\\provider_timing_replay
```

`Prepare` is intentionally safe: it does not connect to a provider, wait for a
session or consume credentials. `Replay` validates only locally supplied replay
files through the three scripts below:

- `scripts/probe_fmp_bar_availability.py`
- `scripts/log_uw_option_trade_receipts.py`
- `scripts/reconcile_uw_live_vs_full_tape.py`

Successful replay proves schema handling and deterministic logging, not live
receipt latency, provider publication time or a universal provider latency rule.
"""


def _cohort_comparison_markdown(stability: Mapping[str, Any]) -> str:
    """Render descriptive cohort-difference evidence without overstating stability."""
    comparisons = stability.get("comparisons")
    if not isinstance(comparisons, list) or not comparisons:
        return "Only one cohort was available; no cross-cohort comparison is possible."
    lines = [
        "| Baseline | Comparison | |P50 difference| seconds | |P95 difference| seconds | "
        "|60s-share difference| |",
        "|---|---|---:|---:|---:|",
    ]
    for row in comparisons:
        if not isinstance(row, Mapping):
            continue
        lines.append(
            "| "
            + " | ".join(
                [
                    _as_text(row.get("baseline_cohort")),
                    _as_text(row.get("comparison_cohort")),
                    _decimal(row.get("latency_p50_absolute_difference_seconds")),
                    _decimal(row.get("latency_p95_absolute_difference_seconds")),
                    _decimal(row.get("within_60_seconds_share_absolute_difference")),
                ]
            )
            + " |"
        )
    lines.append("")
    lines.append(_as_text(stability.get("interpretation")))
    return "\n".join(lines)


def _gate_consequence(name: str) -> str:
    """Return a human-readable consequence for each approved gate name."""
    consequences = {
        "EXISTING_CANONICAL_EVIDENCE": "Existing registered evidence remains interpretable.",
        "EXISTING_SCIENTIFIC_RECONCILIATION": "Reconcile existing results now; do not rerun them.",
        "NEW_HISTORICAL_SAMPLE": "Run a date-level PIT preflight before acquisition.",
        "NEW_PROSPECTIVE_SAMPLE": "Validate the receipt logger before a live capture.",
        "UNIVERSAL_PROVIDER_LATENCY_CLAIM": "Do not make a universal latency assertion.",
    }
    return consequences.get(name, "Evidence-scoped decision.")


def _read_mapping(path: Path) -> Mapping[str, Any]:
    """Read a required JSON object and reject unstructured evidence."""
    value: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("TIMING_MANIFEST_NOT_OBJECT")
    return value


def _require_mapping(container: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    """Return a required JSON-object section with a clear schema error."""
    value = container.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"TIMING_MANIFEST_SECTION_MISSING:{key}")
    return value


def _write_text(path: Path, text: str) -> None:
    """Write Markdown atomically with a deterministic final newline."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(text.rstrip() + "\n", encoding="utf-8")
    temporary.replace(path)


def _as_text(value: object) -> str:
    """Render a nullable metadata value without guessing a replacement."""
    return "UNAVAILABLE" if value is None else str(value)


def _number(value: object, digits: int) -> str:
    """Render a nullable numeric value with a fixed decimal policy."""
    if not isinstance(value, (int, float)):
        return "UNAVAILABLE"
    return f"{value:,.{digits}f}"


def _decimal(value: object) -> str:
    """Render latency or share values compactly while preserving precision."""
    if not isinstance(value, (int, float)):
        return "UNAVAILABLE"
    return f"{value:.6f}"


def _percent(value: object) -> str:
    """Render a nullable fraction as a percentage."""
    if not isinstance(value, (int, float)):
        return "UNAVAILABLE"
    return f"{100.0 * value:.4f}%"


if __name__ == "__main__":
    raise SystemExit(main())
