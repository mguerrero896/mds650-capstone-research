"""Verify whether retained Unusual Whales option-state payloads are PIT usable."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

RAW_ROOT = Path("data/raw/unusual_whales")
OUT = Path("artifacts/api_audit/pit_verification_20260721")
PROBES = (
    "uw-ordinary-term-structure-recent-aapl",
    "uw-ordinary-term-structure-old-aapl",
    "uw-ordinary-skew-recent-aapl",
    "uw-ordinary-skew-old-aapl",
)


def _payload_path(prefix: str) -> Path | None:
    matches = sorted(RAW_ROOT.glob(f"*{prefix}/payload.bin"))
    return matches[0] if matches else None


def _records(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        return []
    return [row for row in payload["data"] if isinstance(row, dict)]


def verify() -> dict[str, Any]:
    """Return an evidence-derived PIT status without making network requests."""
    inspected: list[dict[str, Any]] = []
    has_independent_availability = True
    for probe in PROBES:
        path = _payload_path(probe)
        if path is None:
            inspected.append({"probe": probe, "status": "missing_payload"})
            has_independent_availability = False
            continue
        payload = json.loads(path.read_bytes())
        rows = _records(payload)
        fields = sorted({field for row in rows for field in row})
        publication_fields = sorted(
            field
            for field in fields
            if field.lower() in {"available_at", "published_at", "created_at", "as_of"}
        )
        if not publication_fields:
            has_independent_availability = False
        inspected.append(
            {
                "probe": probe,
                "payload_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "rows": len(rows),
                "fields": fields,
                "publication_or_availability_fields": publication_fields,
                "market_date_fields_only": "date" in fields and not publication_fields,
            }
        )
    status = "PASS" if inspected and has_independent_availability else "INFEASIBLE"
    return {
        "schema_version": "pit-verification-1.0",
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "source": "retained raw Unusual Whales option-state payloads",
        "b1_status": status,
        "ordinary_option_state_pit_verified": status == "PASS",
        "fallback_comparison": None if status == "PASS" else "B2-vs-B0",
        "independent_publication_timestamp_required": True,
        "inspected_payloads": inspected,
        "decision": (
            "ordinary IV/skew/term-structure fields are available, but retained payloads "
            "contain market dates without an independent publication/availability timestamp; "
            "B1 is infeasible and B2-vs-B0 is the only permitted fallback."
            if status != "PASS"
            else "independent publication/availability timestamps were verified"
        ),
    }


def main() -> int:
    """Write the sanitized PIT decision and a human-readable companion report."""
    result = verify()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "pit_verification.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (OUT / "README.md").write_text(
        "# PIT verification\n\n"
        f"- B1 status: `{result['b1_status']}`\n"
        f"- Ordinary option-state PIT verified: `{result['ordinary_option_state_pit_verified']}`\n"
        f"- Fallback: `{result['fallback_comparison']}`\n\n"
        f"{result['decision']}\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                k: result[k]
                for k in ("b1_status", "ordinary_option_state_pit_verified", "fallback_comparison")
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
