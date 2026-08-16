"""Derive bounded-pilot evidence from immutable raw/earlier probe artifacts."""

# ruff: noqa: E501

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(".")
OUT = ROOT / "artifacts" / "pilot"


def main() -> None:
    matrix = json.loads((ROOT / "artifacts/api_audit/b1_coverage_v1_20260721/matrix_exact.json").read_text())
    rows = matrix["rows"]
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(row["asset"], row["date"], row["origin_local"])].append(row)
    origins = []
    for (asset, day, origin), items in sorted(groups.items()):
        origins.append({
            "asset": asset, "date": day, "origin_local": origin,
            "origin_utc": items[0]["origin_utc"],
            "rows": len(items),
            "contract_resolution_rate": sum(x["contracts_resolved"] > 0 for x in items) / len(items),
            "quote_coverage_rate": sum(x["quotes_found"] > 0 for x in items) / len(items),
            "valid_midpoint_rate_primary": sum(x["valid_midpoint_primary"] > 0 for x in items) / len(items),
            "valid_midpoint_rate_sensitivity": sum(x["valid_midpoint_sensitivity"] > 0 for x in items) / len(items),
            "valid_expiry_bucket_count": len({x["bucket"] for x in items if x["valid_midpoint_primary"]}),
            "valid_moneyness_count": len({x["moneyness_target"] for x in items if x["valid_midpoint_primary"]}),
            "atm_iv_available": False,
            "skew_available": False,
            "term_structure_available": False,
            "option_state_pit_verified": False,
            "usable_for_primary": False,
        })
    summary = {
        "design_version": "B1_PILOT_ORIGIN_COVERAGE_V1",
        "status": "exploratory_origin_matrix_not_acceptance_gate",
        "source_artifact": "artifacts/api_audit/b1_coverage_v1_20260721/matrix_exact.json",
        "invalidated_prior_design": matrix.get("invalidated_prior_design"),
        "filters_primary": matrix["filters_primary"],
        "filters_sensitivity": matrix["filters_sensitivity"],
        "dates": matrix["dates"], "assets": matrix["assets"],
        "dte_buckets": matrix["dte_buckets"], "moneyness": matrix["moneyness"],
        "origin_count": len(origins), "row_count": len(rows),
        "origin_rows": origins,
        "aggregate": {
            "contract_resolution_rate": sum(x["contracts_resolved"] > 0 for x in rows) / len(rows),
            "quote_coverage_rate": sum(x["quotes_found"] > 0 for x in rows) / len(rows),
            "valid_midpoint_rate_primary": sum(x["valid_midpoint_primary"] > 0 for x in rows) / len(rows),
            "valid_midpoint_rate_sensitivity": sum(x["valid_midpoint_sensitivity"] > 0 for x in rows) / len(rows),
            "median_quote_age_seconds_primary": sorted(x["quote_age_seconds"] for x in rows if x["valid_midpoint_primary"])[len([x for x in rows if x["valid_midpoint_primary"]]) // 2],
            "median_relative_spread_primary": sorted(x["relative_spread"] for x in rows if x["valid_midpoint_primary"])[len([x for x in rows if x["valid_midpoint_primary"]]) // 2],
        },
        "pit_verdict": "NOT_VERIFIED_OPTION_STATE_SERIES",
        "primary_use": "BLOCKED_PENDING_PIT_AND_COMPLETE_ATM_SKEW_TERM_STRUCTURE",
        "prior_estimates_not_accepted": True,
    }
    (OUT / "b1_origin_coverage.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    iv = json.loads((ROOT / "artifacts/api_audit/b1_coverage_v1_20260721/iv_probe.json").read_text())
    robustness = {
        "status": "exploratory_iv_probe_not_acceptance_gate",
        "source_artifact": "artifacts/api_audit/b1_coverage_v1_20260721/iv_probe.json",
        "filters": iv["filters"],
        "attempts": iv["IV_inversion_attempts"], "successes": iv["IV_inversion_successes"],
        "success_rate": iv["IV_inversion_success_rate"], "failure_reason": iv["failure_reason"],
        "iv_range": iv["iv_range"], "rate_source": iv["rate_source"],
        "dividend_source": iv["dividend_source"],
        "interpretation": "This tests numerical inversion only; it does not prove point-in-time publication or complete B1 state.",
        "secret_values_emitted": False,
    }
    (OUT / "iv_robustness.json").write_text(json.dumps(robustness, indent=2), encoding="utf-8")

    profile = json.loads((ROOT / "artifacts/raw/full_tape/2026-07-16/profile_2026-07-16.json").read_text())
    pit = {
        "status": "PIT_EVENT_TIME_VERIFIED_FOR_FULL_TAPE_SAMPLE",
        "sample_date": "2026-07-16", "event_time": "executed_at",
        "vendor_record_time": "created_at", "primary_cutoff": "created_at <= forecast_origin - 60 seconds",
        "sensitivity_cutoffs": {"sensitivity_15s": "created_at <= origin - 15 seconds", "sensitivity_0s": "created_at <= origin"},
        "negative_latency_count": profile["created_minus_executed_seconds"]["negative_count"],
        "latency_seconds": profile["created_minus_executed_seconds"],
        "duplicate_id_rows": profile["duplicate_id_rows"], "malformed_rows": profile["malformed_rows"],
        "order_regressions": profile["order_regressions"],
        "out_of_regular_session_rows": profile["out_of_regular_session_utc_13_30_20_00"],
        "implied_volatility_missing": profile["missing_counts"].get("implied_volatility", 0),
        "full_tape_primary_ready": True,
        "flow_alerts_primary": False,
    }
    (OUT / "pit_results.json").write_text(json.dumps(pit, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
