"""Global multiplicity correction across the post-null registered contrasts.

Roadmap 4.4 completed: a single Holm step-down across every registered
outcome-bearing contrast evaluated after the prospective C2 null, using the
Gate-1 studentized wild-bootstrap p-values (the C2 contrasts themselves anchor
the family as the confirmatory reference and are included). Exploratory
decision-56 contrasts (gates 10-12) are enumerated but corrected in their own
separate family, so the registered family is not diluted by exploration.
Conservative by construction (the sequence was data-dependent, so no
retrospective correction is exact — stated in the artifact).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from mds650.metrics import holm_adjust

REPO = Path(__file__).resolve().parents[1]
GATE1 = REPO / "artifacts" / "gate1_inference" / "results.json"
GATE11 = REPO / "artifacts" / "gate11_era_map" / "results.json"
GATE12 = REPO / "artifacts" / "gate12_harq_hardening" / "results.json"
OUTPUT = REPO / "artifacts" / "global_multiplicity"


def _collect_gate1() -> dict[str, float]:
    payload = json.loads(GATE1.read_text(encoding="utf-8"))
    p_values: dict[str, float] = {}
    for campaign, campaign_entry in payload["campaigns"].items():
        for block, block_entry in campaign_entry["blocks"].items():
            prefix = campaign if block == "all" else f"{campaign}[{block}]"
            for contrast, stats in block_entry["contrasts"].items():
                p_values[f"{prefix}|{contrast}"] = float(stats["wild_rademacher"]["p_value"])
    return p_values


def _collect_exploratory() -> dict[str, float]:
    p_values: dict[str, float] = {}
    era_map = json.loads(GATE11.read_text(encoding="utf-8"))
    for era, entry in era_map["eras"].items():
        for key, stats in entry["contrasts"].items():
            p_values[f"gate11|{era}|{key}"] = float(stats["p_wild"])
    hardening = json.loads(GATE12.read_text(encoding="utf-8"))
    for era, entry in hardening["design_a_panel_har"].items():
        for family in ("log_ols", "lightgbm"):
            for key, stats in entry[family].items():
                p_values[f"gate12|{era}|{family}|{key}"] = float(stats["p_wild"])
    for key, stats in hardening["design_b_true_harq_dev"]["log_ols"].items():
        p_values[f"gate12|dev_harq|log_ols|{key}"] = float(stats["p_wild"])
    return p_values


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    registered = _collect_gate1()
    exploratory = _collect_exploratory()
    registered_adjusted = holm_adjust(registered)
    exploratory_adjusted = holm_adjust(exploratory)
    survivors = {
        name: value for name, value in registered_adjusted.items() if value < 0.05
    }
    results: dict[str, Any] = {
        "schema_version": "global-multiplicity-v1.0",
        "note": (
            "Single Holm family across all registered post-null contrasts (wild "
            "bootstrap p-values from Gate 1). Conservative bound only: the campaign "
            "sequence was data-dependent, so no retrospective correction is exact; "
            "the clean answer remains the prospective reads. The mechanism search's "
            "25 discarded variants and C3's sign-bootstrap aggregates have no "
            "studentized p-values and are enumerated, not corrected."
        ),
        "registered_family_size": len(registered),
        "enumerated_uncorrectable": {"mechanism_search_variants": 25, "c3_sign_bootstrap": 4},
        "registered_holm": dict(sorted(registered_adjusted.items(), key=lambda kv: kv[1])),
        "registered_survivors_at_5pct": dict(sorted(survivors.items(), key=lambda kv: kv[1])),
        "exploratory_family_size": len(exploratory),
        "exploratory_holm_survivors_at_5pct": {
            name: value
            for name, value in sorted(exploratory_adjusted.items(), key=lambda kv: kv[1])
            if value < 0.05
        },
    }
    payload = json.dumps(results, indent=1, sort_keys=False)
    (OUTPUT / "results.json").write_text(payload, encoding="utf-8")
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    (OUTPUT / "results.sha256").write_text(digest + "\n", encoding="utf-8")
    print(
        f"[holm] registered family={len(registered)} survivors={len(survivors)}; "
        f"exploratory family={len(exploratory)} "
        f"survivors={len(results['exploratory_holm_survivors_at_5pct'])}"
    )
    print(f"[holm] wrote {OUTPUT / 'results.json'} sha256={digest[:16]}")


if __name__ == "__main__":
    main()
