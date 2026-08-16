"""Integrate existing IV inversion results by forecast origin for Pilot V2."""
# ruff: noqa: E501,E702,B007

from __future__ import annotations

import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(".")
OUT = ROOT / "artifacts" / "pilot_v2"


def bucket(dte: int) -> str | None:
    if 7 <= dte <= 21:
        return "short"
    if 30 <= dte <= 60:
        return "medium"
    if 90 <= dte <= 180:
        return "long"
    return None


def main() -> None:
    matrix = json.loads((ROOT / "artifacts/api_audit/b1_coverage_v1_20260721/matrix_exact.json").read_text())
    iv_payload = json.loads((ROOT / "artifacts/api_audit/b1_coverage_v1_20260721/iv_probe.json").read_text())
    iv_rows = iv_payload["rows"]
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in iv_rows:
        groups[(row["asset"], row["origin"])].append(row)
    matrix_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in matrix["rows"]:
        matrix_groups[(row["asset"], row["origin_utc"])].append(row)
    output: list[dict[str, Any]] = []
    for (asset, origin), items in sorted(matrix_groups.items()):
        iv = groups.get((asset, origin), [])
        successes = [x for x in iv if x.get("iv") is not None]
        buckets = {bucket(int(x["dte"])) for x in successes if bucket(int(x["dte"]))}
        medium = [x for x in successes if bucket(int(x["dte"])) == "medium"]
        atm = [x for x in medium if abs(float(x["strike"]) / float(x["spot"]) - 1) <= 0.025]
        sides = {x["option_type"] for x in medium if abs(float(x["strike"]) / float(x["spot"]) - 1) >= 0.01}
        output.append({
            "asset": asset, "origin_utc": origin, "date": origin[:10],
            "hour": origin[11:16], "atm_iv_available": bool(atm),
            "skew_available": {"call", "put"}.issubset(sides),
            "term_structure_available": len(buckets) >= 2,
            "b1a_complete": bool(atm), "b1b_complete": bool(atm) and {"call", "put"}.issubset(sides),
            "b1c_complete": bool(atm) and {"call", "put"}.issubset(sides) and len(buckets) >= 2,
            "iv_contract_count": len({x["contract"] for x in successes}),
            "iv_inversion_attempts": len(iv), "iv_inversion_successes": len(successes),
            "valid_expiry_bucket_count": len(buckets),
            "valid_moneyness_count": len({round(float(x["strike"]) / float(x["spot"]), 3) for x in successes}),
            "median_quote_age_seconds": statistics.median([x["quote_age_seconds"] for x in successes if x.get("quote_age_seconds") is not None]) if successes else None,
            "median_relative_spread": statistics.median([x["relative_spread"] for x in successes if x.get("relative_spread") is not None]) if successes else None,
            "quote_selection": "corrected_per_origin_controlled_for_AAPL; historical_matrix_rows_retained_as_exploratory",
            "usable_for_primary": False,
        })
    all_successes = [x for x in iv_rows if x.get("iv") is not None]
    summary = {
        "status": "PILOT_V2_B1_PER_ORIGIN_EXPLORATORY",
        "source_iv_artifact": "artifacts/api_audit/b1_coverage_v1_20260721/iv_probe.json",
        "source_matrix_artifact": "artifacts/api_audit/b1_coverage_v1_20260721/matrix_exact.json",
        "controlled_probe": "artifacts/pilot_v2/massive_controlled_origin_probe.json",
        "origin_count": len(output),
        "b1a_origins": sum(int(bool(x["b1a_complete"])) for x in output),
        "b1b_origins": sum(int(bool(x["b1b_complete"])) for x in output),
        "b1c_origins": sum(int(bool(x["b1c_complete"])) for x in output),
        "iv_attempts": len(iv_rows), "iv_successes": len(all_successes),
        "iv_failures": [x for x in iv_rows if x.get("iv") is None],
        "primary_use": "BLOCKED_UNTIL_EIGHT_ASSET_PER_ORIGIN_QUOTE_REEXTRACTION_AND_PIT_ACCEPTANCE",
        "rows": output,
    }
    (OUT / "b1_origin_coverage_v2.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    with (OUT / "b1_component_coverage_v2.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(output[0]))
        writer.writeheader(); writer.writerows(output)
    robustness = {
        "status": "PILOT_V2_IV_ROBUSTNESS_INTEGRATED",
        "attempts": len(iv_rows), "successes": len(all_successes), "failures": summary["iv_failures"],
        "failure_count": len(iv_payload["rows"]) - len(all_successes),
        "failure_reason_from_source": iv_payload.get("failure_reason", {}),
        "breakdowns": {
            "asset": {a: sum(x["asset"] == a and x.get("iv") is not None for x in iv_rows) for a in sorted({x["asset"] for x in iv_rows})},
            "option_type": {t: sum(x["option_type"] == t and x.get("iv") is not None for x in iv_rows) for t in sorted({x["option_type"] for x in iv_rows})},
        },
        "bsm_note": "Black-Scholes-Merton inversion is an approximation for American options.",
        "future_rates_or_dividends_used": False,
        "source": "retained exploratory IV rows integrated by origin; controlled quote extraction is separate",
    }
    (OUT / "iv_robustness_v2.json").write_text(json.dumps(robustness, indent=2), encoding="utf-8")
    print(json.dumps({"origins": len(output), "b1a": summary["b1a_origins"], "b1b": summary["b1b_origins"], "b1c": summary["b1c_origins"], "iv_successes": len(all_successes)}))


if __name__ == "__main__":
    main()
