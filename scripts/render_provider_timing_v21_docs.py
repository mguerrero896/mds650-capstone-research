"""Render the human-readable PIT v2.1 amendment from compact sidecars only."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from mds650.provider_timing_v21 import build_pit_claim_matrix_v21, canonical_sha256

ROOT = Path(__file__).resolve().parents[1]


def _read_json(path: Path) -> dict[str, Any]:
    """Read one compact JSON evidence object."""
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"TIMING_V21_JSON_OBJECT_REQUIRED:{path.name}")
    return value


def _read_csv(path: Path) -> list[dict[str, str]]:
    """Read one compact CSV evidence file without making type inferences."""
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write(path: Path, content: str) -> None:
    """Write deterministic UTF-8 Markdown content."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def _table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    """Return a compact escaped CommonMark table."""
    lines = ["| " + " | ".join(headers) + " |"]
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    for row in rows:
        lines.append("| " + " | ".join(str(value).replace("|", "\\|") for value in row) + " |")
    return "\n".join(lines)


def render_documents(*, artifact_dir: Path, docs_dir: Path, reports_dir: Path) -> dict[str, Any]:
    """Render v2.1 contract, matrix, appendix, and handoff from sidecars.

    Parameters
    ----------
    artifact_dir:
        Compact v2.1 evidence directory.
    docs_dir:
        Destination documentation directory.
    reports_dir:
        Destination handoff report directory.

    Returns
    -------
    dict[str, Any]
        Render summary with target-free status and deterministic document hashes.

    Raises
    ------
    FileNotFoundError
        If a required compact sidecar is absent.
    ValueError
        If a required evidence file is not a JSON object.
    """
    audit = _read_json(artifact_dir / "pit_timing_audit_v21.json")
    massive = _read_json(artifact_dir / "massive_reselection_sensitivity_v21.json")
    incidents = _read_csv(artifact_dir / "uw_session_asset_incidents_v21.csv")
    traceability = _read_csv(artifact_dir / "b2_canonical_traceability_v21.csv")
    sources = [
        _read_json(path) for path in sorted((artifact_dir / "official_sources").glob("*.json"))
    ]
    if len(sources) != 4:
        raise ValueError("TIMING_V21_OFFICIAL_SOURCE_RECORD_COUNT_INVALID")
    claims = build_pit_claim_matrix_v21()
    (artifact_dir / "pit_claim_matrix_v21.json").write_text(
        json.dumps(claims, indent=2, sort_keys=True), encoding="utf-8"
    )
    b2_gate = str(audit["b2"]["b2_activity_availability_gate"])
    massive_status = str(
        massive.get(
            "status",
            "PASS"
            if not massive.get("cache_identity_failures")
            and massive.get("quote_existence_coverage_monotonic_nonincreasing") is True
            else "FAIL_CACHE_IDENTITY_OR_MONOTONICITY",
        )
    )
    status = (
        "CONDITIONAL_NOT_CLOSED"
        if b2_gate.startswith("FAIL_") or massive_status != "PASS"
        else "PASS"
    )
    reconciliation_gate = dict(audit.get("reconciliation_gate", {}))
    safe_to_reconcile = bool(
        reconciliation_gate.get(
            "safe_to_reconcile_existing_results",
            b2_gate == "PASS" and massive_status == "PASS",
        )
    )
    reconciliation_reasons = list(reconciliation_gate.get("reasons", []))
    origin_bounds = dict(audit.get("forecast_origin_session_bounds", {}))
    source_table = _table(
        ["Source", "Status", "Body SHA-256", "Support", "Boundary"],
        [
            [
                str(row["source_id"]),
                f"HTTP {row['http_status']}",
                str(row["source_content_sha256"]),
                str(row["documented_excerpt"]),
                str(row["documented_nonclaim"]),
            ]
            for row in sources
        ],
    )
    claim_table = _table(
        ["Claim", "Evidence class", "Permitted conclusion"],
        [
            [str(row["claim_key"]), str(row["claim_class"]), str(row["permitted_conclusion"])]
            for row in claims
        ],
    )
    named_dates = ("2025-08-21", "2025-09-18", "2025-10-20", "2026-01-29")
    incident_rows: list[list[str]] = []
    for day in named_dates:
        rows = [row for row in incidents if row.get("session_date") == day]
        states = Counter(str(row.get("source_temporal_state", "")) for row in rows)
        minimum = min(
            (float(row["lag_seconds_min"]) for row in rows if row["lag_seconds_min"]),
            default=0.0,
        )
        maximum = max((float(row["lag_seconds_max"] or 0.0) for row in rows), default=0.0)
        incident_rows.append(
            [
                day,
                str(len(rows)),
                ", ".join(f"{key}:{value}" for key, value in sorted(states.items())),
                f"{minimum:.3f}",
                f"{maximum:.3f}",
            ]
        )
    incident_table = _table(
        ["Session", "Assets", "Observed source state", "Min lag (s)", "Max lag (s)"],
        incident_rows,
    )
    massive_table = _table(
        ["Cutoff", "Quote coverage", "Median quote age from origin (s)", "IV available"],
        [
            [
                f"origin - {row['cutoff_delay_seconds']}s",
                f"{float(row['quote_coverage_rate'] or 0.0):.6f}",
                str(row["median_quote_age_seconds"]),
                f"{float(row['iv_available_rate'] or 0.0):.6f}",
            ]
            for row in massive.get("summary_by_cutoff", [])
        ],
    )
    cache_scope_warnings = dict(massive.get("cache_scope_warnings", {}))
    trace_counts = dict(
        sorted(Counter(row.get("coding_status", "") for row in traceability).items())
    )
    contract = f"""# Provider Timing PIT Contract v2.1

**Status:** `{status}`

## Scope

This amendment is target-blind. It reads official documentation and already
acquired Full Tape, B2, B1 provenance, and Massive cache data only. It does not
read RV30, QLIKE, forecasts, predictions, model outputs, or outcomes. It does
not train a model or download provider data.

## FMP one-minute bars

FMP's FAQ documents intraday timezone convention at the exchange-country/region
level. `timestamp_raw + 1 minute` remains a conservative study rule. Exact IANA
implementation, DST handling, bar-start/bar-close label, and completed-bar
latency are unresolved provider facts.

## Unusual Whales Full Tape

The REST/OpenAPI sources document a date-specific ZIP. Kafka documentation
defines Kafka timestamps; Full Tape field-name and UTC concordance are payload
observations only. Neither source establishes historical publication time or
client receipt. `created_at` remains an operational availability proxy.

## B2 activity availability

Canonical B2 matrices lack an independent provider-availability field.
`b2v2_max_created_at_utc` is activity provenance, not a health indicator. The
coding sidecar counts are `{trace_counts}`.

**Gate:** `{b2_gate}`. A source record-creation delay paired with an all-zero
B2 row cannot be called genuine zero activity. The B2 activity-availability
contract is **not closed** until a future consumer applies the sidecar state.

**Existing-results reconciliation:**
`SAFE_TO_RECONCILE_EXISTING_RESULTS={"YES" if safe_to_reconcile else "NO"}`.
Reasons: `{", ".join(reconciliation_reasons) if reconciliation_reasons else "none"}`.
This rendering does not read, alter, or reinterpret any sealed predictive result.

## Massive shifted as-of sensitivity

At every delay, the audit reselects the last cached quote satisfying
`sip_timestamp <= forecast_origin - delay`; it does not filter a quote selected
at the original origin. IV is recalculated from the new midpoint and existing
target-free PIT inputs. This does not prove customer-side REST receipt latency.

**Forecast-origin session gate:** `{origin_bounds.get("status", "UNVERIFIED")}`.
The audit reports `{origin_bounds.get("origin_before_open_count", "UNVERIFIED")}`
origins before the official open and
`{origin_bounds.get("origin_after_close_count", "UNVERIFIED")}` after the
official close, including early-close sessions.

**Massive cache-identity gate:** `{massive_status}`. A failed identity or
monotonicity check keeps this contract conditional even if the B2 gate later
becomes passable.

**Massive request-scope warnings:** `{cache_scope_warnings}`. An early-close
request extended to the nominal 16:00 close is always reported separately,
rather than silently treated as an exact session request. If it contains a SIP
record after the actual close, the audit removes that record before every
as-of join and records `OK_EARLY_CLOSE_POST_CLOSE_QUOTES_EXCLUDED`; it never
permits such a record to be selected. The forecast-origin table is separately
constrained to the actual session close.

{massive_table}

## Official source archive

{source_table}
"""
    matrix = f"""# Provider Timing PIT Claim Matrix v2.1

Each conclusion is limited to its evidence class. Documentation bodies are not
stored; the official body SHA-256 identifies the reviewed content.

{claim_table}
"""
    appendix = f"""# Academic Appendix — Provider Timing PIT v2.1

## Session-asset timing incidents

{incident_table}

`2025-10-20` is an observed Full Tape record-creation delay, not a documented
provider outage and not evidence of no option activity. Existing data do not
identify an upstream queue, export mechanism, or other provider-internal cause.

## Canonical B2 coding audit

The traceability sidecar has one row per canonical variant/session/asset. It
distinguishes numeric zero, numeric missingness, row absence, source state, and
the absence of an independent availability indicator. It makes no predictive or
economic inference.
"""
    handoff = f"""# CODEX PIT v2.1 Validation Handoff

## Verdict

`{status}`. Documentation and cache-source amendment evidence is complete, but
the B2 activity-availability interpretation remains fail-closed:
`{b2_gate}`. Massive cache-identity status: `{massive_status}`.

`SAFE_TO_RECONCILE_EXISTING_RESULTS={"YES" if safe_to_reconcile else "NO"}`.
Reasons: `{", ".join(reconciliation_reasons) if reconciliation_reasons else "none"}`.

## Evidence

- Official documentation: {len(sources)}/4 allow-listed pages archived as
  metadata plus SHA-256 only; no raw document body is retained.
- UW incidents: {len(incidents)} session-asset rows.
- B2 traceability: {len(traceability)} canonical variant/session/asset rows.
- Massive quote-existence coverage non-increasing by stricter cutoff:
  `{massive.get("quote_existence_coverage_monotonic_nonincreasing")}`.

## Consequence

No predictive or economic conclusion follows from this amendment. Before B2 is
used in any panel, a future consumer must exclude or explicitly flag rows marked
`ZERO_CODING_POTENTIALLY_CONFOUNDED`.
"""
    _write(docs_dir / "provider_timing_pit_contract_v21.md", contract)
    _write(docs_dir / "provider_timing_claim_matrix_v21.md", matrix)
    _write(docs_dir / "provider_timing_academic_appendix_v21.md", appendix)
    _write(reports_dir / "CODEX_PIT_V21_HANDOFF.md", handoff)
    return {
        "schema_version": "provider-timing-v2.1",
        "status": status,
        "b2_activity_availability_gate": b2_gate,
        "safe_to_reconcile_existing_results": safe_to_reconcile,
        "document_hashes": {
            "provider_timing_pit_contract_v21.md": canonical_sha256(contract),
            "provider_timing_claim_matrix_v21.md": canonical_sha256(matrix),
            "provider_timing_academic_appendix_v21.md": canonical_sha256(appendix),
            "CODEX_PIT_V21_HANDOFF.md": canonical_sha256(handoff),
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Render all PIT v2.1 documentation from existing compact artifacts.

    Parameters
    ----------
    argv:
        Optional CLI arguments for reproducible local execution.

    Returns
    -------
    int
        Zero after successful deterministic rendering.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--artifact-dir", type=Path, default=ROOT / "artifacts" / "provider_timing_v21"
    )
    parser.add_argument("--docs-dir", type=Path, default=ROOT / "docs")
    parser.add_argument("--reports-dir", type=Path, default=ROOT / "reports")
    args = parser.parse_args(argv)
    result = render_documents(
        artifact_dir=args.artifact_dir,
        docs_dir=args.docs_dir,
        reports_dir=args.reports_dir,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
