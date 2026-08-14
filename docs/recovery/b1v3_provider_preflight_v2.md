# B1v3 provider preflight v2 — authenticated closure

Date: 2026-08-14
Scope: target-blind provider availability for the frozen 60-training/30-confirmation candidate.

## Decision

`T222 = PASS_PROVIDER_PREFLIGHT_ASSUMPTION_BOUND`

The result authorizes acquisition of predictor inputs only. It does not authorize target access,
model fitting, QLIKE calculation, or a scientific edge claim.

| Gate | Result | Evidence |
|---|---:|---|
| FMP exact-session OHLCV | 720/720 asset-days | 90 sessions × 8 assets; extra dates excluded |
| Unusual Whales Full Tape transport | 90/90 sessions | Documented GET; ZIP headers only; no ZIP body downloaded |
| Massive historical contract/quote availability | 720/720 asset-days | Contract search `as_of`, contract overview `as_of`, and quote SIP at/before origin |
| Massive primary B1 filter | 698/720 | Diagnostic coverage only: age ≤60 s and relative spread ≤25% |
| Massive sensitivity filter | 716/720 | Diagnostic coverage only: age ≤300 s and relative spread ≤50% |
| Samsung data-volume gate | PASS | 417,795,866,624 bytes free at execution; minimum 85,899,345,920 bytes |
| Secret/personal-path scan | PASS | 10 compact artifacts scanned; zero value hits and zero personal-path hits |

Massive primary-filter coverage by asset was AAPL 84/90, AMZN 86/90, META 86/90,
MSFT 82/90, and 90/90 for NVDA, QQQ, SPY and TSLA. A technically valid quote older than
60 seconds proves historical endpoint/contract availability but remains missing for primary B1.
No quote is imputed and no earlier valid quote replaces an invalid last quote.

## Corrected defects, without deleting evidence

1. The first smoke resolved a historical contract but requested its detail without `as_of`.
   Massive therefore applied today's default and returned 404. The corrected request sends the
   session date as `as_of`; the old 404 report remains under `smoke/`.
2. The first full run searched 7–180 DTE and ±10% moneyness, causing the three-page cap to fail
   for 95 asset-days. The preflight contract requires only one ATM 30–60 DTE contract, so the
   query was narrowed to 30–60 DTE and 0.975–1.025 spot moneyness. Both blocked reports remain
   under `blocked/`.
3. The original validator conflated source availability with the downstream 60-second/25%
   coverage rule. These are now separate fields: `pass` is technical provider availability,
   while `primary_filter_pass` and `sensitivity_filter_pass` remain explicit coverage flags.

Official contracts used:

- FMP 1-minute chart: `GET /stable/historical-chart/1min` with exact `from`/`to` date.
- Unusual Whales Full Tape: `GET /api/option-trades/full-tape/{date}` with Bearer auth and no
  undocumented Range/HEAD behavior.
- Massive all contracts: <https://massive.com/docs/rest/options/contracts>
- Massive contract overview with `as_of`:
  <https://massive.com/docs/rest/options/contracts/contract-overview>
- Massive historical quotes: <https://massive.com/docs/rest/options/trades-quotes/quotes>

## Timing boundary

- FMP `timestamp_raw + 1 minute` remains a conservative research assumption; `+2 minutes` is a
  registered sensitivity. Provider publication timing is not claimed.
- UW `created_at` remains an operational availability proxy, not publication time.
- Massive `sip_timestamp` is SIP source receipt time, not REST client receipt/publication time.
- Consequently `pit_semantics_confirmed=false` remains correct even though the availability
  preflight passed.

## Reproducibility

Primary command:

```powershell
uv run python scripts\run_date_level_pit_preflight_v2.py --execute
```

The commercial response cache is immutable and external on `D:`. The compact Git report is
`artifacts/b1v3_provider_preflight_v2/provider_preflight_report.json`, file SHA-256
`24c071351cb80d1a2dc758849775b2918831dde42b9e3e1d4701aba4e0701d9f`. Its semantic self-hash
and Draft 2020-12 schema both validate. A cache-only replay produced the same scientific state.

At closure the external cache contained 5,311 files using 151.24 MiB, while D: retained
388.73 GiB free. No Full Tape ZIP body was downloaded in this task.

## Remaining gate

`safe_to_acquire_predictors=true`; `safe_to_read_outcomes=false`. T223 must build a new
source-bound predictor-only panel and represent the 22 primary-filter failures as missingness.
It must not open RV30, QLIKE, predictions, model results or the confirmation outcomes.
