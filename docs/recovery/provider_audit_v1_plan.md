# Provider audit v1 plan

This is a bounded, authenticated plan only. It must run after secret rotation and
presence-only validation and must produce sanitized evidence without backfill.

## Executed bounded probe

Run `08a704db-8fe3-41a9-aa74-776111e63936` completed on 2026-07-20. All three required
secret variables were present by name only; no values were logged or written to the repository.
The machine-readable manifest is
`artifacts/api_audit/authenticated_v1/provider_audit_manifest.json` and the human summary is
`artifacts/api_audit/authenticated_v1/provider_audit_summary.md`. The manifest contains 43
provider-result records, schema version 1.1, request IDs, endpoint fingerprints, response hashes
and separate authentication/endpoint/schema/entitlement diagnostics.

Observed result: FMP minute and earnings probes returned HTTP 200 for all eight candidates;
FMP's bar timestamp start/close meaning, official-calendar completeness and missing-minute cause
remain unresolved. The depth probe recorded `2015-01-07 12:15:00` for AMZN and
`2015-01-07 12:34:00` for TSLA as candidates classified
`unclassified_provider_calendar_or_halt`; no interpolation was performed. FMP earnings responses
are symbol-checked and ETF applicability is `not_applicable` unless contrary evidence is found.

Unusual Whales returned event data for the eight candidates in recent/old/high-activity probes;
the schema exposes `iv_start` and `iv_end`, canonicalized from the historical camelCase aliases
`ivStart` and `ivEnd` in the contract map. `created_at`, `start_time` and `end_time` are recorded
separately. Event IV presence is `true`, while `ordinary_option_state_pit_verified` is `false`
and the ordinary option-state probe is `unsupported`; therefore B1 remains blocked. The cursor
probe also records `UW_PAGINATION_PAGE_REPEATED`; the QQQ empty-window candidate returned HTTP
403 rather than a valid empty response, so empty-response acceptance is not met.

Massive was limited to a contract returned by the event source. The reference probe returned HTTP
404 and directed trades and quotes returned HTTP 403. This is recorded as an entitlement/contract
format blocker, not as evidence to download historical OPRA quotes.

The v1 summary reports `B1: BLOCKED`, `Backfill: NOT_AUTHORIZED`, and
`common_history_status: NOT_ESTABLISHED`. These statuses are evidence gates, not implementation
failures to be hidden.

## Massive contract-format correction run

The first run used the raw Unusual Whales option-chain identifier and the legacy host, which
produced 404/403 responses. Official Massive endpoint examples require the OPRA-style `O:`
prefix and expose `/v3/reference/options/contracts/{optionsTicker}`, `/v3/trades/{optionsTicker}`
and `/v3/quotes/{optionsTicker}`. A bounded correction probe therefore used the exact
event-returned contract with the `O:` prefix and current `api.massive.com` host; it did not
expand the request to a market-wide quote download.

Contract-format evidence was checked against the current primary documentation for [Massive
options contracts](https://massive.com/docs/rest/options/contracts), [historical
trades](https://massive.com/docs/rest/options/trades-quotes/trades) and [historical
quotes](https://massive.com/docs/rest/options/trades-quotes/quotes).

Run `ad42fa59-d168-42e7-b5e3-2de0c1ce4701` is preserved separately at
`artifacts/api_audit/authenticated_v1c/provider_audit_manifest.json` (the preceding v1b run is
also retained). It records HTTP 200 for
reference, trades and quotes, one result per directed endpoint, request IDs, bid/ask fields,
condition codes and nanosecond SIP/participant timestamps. This resolves the earlier
host/contract-format diagnosis for the sampled contract and removes `MASSIVE_NOT_AUTHORIZED`
from this run's validator blockers. It does not prove entitlement for other contracts, complete
historical coverage, licensing for redistribution, or ordinary PIT IV/skew/term structure.

## Official Unusual Whales ordinary-state probe

The flow-alert endpoint is not the ordinary-state surface. The current OpenAPI contract exposes
`/api/stock/{ticker}/volatility/term-structure` and
`/api/stock/{ticker}/historical-risk-reversal-skew`. Run
`58824eef-1962-4bfd-aed3-a9614b842756` adds bounded requests for term structure on all eight
assets, recent and older term structure for AAPL, recent/older skew for AAPL, and bounded
oldest-date probes for AAPL (HTTP 200 for the 2023-08-17 request and HTTP 403 for the
2023-08-16 request). The response rows still expose a 2026-07-17 minimum event date, so
this is not evidence that 2023 data are actually returned; the true historical minimum
remains unresolved. The manifest
is preserved at `artifacts/api_audit/authenticated_v1j/provider_audit_manifest.json`.

The same run adds XNYS calendar diagnostics for winter, summer, DST and early-close windows.
The summer window records 2026-07-13 as an omitted session; the DST window records 2026-03-06
as an omitted session and 2026-03-09 15:19 as a minute candidate. These remain unclassified
provider/date-limit/calendar evidence, not a production completeness acceptance. Calendar-match
ratios explicitly assume local minute starts and therefore do not resolve FMP start-versus-close
semantics.

The immediately preceding v1i artifact is intentionally retained as a failed idempotency
fixture: its summer probe duplicated the regular SPY request hash, and the validator rejected
it with `AUDIT_MANIFEST_DUPLICATE_RAW_HASH`. v1j changes the bounded summer window, preserves
the evidence, and validates with zero duplicate hashes.

## Authenticated v1k refresh — 2026-07-21 (superseded by v1l)

After the owner supplied rotated secrets through the process-only PowerShell gate, run
`318a2ce0-972c-4673-862d-fb67bbc4facd` executed the same bounded audit without backfill. The
manifest is preserved at `artifacts/api_audit/authenticated_v1k/provider_audit_manifest.json`
and the human summary at `artifacts/api_audit/authenticated_v1k/provider_audit_summary.md`.
It contains 57 records, validates schema 1.1, is sanitized, and has no personal path or secret
content. Raw bytes are outside Git under the restricted local root used for this run.

The refresh confirms HTTP 200 FMP probes for all eight assets and HTTP 200 Massive reference,
trade and quote probes for one event-returned `O:` contract. It does not resolve FMP bar
start-versus-close semantics, the AMZN/TSLA missing-minute causes, independent Unusual Whales
publication availability, or common provider history. The validator reports
`B1_NOT_AUTHORIZED`, `COMMON_HISTORY_NOT_ESTABLISHED` and `PROVIDER_FAILURES_PRESENT`; backfill
remains unauthorized.

All eight recent term-structure requests returned HTTP 200 with volatility, expiry, date and
implied-move fields. Recent AAPL skew returned HTTP 200 with risk-reversal fields; the older AAPL
skew window returned HTTP 200 with a valid empty `data` array. These are ordinary-state field and
coverage observations, not PIT proof: the responses expose a market date but no independent
publication/availability timestamp, so `ordinary_option_state_pit_verified` remains
`false`, B1 remains blocked, and no look-ahead-safe B1 feature is authorized.

## Authenticated v1l refresh — 2026-07-21

After presence-only validation of the three process-scoped secrets, run
`6f91bc84-152d-4576-8a6e-506c3d4842a7` repeated the same bounded probes without
backfill. The manifest and summary are retained at
`artifacts/api_audit/authenticated_v1l/`; the manifest contains 57 records and validates
against schema 1.1. Its SHA-256 is
`CC46E110CAD266F2FC1703D169FCAF9BD71F00F30058B10AC34E34B6701E9838`.

The refresh again observed FMP HTTP 200 minute/earnings probes for all eight assets,
Unusual Whales ordinary-state fields for all eight assets, and directed Massive reference,
trades and quotes at HTTP 200 for one event-returned `O:` contract. It produced no secret
values or personal paths in the distributable evidence. The validator remains
`sanitized=true`, `authorized_for_backfill=false`, with blockers
`B1_NOT_AUTHORIZED`, `COMMON_HISTORY_NOT_ESTABLISHED` and `PROVIDER_FAILURES_PRESENT`.
No new evidence establishes FMP bar start/close semantics, independent Unusual Whales
publication availability, broader Massive entitlement/licensing or common historical overlap.

## Authenticated v1m refresh — 2026-07-21

After presence-only validation of all three process-scoped secrets, bounded run
`a037b0e2-a858-45cb-965b-baa769a16c9f` repeated the audit without backfill. The sanitized
manifest and summary are retained at `artifacts/api_audit/authenticated_v1m/`; the manifest
contains 57 records, validates against schema 1.1, and has SHA-256
`A2DF4FB8ED41E4F1B17428A31707C2FD80C0B0EA4B636EF435B8551C5528892C`.

FMP returned HTTP 200 for all eight minute and earnings probes. Raw labels in sampled 390-row
sessions run from `09:30:00` through `15:59:00`, which is consistent with minute-start labels
but does not by itself prove provider bar semantics. AMZN and TSLA still have one missing minute
each in the 2015 depth window; no interpolation was performed. Unusual Whales returned ordinary
state fields for all eight assets, but old/oldest event probes returned HTTP 403, the cursor
probe repeated a page, and no independent publication timestamp exists. Massive returned HTTP
200 for reference, directed trades and quotes for one event-returned `O:` contract.

The v1m gate remains `B1: BLOCKED`, `authorized_for_backfill=false`, with
`B1_NOT_AUTHORIZED`, `COMMON_HISTORY_NOT_ESTABLISHED` and `PROVIDER_FAILURES_PRESENT` retained
as hard blockers. Raw response bytes remain outside Git under the restricted raw root.

## Authenticated v1n refresh — 2026-07-21

Bounded run `ca79de19-3b18-4abb-ac1f-ffedd6cae636` repeated the authenticated probes after
presence-only validation of all three secrets. The sanitized manifest and summary are retained
at `artifacts/api_audit/authenticated_v1n/`; it contains 57 records, validates against Schema
1.1, has 57 unique composite keys, and SHA-256
`506C74ACA7EF0716E238DEB95D49AA68FECB8318B880046F343B6F2B38C22BAC`.

FMP returned HTTP 200 for all eight assets and calendar probes. The depth window still has one
unclassified missing minute for AMZN (`2015-01-07 12:15:00`) and TSLA
(`2015-01-07 12:34:00`). Calendar probes also omitted sessions `2026-03-06` and `2026-07-13`
and reported `2026-03-09 15:19:00`; all remain unclassified rather than interpolated. UW still
returns HTTP 403 for old probes and a repeated cursor page;
ordinary option-state fields are present but no independent publication timestamp is observed.
Massive still returns HTTP 200 for one event-returned `O:` contract's reference, trades and
quotes. The v1n gate remains `B1: BLOCKED`, `authorized_for_backfill=false`, with the same
three blockers. v1m remains immutable historical evidence.

## Authenticated v1p refresh — 2026-07-21

Run `76b40083-3db3-4034-942f-86e7048114f4` retained the earlier manifests and extended only the
directed Massive probe. The sanitized manifest at `artifacts/api_audit/authenticated_v1p/`
contains 59 records, validates against Schema 1.1, has 59 unique composite keys, and SHA-256
`039740595F124D870AF65DC995501B4E7AA671E96D7C992F1554C5BCC11141A5`.

The event-returned `O:` contract produced HTTP 200 for reference (one result), trades (70
results with `conditions`, `sip_timestamp`, price and size), quotes page 1 (1,000 bid/ask
results), the followed page 2 (45 results), and a valid empty historical quote window (zero
results). This is directed contract validation, not a full OPRA download. FMP and UW findings
are unchanged; `B1_NOT_AUTHORIZED`, `COMMON_HISTORY_NOT_ESTABLISHED` and
`PROVIDER_FAILURES_PRESENT` remain hard blockers, and `authorized_for_backfill=false` remains in
force. v1n and earlier manifests remain immutable.

## Authenticated v1q refresh — 2026-07-21

Run `fe96cd71-0010-4f6e-ac56-bb73acf1cb15` repeated the bounded audit after the Massive probe
correction. The manifest at `artifacts/api_audit/authenticated_v1q/` contains 59 records, 59
unique composite keys, validates against Schema 1.1, and has SHA-256
`160E8EE9708A523B781877F2AC455B383546F97355EEB433ABCCDD81569A5909`.

The event-returned `O:` contract returned reference 200/1, trades 200/37 with conditions and
nanosecond timestamps, quotes 200/1,000 on each of two pages with bid/ask fields, and a valid
empty historical quote window 200/0. This remains directed validation only. FMP and UW findings
are unchanged; B1, common-history and provider-failure blockers remain active.

## Authenticated v1r refresh — 2026-07-21

Run `81a7b72b-636e-4c17-b973-91cb94881f76` repeated the bounded authenticated audit after
v1q. The sanitized manifest at `artifacts/api_audit/authenticated_v1r/` contains 59 records,
59 unique composite keys, validates against Schema 1.1, and has SHA-256
`74C3C0CAD6A5852812107E510BDDbdC9073626D9D22CF11F2E0001925D11689F`.

Massive returned reference 200/1, trades 200/156 with conditions and nanosecond timestamps,
quotes 200/1,000 on each of two pages with bid/ask fields, and a valid empty quote window
200/0. This remains directed validation only; FMP and Unusual Whales findings and all three
hard blockers are unchanged. v0 through v1q remain immutable lineage.

## Official Unusual Whales PIT boundary — 2026-07-21

The official Kafka documentation describes `OptionState` as daily contract statistics pushed
when volume or open-interest updates are available and defines `last_tape_time` as the
timestamp represented by the data. The same documentation states that Kafka/WebSocket topics
retain only 72 hours. `IvTermStructure` and `RiskReversalSkew` expose trading date and expiry,
not an independent publication timestamp. Therefore these sources support a prospective,
licensed stream-capture design, but do not convert the v1m historical REST observations into a
retrospective PIT B1 series. Source: `https://api.unusualwhales.com/docs/kafka` and the linked
`OptionState`, `IvTermStructure` and `RiskReversalSkew` message definitions.

The official Kafka `FlowAlert` schema also documents `start_time`, `end_time`, `executed_at`,
`ivStart` and `ivEnd`. The retained REST flow-alert payload does not contain `executed_at` and
uses snake-case `iv_start`/`iv_end`; therefore the Kafka field must not be backfilled into the
REST evidence. This distinction preserves the raw contract while confirming that a prospective
licensed Kafka capture could expose execution timing separately from alert-window timing.

## Phase 3A probes

1. **FMP OHLCV** — all eight assets; recent, winter, summer, DST-transition and early-close
   sessions; pagination/date limits; official exchange calendar; bar start/close semantics;
   exact origin close and last valid origin; adjusted/unadjusted and split behavior; order,
   duplicates, nulls; locate AMZN/TSLA missing minute and classify halt/provider/calendar/
   process. Completeness is per observed session, never calendar-days×390.
2. **FMP earnings** — all eight requests; require returned symbol equality; classify each as
   applicable/not_applicable/unsupported/invalid_response. SPY and QQQ do not inherit company
   earnings applicability.
3. **Unusual Whales** — several pages, cursors/time limits, recent and old windows, a
   high-activity asset and valid empty response; detect repeated pages; record minimum date,
   event density, schema stability, event fields, `created_at`, `start_time`, `end_time`, raw
   types/units/semantics/timezones/conversions and post-availability risk. Apply aliases
   `ivStart→iv_start`, `ivEnd→iv_end`; report event IV presence separately from ordinary PIT
   state and test ordinary IV/skew/term structure directly.
4. **Massive** — diagnose host, auth, contract format and entitlement first; use only event-
   returned contracts; probe directed trades/quotes, timestamp precision, bid/ask, condition
   codes, pagination and empty/illiquid windows. Do not download all OPRA quotes.

## Acceptance outputs

Produce schema-1.1 manifest, human summary, sanitized fixture index, request IDs, endpoint
fingerprints, response hashes, composite-key uniqueness result, hash-reuse diagnostics,
authentication/endpoint/schema/entitlement diagnostics, applicability and PIT enums, and an
explicit B1 status. Any hard failure remains a blocker. The summary v1 may be generated only
from the validated manifest.

## Authenticated v1s refresh — 2026-07-21

Presence-only validation confirmed all three process-scoped secrets before the bounded request
set. Run `25a82e51-e276-4634-8b1c-d848423deaf4` is retained at
`artifacts/api_audit/authenticated_v1s/`; it contains 59 records and SHA-256
`d64b7cc4e81ff88b956ec8939965bdc553cfb64ac4943552c329ce3b0a1f4609`.

The directed Massive probe remains successful for one event-returned `O:` contract: reference
200/1, trades 200/280, two quote pages 200/1,000, and a valid empty quote window 200/0. FMP and
Unusual Whales findings are unchanged: FMP bar-label semantics and missing-minute causes remain
unresolved; UW old probes remain 403 and do not establish a historical PIT publication timestamp.
The validator therefore still reports `B1_NOT_AUTHORIZED`, `COMMON_HISTORY_NOT_ESTABLISHED` and
`PROVIDER_FAILURES_PRESENT`, with `authorized_for_backfill=false`.

## Explicit blocker-resolution conditions

Backfill can be reconsidered only after a new sanitized manifest demonstrates all of the following:

1. `B1_NOT_AUTHORIZED`: an independently timestamped, licensed ordinary IV/skew/term-structure
   series is available at or before every forecast cutoff, with a documented publication-time
   field and a passing no-look-ahead contract.
2. `COMMON_HISTORY_NOT_ESTABLISHED`: the same verified historical interval overlaps across FMP,
   UW and the directed Massive evidence for at least four assets, with exact start/end dates and
   asset-level quality ratios recorded.
3. `PROVIDER_FAILURES_PRESENT`: every 403/unsupported/repeated-page condition is either resolved
   or explicitly classified as an in-scope non-applicable probe; no provider failure may be
   silently treated as success.
4. FMP bar semantics: start-versus-close meaning, winter/summer/DST, early-close, halts and the
   AMZN/TSLA missing minutes are classified against an official exchange calendar. Missing prices
   remain exclusions; interpolation is prohibited.

Until those conditions are met, the only permitted dataset exercise is the fixture-only preview at
`artifacts/pilot_preview/fixture_20260721/`. It is marked
`historical_provider_backfill=false`, `synthetic_data_used=true`, and is not a pilot acceptance.

## Corrected provider-call audit v1v — 2026-07-21

The prior probe had three call-contract defects. They are corrected in
`scripts/provider_audit_v1.py` and validated against the current provider documentation:

- FMP now sends `apikey` as a query parameter, matching the official [1-minute chart
  endpoint](https://site.financialmodelingprep.com/how-to/how-to-get-stock-intraday-data-with-fmp-apis),
  while retaining the documented descending response order for later chronological sorting.
- Unusual Whales now sends `ticker_symbol`, `newer_than`, `older_than` and `limit` exactly as
  declared in the official [OpenAPI contract](https://api.unusualwhales.com/api/openapi). The
  second page advances the lower time boundary rather than replaying the same page.
- Massive now sends `apiKey` as a query parameter, uses a future-expiry event-returned contract
  for the reference probe, and retains directed trades/quotes only. The official docs identify
  the options-ticker path, `timestamp` filter and plan-specific historical coverage ([trades](https://massive.com/docs/rest/options/trades-quotes/trades),
  [quotes](https://massive.com/docs/rest/options/trades-quotes/quotes)).

Run `c65599c4-f362-4776-9d5b-61fc361e60ce` is retained at
`artifacts/api_audit/authenticated_v1v/` with 58 records and SHA-256
`eaec1f3dad01e6d5df8cc02e59faf4045674bf639d6291edb1d1ba19cbf602b9`.

Result: `PROVIDER_FAILURES_PRESENT` is cleared by the validator. The 403 at the explicitly
out-of-entitlement oldest-date probe is retained as `applicability=unsupported` with
`expected_entitlement_boundary=true`, not treated as a silent success. A valid 200/0 empty window
is now recorded separately. The remaining blockers are only `B1_NOT_AUTHORIZED` and
`COMMON_HISTORY_NOT_ESTABLISHED`.

## Corrected provider-call audit v1w — 2026-07-21

Run `354e42ac-beb8-48a3-8bd1-455e5923b089` is retained at
`artifacts/api_audit/authenticated_v1w/` with 58 records and SHA-256
`d80336a1a892cdc7b00f30336b921fee821150555ce86c7b51aab74e46ae83a3`.
It preserves the v1v call corrections and records FMP's exchange-local
`America/New_York` timezone guidance while keeping start-versus-close bar semantics unresolved.
Validation remains limited to `B1_NOT_AUTHORIZED` and `COMMON_HISTORY_NOT_ESTABLISHED`.

## Current derived-state refresh — 2026-07-21

The latest execution path is the derived-state auditor in `scripts/provider_audit_v1.py`, not
the historical summary prose above. The latest bounded rerun is retained at
`artifacts/api_audit/authenticated_v1y/` and validates as sanitized against Schema 1.1. The
auditor reads `artifacts/api_audit/pit_verification_20260721/pit_verification.json` and
`artifacts/api_audit/window_probe_20260720/probe_results.json`. For the frozen 2025-07-21
through 2026-07-21 study window it derives `b1_status=INFEASIBLE`,
`fallback_comparison=B2-vs-B0`, `common_history_status=PASS`, and clears the historical
common-history/provider-failure literals. The remaining `B1_NOT_AUTHORIZED` is evidence-driven:
ordinary option-state publication availability is not independently timestamped. The bounded
pilot/backfill artifacts are retained separately and do not authorize benchmark metrics.
