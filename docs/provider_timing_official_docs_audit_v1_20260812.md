# Official provider-timing documentation audit v1

## Scope and status

`PASS_LIMITATIONS_RECORDED_NO_PIT_SEMANTICS_UPGRADE`

This target-blind audit records only documentation inspected on 12 August 2026.
It made no authenticated provider-data request and did not read RV30, forecasts,
QLIKE, models, predictive results, or OOS data. Its machine-readable, self-hashed
record is `artifacts/provider_timing_v21/official_docs_audit_v1_20260812.json`:
`b8bdd43a0842b1d3941151e3fb801dc86ec172a3d63bec619ed0bcac7b2857af`.

## What the official pages establish

| Provider | Official source | Supported fact | Not established |
|---|---|---|---|
| FMP | [1-minute chart documentation](https://site.financialmodelingprep.com/developer/docs/stable/intraday-1-min) | The response contains a `date` field formatted like `YYYY-MM-DD HH:mm:ss` alongside minute OHLCV. | Time zone, whether the label marks bar start or close, and historical customer availability. |
| Unusual Whales | [Flow Alerts](https://api.unusualwhales.com/docs/operations/PublicApi.OptionTradeController.flow_alerts), [Full Tape](https://api.unusualwhales.com/docs/operations/PublicApi.OptionTradeController.full_tape), [Option Trades](https://api.unusualwhales.com/docs/operations/PublicApi.OptionTradeController.index) | Flow Alerts label `created_at` only as a general UTC timestamp. The current-day Option Trades example includes `executed_at`; Full Tape is documented as a historical ZIP by trading date. | That historical `created_at` is publication, receipt, or customer availability time. |
| Massive | [historical option quotes](https://massive.com/docs/rest/options/quotes) | `sip_timestamp` is documented as a nanosecond SIP Unix timestamp for receipt of the quote from its exchange; sequence numbers are unique per ticker. | Historical REST delivery to the customer before a forecast origin. |

## Historical source availability is separate

The study does have historical sources. This is not a data-availability block:

| Provider | Registered evidence | Historical availability conclusion | Boundary retained |
|---|---|---|---|
| FMP | `artifacts/api_audit/b2_replication_90_common_probe.json` (SHA-256 `97c3b57707a953629ff57e485cde918e52ecdd1777a246e84072b5c4150771dc`) | `PASS_90_OF_90_SESSIONS` | It does not determine whether the returned timestamp marks a bar's start or close, time zone, or customer delivery time. |
| Unusual Whales | `artifacts/api_audit/b2_replication_90_uw_metadata_probe.json` (SHA-256 `244690e15054f518e5d12083e6b81d2bcbfcd8f5f009304f4127cbb5c1c4a3f3`) | `PASS_90_OF_90_FILE_METADATA` | File metadata availability is not a row-level point-in-time claim; the probe intentionally did not download those 90 Full Tape ZIPs. |

Thus `HISTORICAL_SOURCE_AVAILABILITY=PASS` and
`PIT_TIMESTAMP_SEMANTICS=UNVERIFIED` are distinct statuses. The latter is a
timing-validity condition, not an assertion that either provider lacks history.

## Consequence for the study

- FMP remains `timestamp_raw + 1 minute` primary and `+2 minutes` sensitivity:
  conservative study rules, not provider-confirmed bar semantics.
- UW `created_at` remains an operational availability proxy only. It must not be
  renamed to publication or receipt time.
- Massive permits the technical as-of quote rule used by the reselection audit,
  but does not prove customer-side historical delivery latency.

Therefore this audit does not change either gate:

```text
SAFE_TO_RECONCILE_EXISTING_RESULTS = NO
SAFE_TO_OPEN_OR_EVALUATE_OOS = NO
```

The only routes that could change those claims are independent provider evidence
with explicit availability semantics or a prospectively operated receipt logger.
