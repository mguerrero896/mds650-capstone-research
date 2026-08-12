# Methodology decisions (recovery baseline)

Status: Phase 5 design approved, 2026-07-29. Earlier bounded phase restrictions remain
historical controls; current acquisition, modeling and QLIKE authority begins only after
Spec Kit consistency and preregistration gates pass.

1. **Target** — RV30 only. At origin `t`, use the fully observed close `C(i,t)` and the next
   thirty consecutive one-minute closes. Compute `r(i,t+j)=ln[C(i,t+j)/C(i,t+j-1)]` for
   `j=1..30` and `RV(i,t:t+30)=Σ(r(i,t+j)^2)`. Exactly 31 prices and 30 returns are required.
2. **Candidates and freeze** — Audit SPY, QQQ, AAPL, MSFT, NVDA, TSLA, AMZN and META
   together. Freeze 4–6 only by coverage, quality, timestamp integrity, contract resolution
   and verified common overlap; predictive results are excluded.
3. **Benchmarks** — B0 controls; B1a adds independently verified ordinary PIT ATM IV; B2 adds
   the frozen compact trade-derived activity features. B1b adds skew and B1c adds term
   structure as robustness levels. Primary contrast is
   `Delta_B2 = QLIKE(B1a)-QLIKE(B2)`; `Delta_B1 = QLIKE(B0)-QLIKE(B1a)` is the key secondary
   confirmatory contrast.
4. **Evidence state** — The current manifest is immutable exploratory v0. It is not a v1
   acceptance result. The repeated eight-asset depth probes are retained and classified as an
   idempotency defect.
5. **Timestamp policy** — FMP bar start/close semantics, exact origin close, last valid origin,
   early-close and halt handling remain unverified as provider facts. Existing canonical evidence
   is retained under its registered conservative timing rules; any *new* historical sample requires
   a date-level PIT preflight. Missing prices fail closed; interpolation is forbidden. Market
   completeness uses an exchange calendar, not 390 times calendar days.
6. **Unusual Whales** — Canonical aliases are `ivStart -> iv_start` and `ivEnd -> iv_end`.
   `event_iv_fields_present` is separate from `ordinary_option_state_pit_verified`; alert
   fields do not prove a historical ordinary option-state series. Document `created_at`,
   `start_time` and `end_time` independently. The retained Full Tape files now provide raw
   `executed_at` and `created_at` field coverage, but their delta remains a provider-field
   diagnostic only: it does not establish customer receipt or publication time. The official
   OptionTrade schema defines `created_at` as time the trade record was created, not as
   publication or historical availability. The official term-structure and historical risk-reversal
   endpoints may establish field coverage, but a market date without an independent
   publication/availability timestamp keeps `ordinary_option_state_pit_verified=false` and
   cannot unlock B1.
7. **Earnings applicability** — Require `returned_symbol == requested_symbol`; use
   `applicable`, `not_applicable`, `unsupported` or `invalid_response`. ETFs do not inherit a
   company earnings contract.
8. **Prevalence** — Construct event and no-event forecast origins while preserving natural
   prevalence. Training-only weighting/subsampling must be documented; validation and final
   testing preserve the natural distribution.
9. **Statistical pre-registration** — Daily paired bootstrap keeps all observed assets and
   origins on the same trading day. Primary/secondary/robustness analyses, Holm use, MDE estimation from
   simulation/bootstrap/pilot/training only, and volatility/earnings/session/asset-market/
   normal-stressed regimes are frozen before final-test inspection.
10. **Runtime** — Python 3.12.12 is the approved baseline. The Windows/Colab compatibility
    matrix and clean-install proof passed before the owner authorized the metadata and lockfile
    migration on 2026-07-21. Compatibility, not novelty, selected the version.
11. **UW prospective PIT boundary** — Official UW streaming documentation describes
    `OptionState.last_tape_time` as the timestamp the data represents, but the option-state,
    IV-term-structure and risk-reversal topics are live Kafka/WebSocket topics with 72-hour
    retention. A historical REST response containing only a trading date is therefore not
    sufficient for retrospective PIT acceptance. A prospective stream capture could satisfy
    the availability gate only after a separate licensed capture and replay audit.
12. **FMP bar-label evidence** — The current official FMP documentation identifies the
    `historical-chart/1min` endpoint and one-minute OHLCV scope, but does not document the
    response timestamp timezone, whether `date` labels interval start or close, or completed-bar
    publication latency. A bounded AAPL 1-minute/5-minute probe is consistent with start-grid
    labels (78/78 versus 0/78 close-grid labels), but remains internal consistency rather than
    contractual proof. The retained authenticated samples show regular-session labels from `09:30`
    through `15:59` (and early-close labels through `12:59`), which is consistent with
    start-labelled bars but is not sufficient to accept the convention. The engineering panel
    therefore uses `available_at = timestamp_raw + 1 minute` as a conservative research
    assumption and keeps `FMP_BAR_SEMANTICS_UNRESOLVED`; report the +2-minute sensitivity and
    never describe either rule as provider-confirmed latency. Sources:
    `https://site.financialmodelingprep.com/developer/docs/stable/intraday-1-min` and
    `https://site.financialmodelingprep.com/developer/docs`.
13. **B1 closure routes** — `B1Q` (Massive quotes) is the preferred ordinary-option-state
    route because it is independent of trade occurrence. `B1T` (Full Tape) is a diagnostic
    fallback and sensitivity route only; it shares source provenance with B2 and cannot be
    described as independent evidence.
14. **B1 quote contract** — Resolve contracts by `as_of` per asset-date, cache each
    contract-day response, then select the last SIP quote with `sip_timestamp <= origin`.
    Primary filters are quote age <=60 seconds and relative spread <=25%; 300 seconds/50%
    are sensitivity filters. Missing quotes receive an explicit reason, never a zero quote.
15. **B1 coverage gate** — A twenty-session request requires B1a global coverage >=70%,
    asset coverage >=50%, every session tercile >=40%, valid PIT and no close-only
    concentration. B1b/B1c may remain robustness levels. Coverage cannot be chosen by
    predictive results.
16. **Common-history closure** — Six monthly probes are sampled overlap evidence only. The
    all-assets v3 artifact must contain 48 asset-date records for the eight candidates and
    report earliest/latest observed dates and common assets per date without claiming daily
    continuity.
17. **Twenty-session boundary** — The twenty trading sessions immediately before 13 July 2026,
    excluding the five Pilot V2 sessions, were authorized and processed as calibration-only
    evidence. This decision does not authorize any larger range; a separate configuration change
    and authorization are required for a future backfill, with the same resumability and 30%-margin
    storage gates.
18. **Nested B1 semantics** — Component availability is separate from benchmark completeness:
    `b1a_complete=ATM`, `b1b_complete=ATM AND skew`, and `b1c_complete=ATM AND skew AND
    term structure`. Monotonicity is an executable invariant.
19. **Forensic B1 gate** — Retain the invalid nested result; emit a stage-level waterfall and
    controlled four-asset trace before any full recomputation.
20. **Availability probe** — Inspect exact FMP sessions, UW file metadata and historical
    Massive contract/quote probes without downloading Full Tape contents; file existence is
    not PIT proof.
21. **B1Q integration repair and earnings contract** — Resolve historical contracts by DTE
   bucket so pagination on near-term expiries cannot omit medium/long buckets. Cache keys
   include provider, asset, session date, expiry, strike, option type and contract. Earnings
   are equity-only; ETF distributions are never synthesized as earnings.
22. **Twenty-session calibration boundary** — Phase 3F is authorized only for the twenty
   pre-Pilot-V2 sessions 2026-06-11 through 2026-07-10. It is resumable and storage-gated,
   retains raw ZIPs immutably, leaves the 199 legacy cache files read-only, and does not
   authorize a larger backfill, models, QLIKE, tuning, final tests, asset freeze or document
   publication.
23. **B2 calibration** — Use continuous features with `created_at <= origin-60s` as the primary
   operational availability proxy; 15s and 0s are sensitivities. Normalize by asset and
   30-minute band from prior sessions with median/MAD and explicit IQR/asset fallbacks. The
   unusual-event label is secondary, p95-based and never selected using RV30.
24. **Calibration-to-pilot separation** — Estimate all normalization parameters on the twenty
   pre-Pilot-V2 sessions, then apply them unchanged to Pilot V2. Record sample sizes, fallback,
   cutoffs and hashes per origin; no future or target information may enter calibration.
25. **Phase 3F B1Q gate** — Recompute B1Q on all twenty sessions with the repaired nested
   predicates and retain B1T as diagnostic-only. Recommend roles only from data quality/PIT
   evidence; report one explicit recommendation while keeping model and final-test gates closed.
26. **Owner authorization 2026-07-22** — RV30 is the official horizon and RV10 is not
   introduced. The owner authorized the FMP one-minute availability assumption and the UW
   60-second `created_at` operational proxy only as explicitly labeled assumptions. Neither
   replaces direct provider evidence: FMP start/close semantics and UW historical publication
   semantics remain unresolved until documented or independently demonstrated. The bounded
   daily continuity audit in `artifacts/api_audit/common_history_continuity_v5.json` is
   metadata-only, uses no Full Tape ZIP contents, and does not authorize backfill, modeling,
   QLIKE or final testing. Earnings remain outside the primary benchmark.
27. **Ninety-session sample** — The owner approved eighty XNYS development sessions from
   2026-03-24 through 2026-07-17 and ten prospective holdout sessions from 2026-07-20 through
   2026-07-31. Reuse the twenty-five retained sessions after hash validation and acquire only
   the fifty-five missing development sessions.
28. **Compact B2 information set** — Freeze exactly nine target-blind features:
   log trade count, unique-contract share, log mean/max premium, scaled call/put premium
   imbalance, execution-side premium imbalance, repeated-contract premium share, strike
   concentration and expiry concentration. The registry was chosen without RV30, QLIKE,
   forecasts or holdout access; every attempted registered variant is retained.
29. **Champion–challenger models** — Gamma GLM is confirmatory because it models a positive
   conditional mean with a log link. LightGBM with Gamma objective is a fixed nonlinear
   robustness challenger. A favorable result cannot promote the challenger or revise either
   grid after preregistration.
30. **Inference and multiplicity** — QLIKE is primary; MAE and RMSE are descriptive. Use
   10,000 paired whole-day bootstrap draws with seed 650 and Holm correction for `Delta_B1`
   and `Delta_B2`. Positive, negative and null outcomes are equally reportable.
31. **Holdout discipline** — The ten-session prospective holdout is read analytically once
   after all sessions complete, method hashes freeze, leakage/reproducibility tests pass and
   the access ledger authorizes the `0 -> 1` transition. No design decision changes afterward.
32. **Storage boundary** — Large licensed raw ZIPs, Parquet tables and provider caches live
   under `D:\MDS650`. Before each batch, stop if projected minimum peak free space is below
   80 GB. Do not delete raw evidence until hashes, manifests and reproducibility are verified.
33. **Phase 5 stability freeze** — Session terciles use B0 session-minute bounds 130 and 260.
   Volatility regimes use linear tertiles of pooled selected-asset development
   `b0_rv_30m_lag`; the exact cutpoints are stored in the method freeze. FMP +2 and B2
   120/300-second sensitivities refit the frozen primary specifications without retuning and
   do not enter the two-test Holm family. A stratum is materially negative only when its
   paired-day bootstrap `ci_high < 0`; a systematic reversal requires at least two such
   strata, at least two sessions per stratum and at least 50% of the corresponding dimension's
   origins. Any non-primary timing variant with `ci_high < 0` is material. These outputs are
   generated inside the sole authorized holdout read, never by reopening the holdout. The
   stability dimensions were preregistered, but the numerical materiality rule was
   operationalized after development and before holdout; final reporting must disclose that
   distinction and cannot describe the threshold as pre-development.
34. **Written specification approval and holdout acquisition boundary** — The owner approved
   the written 80/10, B0/B1a/B2, Gamma/LightGBM, QLIKE/bootstrap/Holm and one-read design.
   Holdout acquisition is operationally separate from analytical access: it cannot make a
   provider request before `2026-07-31T20:00:00Z`, runs under the isolated
   `D:\MDS650\data\phase5_holdout` root, may construct and hash the common panel and timing
   sidecar, and must leave `holdout_reads=0` without model fitting, QLIKE or outcome summaries.
35. **Provider timing gate amendment v1 (2026-08-11)** — Existing canonical evidence is
   `VALID_UNDER_REGISTERED_TIMING_ASSUMPTIONS` and its scientific reconciliation is
   `CONDITIONAL_GO_NOW`. A new historical sample remains
   `GO_AFTER_DATE_LEVEL_PIT_PREFLIGHT`; a new prospective sample remains
   `GO_AFTER_RECEIPT_LOGGER_VALIDATED`; and any universal provider-latency claim is
   `NOT_SUPPORTED`. The static FMP rule is `timestamp + 1 minute` with `+2 minutes` sensitivity
   as `SUPPORTED_CONSERVATIVE_ASSUMPTION`. The historical UW Full Tape audit is `PROXY_ONLY`:
   observed `created_at - executed_at` fields do not become publication or client-receipt time.
   This amendment supersedes a single absolute timing NO-GO without changing canonical results.
36. **Provider timing gate amendment v2.1 (2026-08-12)** — A target-blind offline audit
   verified the target-free forecast-origin sidecar against the XNYS calendar: all 77,328
   origins were inside session bounds, including 432 origins in the two early-close sessions.
   Massive B1Q raw-cache re-selection passed for 2,308,176 attempts and 32,238 cache
   identities: no identity failures, no future quote selection and quote existence was
   non-increasing for origin, origin-minus-60 seconds and origin-minus-300 seconds. Thirty-one
   early-close cache envelopes carrying post-close SIP rows were explicitly filtered before
   as-of selection; 329 other overextended early-close requests were retained as visible
   warnings. The B2 gate is nevertheless `FAIL_ZERO_ACTIVITY_NOT_DISAMBIGUATED`: 61 of 5,400
   canonical variant/session/asset sidecar rows are zero-coded while record-creation delay is
   observed. Therefore `SAFE_TO_RECONCILE_EXISTING_RESULTS=NO`. The audit establishes neither
   Unusual Whales publication/client-receipt time nor an economic or predictive claim; no
   sealed result, model or QLIKE output was read or changed.
37. **Corrected development evidence release (2026-08-12)** — Authenticated historical-source
   evidence establishes FMP `PASS_90_OF_90_SESSIONS` and Unusual Whales
   `PASS_90_OF_90_FILE_METADATA` for the registered sample. These findings establish historical
   availability only: they do not confirm the FMP bar timestamp label or REST availability, and
   they do not turn Unusual Whales `created_at` into publication or client-receipt time. The
   approved correction is therefore a new, source-bound, development-only B0/B1a/B2 release
   built specifically for the exact fixed 80-session development manifest. The target-blind
   v2.4 panel is retained as a control/provenance artifact but cannot be relabelled as the
   source window because its 180 dates do not equal the frozen 80 dates. A coverage ledger must
   record B0/B2 and B1Q source identity by asset-date. The executed 80-session target-free
   ledger records B0/FMP and B2/UW raw Full Tape source coverage for all 480 selected
   asset-date pairs. It also records that the 55 existing B1Q source dates have
   `rate_source_date == session_date`, while the retained 25 dates lack separately stored
   pre-origin rate/dividend provenance; all 34,080 B1Q origins are therefore
   `B1Q_EXOGENOUS_INPUT_PROVENANCE_UNRESOLVED`. Neither condition licenses a later, stale,
   same-session, or carried-forward value. Delayed B2 rows are explicit
   all-nine-feature-null exclusions, never no-activity zeroes. A source-coverage gap yields
   `BLOCKED_SOURCE_COVERAGE` before target binding or evaluation. This release never rewrites
   sealed legacy results, acquires data, reads the ten-session holdout or upgrades
   `SAFE_TO_RECONCILE_EXISTING_RESULTS=NO` or `SAFE_TO_OPEN_OR_EVALUATE_OOS=NO`.
38. **B1Q exogenous-evidence hardening (2026-08-12)** — A strictly prior
   `rate_source_date` is necessary but not sufficient to establish B1Q provenance. Every usable
   rate and dividend input must additionally carry a sanitized raw-payload SHA-256 and an
   evidence-availability timestamp at or before its forecast origin. Missing, malformed or
   later evidence produces `B1Q_EXOGENOUS_INPUT_PROVENANCE_UNRESOLVED`; it never licenses a
   backfilled, carried-forward or undocumented proxy. The FMP Treasury/dividend semantics and
   revision claims must first pass the review-only timing-evidence intake; that assessment is
   not a network or rebuild authorization. Legacy B1Q source files lacking these audit fields
   remain explicitly blocked until separately evidenced inputs are available.
