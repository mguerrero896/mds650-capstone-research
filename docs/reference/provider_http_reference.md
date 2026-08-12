# Provider HTTP reference (FMP, Unusual Whales, Massive)

Verified against official provider documentation on 2026-07-21 and against the
authenticated audit run `25a82e51` (artifacts/api_audit/authenticated_v1s/),
where every call pattern below returned HTTP 200 except where noted.

**Key fact for agents: call syntax must be checked against the provider contract.**
The v1s probe had incorrect historical UW parameter names and non-canonical auth
placement for FMP/Massive; v1v/v1w corrected and revalidated them. A 403 may be
an entitlement limit, but only after endpoint, parameter names and authentication
are validated.

---

## 1. Financial Modeling Prep (FMP)

- Base URL: `https://financialmodelingprep.com`
- Auth: FMP documents both query `?apikey=YOUR_KEY` (`&apikey=` if other
  parameters exist) and header `apikey: YOUR_KEY`. Phase 5 uses the query form
  so the sanitized request manifest can record the non-secret parameters.
- Do NOT use `Authorization: Bearer` with FMP — it is not a documented form.
- Example (1-minute intraday bars):
  `GET https://financialmodelingprep.com/stable/historical-chart/1min?symbol=AAPL&apikey=YOUR_KEY`.
  Newer "stable" paths live under
  `/stable/...` (e.g. `/stable/earnings-calendar`).
- The official 1-minute viewer also documents date-bounded `from`/`to` inputs
  and `extended` / `nonadjusted` flags. It does **not** document timezone,
  whether `date` labels a bar open or close, range-bound inclusivity, regular
  session defaults, or REST publication latency. Therefore an exact date request
  is not a PIT semantics confirmation; retain the registered +1 minute rule
  and +2 minute sensitivity.
- Error semantics: 401 = bad/missing key; 403 = endpoint not in plan
  (earnings calendar and long history are premium-tier datasets).
- MEASURED DEPTH (2026-07-21, `scripts/window_probe_v1.py`): 1-min AAPL bars
  returned 390 rows at 7/90/180/365/730 days back — intraday history verified
  to at least 2 years. The 2026-06-19 probe returned 200 with 0 rows because
  that was the Juneteenth market holiday — a valid empty session, not a gap.

## 2. Unusual Whales

- Base URL: `https://api.unusualwhales.com`
- Auth: `Authorization: Bearer YOUR_KEY` (+ `Accept: application/json`).
- Machine-readable spec: `GET https://api.unusualwhales.com/api/openapi`
  (OpenAPI YAML). Docs pages: https://api.unusualwhales.com/docs
- Endpoints used here:
  - `GET /api/option-trades/flow-alerts` — params include `ticker_symbol`,
    `min_premium`, `newer_than` / `older_than` (unix ms/sec or ISO date),
    `limit` (default 100, max 200), plus many filter flags.
  - `GET /api/option-trades/full-tape/{date}` — a documented market-date
    (`YYYY-MM-DD`) download returning `application/zip`; the public OpenAPI
    describes data since 2022-01-01 subject to plan lookback. The documentation
    does **not** establish `Range`, `HEAD`, `206`, `Content-Range`, resumable
    transfer, or streaming semantics. A future preflight must therefore use
    only the documented ZIP download route, never an undocumented range probe.
  - `GET /api/stock/{ticker}/volatility/term-structure`
- Pagination: time-window pagination via `newer_than` / `older_than`; the
  corrected auditor advances the lower time boundary and checks page IDs.
- KNOWN ENTITLEMENT LIMIT (observed 2026-07-21): the accepted probe boundary
  was 2023-08-18 (valid 200/0); 2023-08-17 returned 403 and is recorded as an
  expected unsupported boundary. The oldest non-empty event date observed was
  2024-08-02. A 403 here means "not in plan" only after the request contract
  is valid; a bad key returns 401.
- INDEPENDENTLY CONFIRMED 2026-07-21 by `scripts/window_probe_v1.py` (binary
  search, artifacts/api_audit/window_probe_20260720/): oldest entitled day =
  **2023-08-18** (1,067 days back). A 12-month study window fits inside the
  entitlement with wide margin.

## 3. Massive (formerly Polygon.io)

- Polygon.io rebranded to Massive on 2025-10-30. Base URL:
  `https://api.massive.com` (old `api.polygon.io` still works during the
  transition; prefer massive.com). Override via `MDS650_MASSIVE_BASE_URL`.
- Auth: canonical documented form is query param `?apiKey=YOUR_KEY` (camelCase
  `apiKey`, unlike FMP). The corrected auditor uses this form.
- Endpoints used here (all returned 200 in audit):
  - `GET /v3/reference/options/contracts/{contract_id}` — contract metadata;
    options tickers use the `O:` prefix (e.g. `O:AAPL240119C00190000`).
  - `GET /v3/trades/{contract_id}` — historical trades.
  - `GET /v3/quotes/{contract_id}` — historical quotes (NBBO).
- MDS650 directed-quote contract: use the forecast-origin timestamp as a
  positive, exactly 19-digit integer nanosecond value. The client rejects
  booleans, strings/ISO timestamps, nonpositive values, and other precisions
  before transport, then sends
  `timestamp.lte=<forecast_origin_ns>&sort=timestamp&order=desc&limit=1`.
  Sanitized request records exclude `apiKey`.
- The official quote reference lists `timestamp.lte` / `.gte` range filters and
  accepts a nanosecond timestamp. The client must still validate locally that
  every retained `sip_timestamp <= forecast_origin`; provider event time does
  not prove customer receipt latency or historical PIT availability.
- Pagination: responses include `next_url`; follow it with the same query
  authentication (the audit script already does this via `next_path`).
- Docs: https://massive.com/docs/rest/quickstart — every docs page has a
  Markdown version and there is an `llms.txt` for agents.
- Empty result windows return 200 with `results: []` — that is a valid
  response (e.g. quote windows before the contract listed), not an error.
- PLAN SCOPE (measured 2026-07-21): expired 2017 options contract reference
  returned 200, but 2015 STOCK minute aggregates (`/v2/aggs/...`) returned
  **403** — the plan is options-scoped. Use FMP for underlying minute bars;
  do not add Massive stock-aggregate calls without a new entitlement check.

---

## Error triage cheat-sheet

| Status | Meaning | Action |
|--------|---------|--------|
| 401 | key missing/invalid | check env var loading, never print the key |
| 403 | endpoint or date range not in the subscription plan | record entitlement only after validating auth and parameters |
| 422 | bad parameter shape | fix params against the tables above |
| 429 | rate limited | honor `Retry-After` header |
| 200 + empty list | valid empty window | treat as data, not failure |

Env vars (presence-only, never commit values): `FMP_API_KEY`,
`UNUSUALWHALES_API_KEY`, `MASSIVE_API_KEY` — loaded via `src/mds650/config.py`.

Sources: [FMP docs](https://site.financialmodelingprep.com/developer/docs),
[FMP FAQs](https://site.financialmodelingprep.com/faqs),
[FMP 1-min endpoint](https://site.financialmodelingprep.com/developer/docs/stable/intraday-1-min),
[Unusual Whales API docs](https://api.unusualwhales.com/docs),
[UW flow-alerts operation](https://api.unusualwhales.com/docs/operations/PublicApi.OptionTradeController.flow_alerts),
[UW developers page](https://unusualwhales.com/public-api),
[Polygon is now Massive](https://massive.com/blog/polygon-is-now-massive),
[Massive REST quickstart](https://massive.com/docs/rest/quickstart).
