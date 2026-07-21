"""Empirically measure each provider's usable historical window.

Evidence-first: bounded, deterministic probes (~25 requests total) that answer
one question per provider:

  1. Unusual Whales: oldest calendar day for which /api/option-trades/flow-alerts
     is ENTITLED (200) vs plan-blocked (403), found by binary search.
  2. FMP: how far back /api/v3/historical-chart/1min returns non-empty data.
  3. Massive: spot-check that deep options reference/quotes history responds.

Never prints or persists secret values. Results land in
artifacts/api_audit/window_probe_<UTC date>/ as JSON + markdown.

Run:  .venv/Scripts/python.exe scripts/window_probe_v1.py
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

import httpx

UTC = dt.UTC
TODAY = dt.datetime.now(UTC).date()
OUT_DIR = Path("artifacts/api_audit") / f"window_probe_{TODAY:%Y%m%d}"
SLEEP_S = 0.35
RECORDS: list[dict] = []


def _need(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        sys.exit(f"missing env var {name} (presence-only check; value never printed)")
    return value


def _get(
    client: httpx.Client, provider: str, purpose: str, url: str, headers: dict, params: dict
) -> tuple[int, int]:
    """One bounded GET. Returns (status, row_count). Records evidence, no secrets."""
    time.sleep(SLEEP_S)
    try:
        r = client.get(url, headers=headers, params=params)
        status = r.status_code
        rows = 0
        try:
            payload = r.json()
            for key in ("data", "results"):
                if isinstance(payload, dict) and isinstance(payload.get(key), list):
                    rows = len(payload[key])
                    break
            else:
                if isinstance(payload, list):
                    rows = len(payload)
        except ValueError:
            pass
    except httpx.HTTPError as exc:
        status, rows = -1, 0
        RECORDS.append(
            {
                "provider": provider,
                "purpose": purpose,
                "url": url,
                "params": {k: str(v) for k, v in params.items()},
                "status": status,
                "rows": rows,
                "error": type(exc).__name__,
            }
        )
        return status, rows
    RECORDS.append(
        {
            "provider": provider,
            "purpose": purpose,
            "url": url,
            "params": {k: str(v) for k, v in params.items()},
            "status": status,
            "rows": rows,
        }
    )
    return status, rows


def probe_uw(client: httpx.Client, key: str) -> dict:
    """Binary-search the oldest ENTITLED day for flow-alerts (403 boundary)."""
    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    url = "https://api.unusualwhales.com/api/option-trades/flow-alerts"

    def day_allowed(day: dt.date) -> tuple[bool, int]:
        params = {
            "newer_than": f"{day.isoformat()}T00:00:00Z",
            "older_than": f"{(day + dt.timedelta(days=1)).isoformat()}T00:00:00Z",
        }
        status, rows = _get(
            client, "unusual_whales", f"flow-alerts day {day}", url, headers, params
        )
        return status == 200, rows

    lo = dt.date(2023, 8, 16).toordinal()  # known blocked (403) in audit 25a82e51
    hi = TODAY.toordinal()  # known allowed
    ok, _ = day_allowed(dt.date.fromordinal(lo))
    if ok:
        lo_allowed = dt.date.fromordinal(lo)  # plan deeper than expected
    else:
        while hi - lo > 1:
            mid = (lo + hi) // 2
            ok, _ = day_allowed(dt.date.fromordinal(mid))
            if ok:
                hi = mid
            else:
                lo = mid
        lo_allowed = dt.date.fromordinal(hi)
    return {
        "oldest_entitled_day": lo_allowed.isoformat(),
        "days_back_from_today": (TODAY - lo_allowed).days,
        "note": "day D allowed == HTTP 200 for newer_than=D, older_than=D+1; "
        "403 == plan-blocked. rows may be 0 on allowed days.",
    }


def probe_fmp(client: httpx.Client, key: str) -> dict:
    """Find how far back 1-min bars return non-empty data (plan depth)."""
    headers = {"apikey": key}
    depths = [7, 30, 90, 180, 365, 730]
    results = {}
    deepest_nonempty = None
    for days_back in depths:
        day = TODAY - dt.timedelta(days=days_back)
        while day.weekday() >= 5:  # shift weekend to Friday
            day -= dt.timedelta(days=1)
        url = "https://financialmodelingprep.com/api/v3/historical-chart/1min/AAPL"
        status, rows = _get(
            client,
            "fmp",
            f"1min depth {days_back}d",
            url,
            headers,
            {"from": day.isoformat(), "to": day.isoformat()},
        )
        results[f"{days_back}d"] = {"date": day.isoformat(), "status": status, "rows": rows}
        if status == 200 and rows > 0:
            deepest_nonempty = days_back
    return {"per_depth": results, "deepest_nonempty_days": deepest_nonempty}


def probe_massive(client: httpx.Client, key: str) -> dict:
    """Spot-check deep options reference + quotes and 2015 stock minute bars."""
    headers = {"Authorization": f"Bearer {key}"}
    base = os.environ.get("MDS650_MASSIVE_BASE_URL", "https://api.massive.com")
    out: dict = {}
    status, rows = _get(
        client,
        "massive",
        "expired 2017 contract reference",
        f"{base}/v3/reference/options/contracts",
        headers,
        {
            "underlying_ticker": "AAPL",
            "expiration_date.lte": "2017-12-31",
            "expired": "true",
            "limit": 1,
        },
    )
    out["reference_2017"] = {"status": status, "rows": rows}
    status, rows = _get(
        client,
        "massive",
        "2015 minute aggregates AAPL",
        f"{base}/v2/aggs/ticker/AAPL/range/1/minute/2015-01-05/2015-01-05",
        headers,
        {"limit": 5},
    )
    out["stock_minute_2015"] = {"status": status, "rows": rows}
    return out


def main() -> None:
    uw_key = _need("UNUSUALWHALES_API_KEY")
    fmp_key = _need("FMP_API_KEY")
    massive_key = _need("MASSIVE_API_KEY")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    with httpx.Client(timeout=25.0) as client:
        uw = probe_uw(client, uw_key)
        fmp = probe_fmp(client, fmp_key)
        massive = probe_massive(client, massive_key)

    summary = {
        "generated_at_utc": dt.datetime.now(UTC).isoformat(),
        "request_count": len(RECORDS),
        "unusual_whales": uw,
        "fmp": fmp,
        "massive": massive,
        "secret_values_emitted": False,
    }
    (OUT_DIR / "probe_results.json").write_text(
        json.dumps({"summary": summary, "requests": RECORDS}, indent=2), encoding="utf-8"
    )

    md = [
        f"# Provider window probe {TODAY:%Y-%m-%d}",
        "",
        f"- Requests made: {len(RECORDS)} (bounded)",
        f"- Unusual Whales flow-alerts oldest ENTITLED day: **{uw['oldest_entitled_day']}**"
        f" ({uw['days_back_from_today']} days back from today)",
        f"- FMP 1-min deepest non-empty probe: **{fmp['deepest_nonempty_days']} days back**"
        " (see per-depth table in JSON)",
        f"- Massive expired-2017 options reference: HTTP {massive['reference_2017']['status']},"
        f" rows={massive['reference_2017']['rows']}",
        f"- Massive 2015 stock minute bars: HTTP {massive['stock_minute_2015']['status']},"
        f" rows={massive['stock_minute_2015']['rows']}",
        "",
        "Interpretation: the event-window for UW-dependent components is bounded by the",
        "oldest entitled day above; price/quote history from Massive/FMP extends further.",
    ]
    (OUT_DIR / "probe_summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
