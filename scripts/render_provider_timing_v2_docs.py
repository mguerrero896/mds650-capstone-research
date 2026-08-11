# ruff: noqa: E501
"""Render deterministic PIT v2 contract and handoff documents from offline evidence."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse paths for compact evidence input and rendered Markdown output.

    Parameters
    ----------
    argv:
        Optional command-line arguments. ``None`` uses process arguments.

    Returns
    -------
    argparse.Namespace
        Input and output directories. No network or provider credential options
        are accepted.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-dir", type=Path, default=Path("artifacts/provider_timing_v2"))
    parser.add_argument("--docs-dir", type=Path, default=Path("docs"))
    parser.add_argument("--reports-dir", type=Path, default=Path("reports"))
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Render the PIT v2 contract, claim matrix, appendix and handoff.

    Parameters
    ----------
    argv:
        Optional paths for evidence and output folders.

    Returns
    -------
    int
        Zero after the four deterministic Markdown documents are written.

    Raises
    ------
    FileNotFoundError
        If a required compact evidence file is missing.
    ValueError
        If a claim class, required gate, or evidence schema is inconsistent.
    """
    args = parse_args(argv)
    manifest = _read_mapping(args.audit_dir / "pit_timing_audit_v2.json")
    claims_payload = _read_mapping(args.audit_dir / "pit_claim_matrix_v2.json")
    claims = _claim_rows(claims_payload)
    sources = _source_records(args.audit_dir / "official_sources")
    _validate_evidence(manifest=manifest, claims=claims)
    args.docs_dir.mkdir(parents=True, exist_ok=True)
    args.reports_dir.mkdir(parents=True, exist_ok=True)
    _write_markdown(
        args.docs_dir / "provider_timing_claim_matrix_v2.md",
        _render_claim_matrix(claims=claims, sources=sources),
    )
    _write_markdown(
        args.docs_dir / "provider_timing_pit_contract_v2.md",
        _render_contract(manifest=manifest, claims=claims, sources=sources),
    )
    _write_markdown(
        args.docs_dir / "provider_timing_academic_appendix_v2.md",
        _render_academic_appendix(manifest=manifest, sources=sources),
    )
    _write_markdown(
        args.reports_dir / "CODEX_PIT_V2_HANDOFF.md",
        _render_handoff(manifest=manifest, sources=sources),
    )
    return 0


def _read_mapping(path: Path) -> dict[str, Any]:
    """Read one compact JSON object or fail closed."""
    if not path.is_file():
        raise FileNotFoundError(f"TIMING_V2_EVIDENCE_MISSING:{path.name}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"TIMING_V2_EVIDENCE_NOT_OBJECT:{path.name}")
    return payload


def _claim_rows(payload: Mapping[str, Any]) -> list[dict[str, str]]:
    """Validate claim rows before rendering their distinction into prose."""
    rows = payload.get("claims")
    if not isinstance(rows, list):
        raise ValueError("TIMING_V2_CLAIMS_MISSING")
    required = {
        "claim_key",
        "provider",
        "field_or_topic",
        "claim_class",
        "evidence_locator",
        "permitted_conclusion",
    }
    output: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict) or not required.issubset(row):
            raise ValueError("TIMING_V2_CLAIM_SCHEMA_INVALID")
        normalized = {key: str(row[key]) for key in required}
        output.append(normalized)
    return sorted(output, key=lambda row: row["claim_key"])


def _source_records(directory: Path) -> list[dict[str, Any]]:
    """Read source-record metadata without retaining raw documentation bodies."""
    if not directory.is_dir():
        raise FileNotFoundError("TIMING_V2_OFFICIAL_SOURCE_DIRECTORY_MISSING")
    records = [_read_mapping(path) for path in sorted(directory.glob("*.json"))]
    if not records:
        raise ValueError("TIMING_V2_OFFICIAL_SOURCE_RECORDS_EMPTY")
    return sorted(records, key=lambda record: str(record.get("source_id", "")))


def _validate_evidence(*, manifest: Mapping[str, Any], claims: Sequence[Mapping[str, str]]) -> None:
    """Reject unsupported semantic relabelling before document generation."""
    accepted_classes = {
        "PROVIDER_DOCUMENTED",
        "PAYLOAD_OBSERVED",
        "STUDY_CONSERVATIVE_RULE",
        "UNVERIFIED",
    }
    by_key = {claim["claim_key"]: claim for claim in claims}
    for claim in claims:
        if claim["claim_class"] not in accepted_classes:
            raise ValueError("TIMING_V2_CLAIM_CLASS_INVALID")
    required_claims = {
        "fmp_timestamp_timezone",
        "fmp_bar_bucket_label",
        "uw_created_at",
        "uw_publication_or_client_receipt",
        "massive_sip_timestamp",
        "massive_rest_receipt_time",
    }
    if not required_claims.issubset(by_key):
        raise ValueError("TIMING_V2_REQUIRED_CLAIM_MISSING")
    if by_key["uw_created_at"]["claim_class"] != "PROVIDER_DOCUMENTED":
        raise ValueError("TIMING_V2_UW_CREATED_AT_CLASS_INVALID")
    if "publication" in by_key["uw_created_at"]["permitted_conclusion"].lower():
        raise ValueError("TIMING_V2_UW_CREATED_AT_PUBLICATION_RELABEL")
    gates = manifest.get("gates")
    if not isinstance(gates, dict):
        raise ValueError("TIMING_V2_GATES_MISSING")
    required_gates = {
        "EXISTING_FMP_EVIDENCE",
        "EXISTING_UW_RECORD_CREATION_EVIDENCE",
        "EXISTING_MASSIVE_SELECTED_QUOTE_EVIDENCE",
        "NEW_HISTORICAL_SAMPLE",
        "NEW_PROSPECTIVE_CAPTURE",
    }
    if not required_gates.issubset(gates):
        raise ValueError("TIMING_V2_GATE_MISSING")


def _render_claim_matrix(
    *, claims: Sequence[Mapping[str, str]], sources: Sequence[Mapping[str, Any]]
) -> str:
    """Render auditable timing claims in a compact Markdown table."""
    lines = [
        "# Provider Timing Claim Matrix v2",
        "",
        "This matrix separates provider documentation, local payload observations, conservative study rules, and unresolved claims. It contains no target, prediction, or performance result.",
        "",
        "| Provider | Field or topic | Claim class | Evidence locator | Permitted conclusion |",
        "|---|---|---|---|---|",
    ]
    for claim in claims:
        lines.append(
            "| {provider} | {field} | {claim_class} | {locator} | {conclusion} |".format(
                provider=_cell(claim["provider"]),
                field=_cell(claim["field_or_topic"]),
                claim_class=_cell(claim["claim_class"]),
                locator=_cell(claim["evidence_locator"]),
                conclusion=_cell(claim["permitted_conclusion"]),
            )
        )
    lines.extend(["", "## Official-source archive", ""])
    for source in sources:
        title = _cell(str(source.get("title", "Untitled official source")))
        url = str(source.get("url", ""))
        source_id = _cell(str(source.get("source_id", "unknown")))
        lines.append(f"- `{source_id}`: [{title}]({url})")
    return "\n".join(lines) + "\n"


def _render_contract(
    *,
    manifest: Mapping[str, Any],
    claims: Sequence[Mapping[str, str]],
    sources: Sequence[Mapping[str, Any]],
) -> str:
    """Render the deterministic PIT contract with evidence boundaries."""
    by_key = {claim["claim_key"]: claim for claim in claims}
    uw = _mapping(manifest, "uw")
    massive = _mapping(manifest, "massive")
    cache = _mapping(manifest, "massive_cache_schema_sample")
    lag_rows = _mapping_rows(uw, "record_creation_lag_cdf")
    feature_rows = _mapping_rows(uw, "feature_window_summary")
    source_urls = {str(source.get("source_id")): str(source.get("url")) for source in sources}
    lines = [
        "# Provider Timing PIT Contract v2",
        "",
        "## Scope and invariant",
        "",
        "This contract was built from official documentation and previously acquired, target-free provider evidence. It made no provider HTTP request, downloaded no market data, read no RV30/QLIKE/prediction/outcome field, and did not modify canonical research artifacts.",
        "",
        "One forecast origin is an asset at a valid five-minute XNYS market-time origin. Each provider field is usable only under the evidence class below; a study rule is never represented as provider documentation.",
        "",
        "## FMP one-minute OHLCV",
        "",
        f"- **Provider documentation:** [FMP 1-minute endpoint]({source_urls.get('fmp_1min_endpoint', '')}) documents one-minute OHLCV scope; [cycle times]({source_urls.get('fmp_cycle_times', '')}) labels the endpoint Real-Time.",
        f"- **Payload observation:** `{by_key['fmp_raw_timestamp_payload']['permitted_conclusion']}`",
        "- **Unresolved provider semantics:** FMP's raw timestamp timezone and whether it labels bar start or close are **not provider-documented** in the reviewed sources. The acquired audit records both as unresolved.",
        "- **Study rule:** interpret the raw label under the existing XNYS/`America/New_York` research convention, then set **FMP +1 minute** as the primary `available_at` rule and **FMP +2 minutes** as the prespecified sensitivity. These are conservative study rules, not an FMP latency statement.",
        "- **Calendar rule:** XNYS calendar logic controls regular sessions, DST transitions and early closes. This does not imply that FMP documents its bar-label semantics or its own calendar.",
        "",
        "## Unusual Whales Full Tape / B2",
        "",
        f"- **Provider documentation:** [OptionTrade]({source_urls.get('uw_option_trade', '')}) defines `executed_at` as execution time and `created_at` as trade-record creation time, both Unix milliseconds.",
        "- **Payload observation:** Full Tape persists both fields as UTC instants. `created_at - executed_at` is named **record-creation lag** in this study; it is not publication time, feed-dispatch time or client-receipt time.",
        "- **Study rule:** for buffer `d` in {60, 120, 300} seconds, B2 uses `[origin - d - 5 minutes, origin - d)` and requires `max(executed_at, created_at) <= origin - d`. The primary rule is `d=60`; 120 and 300 seconds are prespecified sensitivities.",
        "",
        "### Record-creation-lag CDF (exact acquired scope)",
        "",
        "| Buffer (seconds) | Within-buffer share | Interpretation |",
        "|---:|---:|---|",
    ]
    for row in lag_rows:
        lines.append(
            "| {buffer} | {share} | Nested record-creation-lag CDF; monotonic by construction. |".format(
                buffer=_integer(row.get("buffer_seconds")),
                share=_percent(row.get("within_buffer_share")),
            )
        )
    lines.extend(
        [
            "",
            "### Exact B2 feature-window eligibility (existing origins)",
            "",
            "| Buffer (seconds) | Candidate trades | Eligible trades | Eligibility retention | Note |",
            "|---:|---:|---:|---:|---|",
        ]
    )
    for row in feature_rows:
        lines.append(
            "| {buffer} | {candidate} | {eligible} | {share} | Windows shift with the buffer; this table is not a nested-CDF claim. |".format(
                buffer=_integer(row.get("buffer_seconds")),
                candidate=_integer(row.get("candidate_trade_count")),
                eligible=_integer(row.get("eligible_trade_count")),
                share=_percent(row.get("eligible_trade_retention_share")),
            )
        )
    tail = _mapping(uw, "extreme_tail")
    lines.extend(
        [
            "",
            "### Extreme-tail audit",
            "",
            "- Both timestamps observed: {both}; negative record-creation lags: {negative}; lags over 300 seconds: {tail300}; maximum observed lag: {maximum} seconds.".format(
                both=_integer(tail.get("both_timestamps_count")),
                negative=_integer(tail.get("negative_record_creation_lag_count")),
                tail300=_integer(tail.get("lag_over_300_seconds_count")),
                maximum=_number(tail.get("max_nonnegative_record_creation_lag_seconds")),
            ),
            "",
            "## Massive B1 quotes",
            "",
            f"- **Provider documentation:** [Massive Quotes]({source_urls.get('massive_options_quotes', '')}) defines `sip_timestamp` as the nanosecond timestamp when SIP received a quote from the exchange. `sequence_number` is increasing and unique per option ticker, but need not be sequential.",
            "- **Payload observation:** the existing v4 cache records sanitized `timestamp.lte`, `sort`, `order`, `limit`, `sip_timestamp`, `sequence_number`, bid and ask fields. The cache audit reports schema and request-upper-bound violations separately.",
            "- **Study rule:** select the last `(sip_timestamp, sequence_number)` quote whose `sip_timestamp <= forecast_origin`. This source-time rule prevents a future SIP quote from entering an origin, but it does not establish when a Massive REST response reached this project.",
            "- **Availability sensitivities:** source-time delays and maximum quote-age filters are conservative feasibility sensitivities. They are not labelled as measured Massive REST or client latency.",
            "",
            "### Existing selected-quote evidence",
            "",
            "| Check | Result |",
            "|---|---:|",
            f"| B1 origin rows | {_integer(_mapping(massive, 'origin_matrix').get('row_count'))} |",
            f"| Final selected future SIP timestamps | {_integer(_mapping(massive, 'origin_matrix').get('future_sip_timestamp_count'))} |",
            f"| IV-attempt future SIP timestamps | {_integer(_mapping(massive, 'iv_attempts').get('future_sip_timestamp_count'))} |",
            f"| Negative quote ages | {_integer(_mapping(massive, 'iv_attempts').get('negative_quote_age_count'))} |",
            f"| Final selected quote future-free | {str(massive.get('selected_quote_future_free'))} |",
            f"| Deterministic cache files schema-valid | {_integer(cache.get('schema_valid_file_count'))} |",
            f"| Cache quotes after request upper bound | {_integer(cache.get('quote_after_request_upper_bound_count'))} |",
            "",
            "## Gate map",
            "",
            "| Gate | Status | Meaning |",
            "|---|---|---|",
        ]
    )
    for gate, status in sorted(_mapping(manifest, "gates").items()):
        lines.append(
            f"| `{_cell(str(gate))}` | `{_cell(str(status))}` | {_gate_meaning(str(gate))} |"
        )
    return "\n".join(lines) + "\n"


def _render_academic_appendix(
    *, manifest: Mapping[str, Any], sources: Sequence[Mapping[str, Any]]
) -> str:
    """Render a compact academic appendix focused on timestamp validity boundaries."""
    uw = _mapping(manifest, "uw")
    massive = _mapping(manifest, "massive")
    lines = [
        "# Academic Appendix — Provider Timing and PIT Evidence v2",
        "",
        "## Purpose",
        "",
        "This appendix documents the timestamp contract used to prevent information entering a forecast origin after that origin. It is an engineering and provenance appendix; it does not report RV30, model, QLIKE or other predictive findings.",
        "",
        "## Evidence taxonomy",
        "",
        "1. **PROVIDER_DOCUMENTED** — an explicit statement on an official provider page.",
        "2. **PAYLOAD_OBSERVED** — a field or relationship present in acquired, immutable local evidence.",
        "3. **STUDY_CONSERVATIVE_RULE** — a deliberately stricter rule chosen by the study.",
        "4. **UNVERIFIED** — not established by the reviewed official documentation and payloads.",
        "",
        "## Provider-specific interpretation",
        "",
        "- **FMP:** the one-minute endpoint scope is documented, but the raw timestamp's timezone, bar-start/bar-close semantics and numerical completed-bar API availability are unresolved. +1 and +2 minutes are therefore conservative study assumptions.",
        "- **Unusual Whales:** `executed_at` describes execution and `created_at` describes creation of the trade record. The difference is record-creation lag. No source reviewed here establishes historical publication or this client's receipt time.",
        "- **Massive:** `sip_timestamp` is an exchange-to-SIP source timestamp in nanoseconds and `sequence_number` provides a deterministic tie-breaker. Neither field establishes REST delivery to this client.",
        "",
        "## Reproducible historical checks",
        "",
        "- UW record-creation-lag CDF monotonic: `{}`.".format(
            str(uw.get("record_creation_lag_cdf_monotonic"))
        ),
        "- Massive final selected quote future-free: `{}`.".format(
            str(massive.get("selected_quote_future_free"))
        ),
        "- This audit used existing acquired data only; it did not call a provider or create a new historical sample.",
        "",
        "## Gates for future evidence",
        "",
        "A new historical sample remains subject to a date-level PIT preflight. A prospective capture remains subject to a receipt logger that records provider event time, local request/receipt time, provider request ID where supplied, and clock discipline. Neither gate can be satisfied retroactively by relabelling `created_at` or `sip_timestamp`.",
        "",
        "## Official sources",
        "",
    ]
    for source in sources:
        lines.append(
            "- [{title}]({url}) — archived as compact metadata with source-record hash.".format(
                title=_cell(str(source.get("title", "Official source"))),
                url=str(source.get("url", "")),
            )
        )
    return "\n".join(lines) + "\n"


def _render_handoff(*, manifest: Mapping[str, Any], sources: Sequence[Mapping[str, Any]]) -> str:
    """Render a short evidence-based handoff without research-result claims."""
    uw = _mapping(manifest, "uw")
    massive = _mapping(manifest, "massive")
    cache = _mapping(manifest, "massive_cache_schema_sample")
    gates = _mapping(manifest, "gates")
    lines = [
        "# CODEX PIT v2 Validation Handoff",
        "",
        "## Scope",
        "",
        "- Official documentation plus acquired, target-free provider evidence only.",
        "- No new provider request, new market download, model training, target read, prediction read or canonical-artifact mutation.",
        "",
        "## Critical conclusions",
        "",
        "| Conclusion | Status | Evidence consequence |",
        "|---|---|---|",
        "| FMP endpoint scope is documented; timestamp timezone and bar label remain unresolved. | CONDITIONAL | Apply +1/+2-minute study rules, never call them FMP specifications. |",
        "| UW created_at is trade-record creation time. | PASS_PROXY_ONLY | It supports a conservative operational proxy, not publication/receipt or trader-intent claims. |",
        "| UW lag CDF is monotonic. | {status} | Exact B2 shifted-window eligibility is reported separately. |".format(
            status="PASS" if uw.get("record_creation_lag_cdf_monotonic") is True else "FAIL"
        ),
        "| Massive selected quotes are not future-dated. | {status} | The as-of rule is supported for existing B1 provenance, not REST-latency proof. |".format(
            status="PASS" if massive.get("selected_quote_future_free") is True else "FAIL"
        ),
        "| Massive deterministic cache schema sample is clean. | {status} | Schema and request-upper-bound evidence is limited to the sampled cache files. |".format(
            status="PASS"
            if _int_value(cache.get("schema_valid_file_count")) > 0
            and _int_value(cache.get("quote_after_request_upper_bound_count")) == 0
            else "FAIL"
        ),
        "",
        "## Gate status",
        "",
        "| Gate | Status |",
        "|---|---|",
    ]
    for gate, status in sorted(gates.items()):
        lines.append(f"| `{_cell(str(gate))}` | `{_cell(str(status))}` |")
    lines.extend(["", "## Source archive", ""])
    for source in sources:
        lines.append(
            "- `{source_id}`: [{title}]({url})".format(
                source_id=_cell(str(source.get("source_id", "unknown"))),
                title=_cell(str(source.get("title", "Official source"))),
                url=str(source.get("url", "")),
            )
        )
    lines.extend(
        [
            "",
            "## Residual boundaries",
            "",
            "- The audit does not prove FMP's raw bar timezone, start/close label or completed-bar REST delivery latency.",
            "- The audit does not prove UW publication time or this client's historical receipt time.",
            "- The audit does not prove Massive REST/client receipt latency.",
            "- A prospective receipt logger is required before making client-latency claims.",
        ]
    )
    return "\n".join(lines) + "\n"


def _mapping(container: Mapping[str, Any], key: str) -> dict[str, Any]:
    """Return one required nested mapping."""
    value = container.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"TIMING_V2_MAPPING_MISSING:{key}")
    return value


def _mapping_rows(container: Mapping[str, Any], key: str) -> list[dict[str, Any]]:
    """Return a list of mapping rows or fail closed."""
    value = container.get(key)
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise ValueError(f"TIMING_V2_ROWS_MISSING:{key}")
    return list(value)


def _write_markdown(path: Path, content: str) -> None:
    """Write Markdown only after rejecting personal filesystem paths."""
    if _contains_personal_path(content):
        raise ValueError("TIMING_V2_PERSONAL_PATH_IN_DOCUMENT")
    path.write_text(content, encoding="utf-8")


def _cell(value: str) -> str:
    """Escape a compact Markdown table cell."""
    return value.replace("|", "\\|").replace("\n", " ")


def _integer(value: object) -> str:
    """Render a missing numeric aggregate safely."""
    return "not available" if not isinstance(value, int) else f"{value:,}"


def _int_value(value: object) -> int:
    """Return an aggregate integer or zero when a test fixture omits it."""
    return value if isinstance(value, int) else 0


def _number(value: object) -> str:
    """Render a floating summary without encoding a missing value as zero."""
    return "not available" if not isinstance(value, int | float) else f"{float(value):.6f}"


def _percent(value: object) -> str:
    """Render a fraction as a human-readable percentage."""
    return "not available" if not isinstance(value, int | float) else f"{float(value) * 100:.4f}%"


def _gate_meaning(gate: str) -> str:
    """Return a fixed explanation for each evidence-scope gate."""
    meanings = {
        "EXISTING_FMP_EVIDENCE": "Existing evidence is usable only under explicit study rules.",
        "EXISTING_UW_RECORD_CREATION_EVIDENCE": "Record creation supports a proxy-only eligibility rule.",
        "EXISTING_MASSIVE_SELECTED_QUOTE_EVIDENCE": "Existing B1 source-time provenance has no future selected quote.",
        "EXISTING_MASSIVE_CACHE_SCHEMA_SAMPLE": "Sampled cache schema and request bounds were checked separately.",
        "NEW_HISTORICAL_SAMPLE": "A date-level PIT preflight is required before any new historical sample.",
        "NEW_PROSPECTIVE_CAPTURE": "A receipt logger is required before prospective latency claims.",
        "UNIVERSAL_PROVIDER_PUBLICATION_OR_RECEIPT_LATENCY": "Not established by existing documentation and payloads.",
    }
    return meanings.get(gate, "Evidence-scoped status; no broader inference is permitted.")


def _contains_personal_path(value: str) -> bool:
    """Detect Windows user-profile paths in a rendered document."""
    normalized = value.replace("/", "\\").lower()
    return "c:\\users\\" in normalized or "d:\\users\\" in normalized


if __name__ == "__main__":  # pragma: no cover - command entry point
    raise SystemExit(main())
