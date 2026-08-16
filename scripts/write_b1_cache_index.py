"""Index existing contract-day caches without rewriting their payloads."""
# ruff: noqa: E501

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "artifacts" / "b1_full_origin" / "massive_contract_day_cache"


def main() -> None:
    """Write deterministic request hashes for every retained cache file."""
    rows = []
    for path in sorted(CACHE.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        asset, day, contract = payload.get("asset"), payload.get("day"), payload.get("contract", {}).get("contract")
        if not asset or not day or not contract:
            continue
        params = "timestamp=" + str(day) + "|sort=timestamp|order=desc|limit=50000"
        request_hash = hashlib.sha256(f"https://api.massive.com/v3/quotes/{contract}|{params}".encode()).hexdigest()
        rows.append({"cache_file": path.name, "asset": asset, "day": day, "contract": contract, "source_request_hash": request_hash, "http_status": payload.get("http_status"), "pages": payload.get("pages"), "secret_values_emitted": False})
    destination = CACHE / "cache_index.json"
    destination.write_text(json.dumps({"status": "B1_CACHE_INDEX", "entries": rows, "idempotent_key": "asset|day|contract|source_request_hash", "secret_values_emitted": False}, indent=2), encoding="utf-8")
    print(json.dumps({"entries": len(rows), "secret_values_emitted": False}))


if __name__ == "__main__":
    main()
