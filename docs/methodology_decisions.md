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
39. **B1Q put-call-parity grid diagnostic (2026-08-12)** — The target-free, source-hashed
   `artifacts/corrected_development_v1/b1q_put_call_parity_feasibility_v1.json` tests only
   whether the already cached B1Q contract grid has the minimum same-expiry geometry required to
   derive a discount factor from put-call parity. It reads an explicit quote-only allowlist and
   no target, metric, IV outcome, rate, dividend, model or holdout field. On the current 55-day
   cache it found 27,199 of 31,240 origins with at least one same-strike call/put pair, but zero
   origins with two paired strikes at one expiry; the result is therefore
   `INFEASIBLE_WITH_CURRENT_CONTRACT_GRID`. This is neither evidence that FMP or Massive lack
   history nor permission to synthesize a rate/dividend input, carry a value forward, use zero,
   alter B1Q, reconcile legacy outputs or open OOS. Any future parity route would require a
   separately authorized methodological amendment, an expanded source contract and fresh PIT
   review before it can be considered.
40. **Deterministic Massive contract-selection rule (2026-08-12)** — The local,
   target-blind rule massive-contract-grid-v1-asof-dte-moneyness-tiebreak fixes
   contract-grid selection from already schema-validated historical reference candidates.
   It uses the registered 7–21, 30–60 and 90–180 DTE buckets, the
   0.95/0.975/1.00/1.025/1.05 moneyness grid and call/put slots. Ties are resolved in
   this exact order: absolute moneyness distance, distance from the DTE-bucket midpoint,
   expiration, strike and contract identifier. A missing slot remains missing, not zero.
   This only removes a local reproducibility ambiguity; it does not call Massive, alter
   any legacy B1Q cache, establish provider PIT semantics, resolve B1Q exogenous-input
   provenance or upgrade SAFE_TO_RECONCILE_EXISTING_RESULTS=NO.
41. **PIT preflight status v2.1 supersedes only its current planning state
   (2026-08-12)** — The v2.1 preflight status binds the registered Massive selection-rule ID
   and removes the stale current-state code
   `MASSIVE_CONTRACT_SELECTION_RULE_UNRESOLVED_NO_EXECUTION`. The sealed v2.0 status and its
   historical evidence code remain immutable and schema-valid. FMP historical availability
   remains `PASS_90_OF_90_SESSIONS`, and Unusual Whales Full Tape file metadata remains
   `PASS_90_OF_90_FILE_METADATA`; these positive availability facts remain distinct from
   timestamp, publication, receipt and exogenous-input provenance. The v2.1 status therefore
   remains `FAILED_CLOSED`, with zero transport attempts and no authorization to reconcile
   legacy results, acquire new data or open OOS.
42. **Scientific interpretation after the corrected forensic reevaluation
   (2026-08-14)** — The current accepted interpretation is model-dependent. Gamma reports an
   adverse `B1a-B0` contrast and a positive, statistically supported `B2-B1a` contrast; the
   fixed LightGBM challenger does not confirm either contrast at the registered materiality
   standard. `confirmed_contrasts` therefore remains empty. The directed B2 finding may be
   described as promising and replicated within Gamma, never as a universal or production
   edge. No result in this repository is a trading P&L backtest.
43. **Legacy B1 status and approved B1v3 boundary (2026-08-14)** — Legacy B1 remains an
   immutable audit comparator. Target-blind review found that its ATM/skew geometry can mix
   maturities and that raw-IV term differences do not represent constant-maturity forward
   variance. The owner-approved B1v3 uses same-expiry/same-strike call-put consensus, 30-day log
   implied variance, symmetric same-expiry skew, and forward variance derived from total
   variance at registered tenors. Status is `APPROVED_FOR_TARGET_BLIND_IMPLEMENTATION`: it is not
   yet an accepted benchmark result and does not permit outcome evaluation before source binding,
   pristine-sample selection, preregistration and one-read gates pass.
44. **No sign-directed development (2026-08-14)** — B1v3 geometry and feature definitions
   were derived without reading RV30, QLIKE, predictions or model outcomes for that design
   step. If approved, the specification, source contract, preprocessing, models, metric,
   inference and stop rules must be sealed before a new result is opened. Positive, negative
   and null signs must all remain in the variant ledger; no route may be promoted because it
   produces a favorable sign.
45. **Institutional authority and narrative (2026-08-14)** —
   `reports/MDS650_MASTER_PROJECT_DOSSIER.md` is the human-readable index of code, data,
   artifacts, joins, models, results and roadmap. It does not supersede immutable manifests,
   schemas, execution logs, hashes or registered contracts. Any conflict is resolved in favor
   of the lower-level signed evidence and documented as a supersession, never silently edited.
46. **Provider availability statement (2026-08-14)** — FMP and Unusual Whales demonstrably
   provide historical data for the registered sample, and Massive provides directed historical
   contract/quote data under the observed entitlement. Historical retrieval is not equivalent
   to proof of first availability at every past origin. New data must pass the date-level
   contract/preflight and registered timing assumptions; provider facts and research assumptions
   must remain separately labeled.
47. **B1v3 independent-confirmation rule (2026-08-14)** — The next scientific test must use a
   date-only exposure ledger, exclude every previously used result date, require 60 preceding
   eligible XNYS sessions and freeze the earliest contiguous pristine 30-session block before any
   RV30 or QLIKE access. Gamma remains confirmatory, LightGBM fixed robustness, QLIKE primary,
   inference uses 10,000 paired whole-day bootstrap resamples plus Holm, and MDE is training-only.
   If no eligible block exists, record `NO_PRISTINE_30_SESSION_BLOCK`; never reuse an exposed OOS
   period or choose a feature/timing/model variant because its result is favorable.
48. **B1v3 one-read result (2026-08-14)** — The source-bound 60/30-session confirmation is
   complete on 23,320 development and 11,577 confirmation common-complete origins. Under the
   confirmatory Gamma model, `QLIKE(B0)-QLIKE(B1v3a)=-0.05030242` with 95% paired-day interval
   `[-0.06532898,-0.03593304]`, so ordinary ATM option state did not improve B0. The registered
   incremental contrast `QLIKE(B1v3a)-QLIKE(B2)=0.05339190` has interval
   `[0.03857849,0.06817332]`, Holm-adjusted `p=0.00039996`, exceeds the training-only MDE
   `0.01304182`, is positive in all six asset point estimates and remains positive under all five
   timing sensitivities. Fixed LightGBM reverses both contrasts, including B2 at
   `-0.00745281` with interval `[-0.01218466,-0.00355039]`. The binding conclusion is therefore
   `POSITIVE_BUT_NOT_GLOBALLY_CONFIRMED`: B2 has strong Gamma-specific incremental evidence, not
   a model-independent or production edge; B1v3a does not beat B0 in this confirmation.
49. **One-read serialization recovery (2026-08-14)** — The confirmation token was consumed once
   and the registered evaluation completed before a generic `authorization` sanitizer token
   rejected the legitimate provenance key `consumed_authorization_manifest_sha256`. No second
   target read or model fit was performed. Finalization used only the three already-sealed
   derived Parquet outputs after testing the exact consumed-ledger transition, target identity,
   schema, hashes and secret hygiene. The incident and immutable hashes are recorded in
   `docs/recovery/b1v3_one_read_serialization_incident.md`.
50. **Repository consolidation and single history (2026-08-17)** — The five local branches
   were verified to form one linear chain; `main` was created at `37146ce` (tip of
   `codex/b1-diagnosis-replication-20260815`) and is the sole canonical branch. The
   pre-consolidation dirty state of the primary worktree (206 porcelain entries, 694 files)
   is preserved verbatim on `archive/meeting-dirty-20260816`; nothing was discarded without a
   committed copy. Full-history bundles and working-tree snapshots exist under
   `D:\MDS650\backups\repo_20260817\`. Commercial-derived heavy evidence is mounted at
   `D:\MDS650\evidence_root` per the `MDS650_EVIDENCE_ROOT` convention in `tests/evidence.py`;
   the frozen Phase 4B/5 input hashes verify against that root. The `MDS650_DATA_ROOT`
   environment variable was reconciled to `D:\MDS650` (closing the L008 mismatch): canonical
   consumers append `data/` themselves. An off-machine remote (private GitHub) remains an
   owner action and is the highest-priority open custody item.
51. **Retroactive classification of the 2024 confirmation blocks (2026-08-17)** — The two
   historical evaluation blocks (2024-08-02..2024-09-13 and 2024-10-01..2024-11-11) recorded in
   `artifacts/b2_confirmation/` lie outside both the frozen 2025-07-21..2026-07-21 study window
   and the Phase 6 session allowlist ending 2026-03-23, and no numbered decision authorized
   their dates before evaluation. They are therefore classified `EXPLORATORY_RETROSPECTIVE`
   and may not be cited as confirmatory evidence in any deliverable. Presenting them as part
   of a window amendment requires an explicit owner decision (D005,
   `OWNER_APPROVAL_PENDING`). Their per-protocol freezes remain valid as internal audit
   records; the classification governs only the evidentiary weight of the results.
52. **Sealed-cohort disposition and campaign moratorium (2026-08-17)** — Validation A
   (14/30 acquired), Validation B (0/30) and Phase 8 (10/30) remain sealed with zero
   scientific reads. Their disposition — complete under the existing frozen gates, or close
   formally without reading — is an owner decision (D006) recorded in
   `docs/sealed_cohorts_disposition_v1.md`. Until D006 is decided, NO new retrospective
   evaluation campaign, protocol freeze, or historical block selection may be created. This
   moratorium exists because five post-null evaluation campaigns were designed between
   2026-08-01 and 2026-08-14, and campaign-level multiplicity is not controlled by
   per-campaign Holm families (R-019).
53. **Binding reporting hierarchy for all deliverables (2026-08-17)** — Every report,
   proposal, slide or summary must present results in this order and with these labels:
   (1) the prospective preregistered Phase 5 holdout is the only confirmatory test and it
   returned null for both nested contrasts; (2) all later positive findings are retrospective
   and model-dependent (`POSITIVE_BUT_NOT_GLOBALLY_CONFIRMED` / `MODEL_FAMILY_DEPENDENT`),
   with the fixed LightGBM challenger adverse or null in the same samples; (3) wherever an
   incremental `B1->B2` contrast is shown, the total `B0->B2` contrast for the same
   model/sample must appear beside it; (4) the bare word "confirmed" may not be used for any
   global effect while `confirmed_contrasts` is empty in the underlying artifact. The
   canonical cross-campaign numbers live in `docs/results_reconciliation_v2.md`.
54. **D005 resolved: 2024 confirmation blocks remain exploratory (2026-08-17)** — The owner
   confirmed in writing (2026-08-17 session message) that the two out-of-window 2024
   evaluation blocks keep the `EXPLORATORY_RETROSPECTIVE` classification from decision 51 as
   their final status. No window amendment will be made. In every deliverable they may be
   described only as exploratory diagnostics; they carry no confirmatory weight. D005 is
   closed.
55. **D006 resolved: Phase 8 completion chosen; Validation A/B closed unread (2026-08-17)** —
   The owner directed end-to-end resolution of the sealed cohorts and authorized storage on
   `D:`. Actions executed the same day: (a) the Phase 8 blind-collector store was relocated
   to `D:\MDS650\phase8_holdout` via a directory junction (paths unchanged;
   `phase8_repro_gate.py` PASS after the move; `holdout_reads` remains 0); (b) catch-up
   acquisition of the closed-but-uncollected August sessions was launched and the
   `MDS650_Phase8A_BlindCollector` scheduled task was re-enabled (daily 18:00), which
   completes 30/30 on 2026-08-29 for the frozen 2026-07-20..2026-08-28 calendar; (c)
   Validation A (14/30 acquired) and Validation B (0/30) are `CLOSED_UNREAD_20260817`:
   superseded by the B1v3 exposure-ledger design (decision 47) and the Phase 8 prospective
   holdout; they may be cited as unopened seals, never as results. Phase 8 remains sealed:
   no read is authorized until 30/30 completion plus an explicit one-shot authorization
   recorded against the frozen method hash `87c818be…`. The decision-52 moratorium on new
   retrospective campaigns remains in force. D006 is closed.
56. **Owner-directed exploratory era-information mapping and positive-findings
   formalization (2026-08-18)** — The owner directed (session goal, 2026-08-18) an
   end-to-end search for the strongest defensible positive characterization of the
   project's results. Scope authorized: (a) formalizing, with the Gate-1 studentized
   machinery, the cross-family positive contrasts already present in frozen, previously
   read artifacts — in particular the 2024-block B0→B1a and total B0→B2 contrasts that
   are positive across all five model families; (b) an era-information map re-analyzing
   the four existing frozen feature panels (C6 2024-08..12, C4c 2025-03..07, Phase 6
   2025-08..2026-03, development 2026-03..07) with three fixed-hyperparameter model
   families and nested B0/B1/B2 ladders under within-era walk-forward, to measure how
   option-information content varies over time. Both carry the label
   `EXPLORATORY_DESCRIPTIVE`: they re-analyze already-read data, involve no sealed
   cohort, no new provider acquisition, and no confirmatory weight. The decision-53
   reporting hierarchy (prospective null first) and the decision-52 moratorium on new
   confirmatory retrospective campaigns remain fully in force. Result signs are reported
   exactly as computed; this decision authorizes the analysis, not any outcome.
57. **Pre-stated interpretation rule for the UW latency campaign (2026-08-18)** —
   Recorded before the first +7-day reconciliation artifact exists (first one expected
   on or after 2026-08-24). Thresholds, fixed now: (a) if the live-era P95 of
   receipt−`created_at` latency is ≤ 60 seconds, the registered availability cutoff
   (`created_at` ≤ origin − 60s) is upgraded from assumption to measured-adequate for
   the live era; if P95 exceeds 60 seconds, every live-era B2 availability claim must
   carry the measured P95 as its effective cutoff, and threat #8 in
   `docs/threats_to_validity_matrix_v1.md` is amended with the measured value;
   (b) if the backfill upper bound (tape rows never observed live) exceeds 5% of tape
   rows for the outcome assets, A002 is reported as MEASURED_ADVERSE for the live era
   and, by stated analogy, the historical 2024/2025 tape-based B2 claims gain an
   explicit unquantified-backfill caveat; at or below 5% the historical caveat remains
   qualitative; (c) any revision rate among matched rows above 1% is reported alongside
   every B2 feature claim. An adverse outcome on any threshold changes labels and
   caveats only — no registered verdict is rewritten (decision 53). The campaign's
   completion (≥5 reconciled sessions) is independent of, and may postdate, the Phase 8
   read; a slip creates no pressure on either.
58. **Phase 9 prospective total-contribution protocol frozen (2026-08-18)** — The owner
   authorized ("procede con todos los bloques", session goal 2026-08-18) freezing the
   Phase 9 protocol in `docs/phase9_total_contribution_protocol_v1.md`: a prospective,
   one-read, two-independent-family test of the TOTAL option-information contribution
   (B0HAR→B2) on the first 60 XNYS sessions strictly after 2026-08-18, with fixed
   decision rules (GLOBAL_POSITIVE / EQUIVALENT_NULL at δ = 0.005 / MIXED), honest
   dual-scenario power statement, and a precommitment for the underpowered-null branch.
   The protocol file's SHA-256 at freeze is recorded in
   `artifacts/phase9/protocol_freeze.json`; any later edit invalidates it. Collection is
   inert until the owner activates the collector task; no Phase 9 data exist at freeze
   time. Decisions 52/53 remain in force; this is the registered successor experiment,
   not a retrospective campaign.
59. **Phase 9 collection ACTIVATED (2026-08-18)** — The owner activated Phase 9
   collection ("activa phase 9 completa", session message 2026-08-18). Infrastructure,
   verified live before activation: `scripts/phase9_collect.py` (nightly post-close
   pulls — FMP 1-minute bars for the six assets, the UW full-tape day archive via the
   signed-redirect download, and a Massive ATM quote sweep at the five-minute origins
   with 13-second pacing), `scripts/phase9_verify.py` (same-day completeness check with
   loud alerts to `logs/PHASE9_ALERT.txt`), and scheduled tasks
   `MDS650_Phase9_Collector` (daily 08:10 local) and `MDS650_Phase9_PostCheck` (daily
   13:30 local), both registered `Ready`. End-to-end dry run against 2026-08-14:
   2,340 bars, 1.47 GB tape, 12/18 quotes OK, manifest with SHA-256 hashes; dry-run
   data quarantined under `phase9/dryrun/`. Storage guard: 120 GB minimum free,
   crash-safe per-session directories, access counter `reads=0`, append-only session
   register. The 60-session clock starts at the first captured session (expected from
   the 2026-08-18 NY session); completion ≈ mid-November 2026, alert on 60/60. The
   frozen protocol (decision 58, sha 8cf87b4d…) governs; nothing is read until then.
60. **Model naming correction — `har_rv` is a log-linear fixed extension (2026-08-18)** —
   Reviewer correction accepted: the model registered as `har_rv` /
   `har_rv_fixed_extension` in every frozen campaign (C1–C6 and the canonical
   validation) is a plain `LinearRegression` on the log target over the frozen
   information-set columns (`development_models.py`, `canonical_validation.py`) — it is
   not the dedicated intraday HAR/HARQ of `src/mds650/har.py` (Gate 3), which was
   introduced later with true RV components and realized quarticity. Resolution:
   frozen artifacts keep the registered name verbatim (immutability); the code
   docstrings and every citing document now state the actual specification, and
   `docs/model_naming_note_v1.md` is the binding citation rule. No canonical Model
   Confidence Set contains the Gate-3 HAR; claims about either model do not transfer
   to the other. No frozen value, seed, or artifact was rewritten.
61. **Two-tier CI contract (2026-08-18)** — Reviewer correction accepted: the hosted
   CI previously ran only static gates. Now tier 1 (GitHub Actions, required) runs
   Ruff, strict mypy, and the hermetic pytest suite — 189/193 test files including
   property-based (hypothesis), synthetic end-to-end and schema/contract tests — with
   a coverage gate >= 80% of src/mds650 (81.03% at introduction). Tier 2 (local,
   scripts/run_local_evidence_gates.py) runs the full suite against the licensed
   evidence store plus SHA-256 verification of every gated file. The four
   tier-2-only test files and the reason each cannot run hosted are enumerated in
   docs/ci_contract_v1.md. Branch protection on the public mirror requires both
   tier-1 checks; force push remains allowed because the mirror is regenerated by
   scripts/publish_mirror.sh (filtered history). Mirror commits cannot carry
   verified signatures (history is rewritten on every publish); integrity relies on
   the publish script's dual verification, documented in the same contract.
62. **Physical immutability of frozen evidence (2026-08-18)** — Reviewer correction
   accepted: logical immutability (write_immutable_raw refusing byte replacement)
   did not stop out-of-band writes, as the frozen-manifest overwrite incident
   demonstrated. Now: (1) data/FROZEN_ARTIFACTS.json, an append-only registry
   pinning 61 frozen artifacts to their SHA-256 (LF-normalized text, raw parquet)
   managed exclusively by scripts/freeze_registry.py; (2) a hermetic tripwire test
   re-hashing every registered file on every CI and tier-2 run; (3) a writer guard
   mds650.storage.assert_outside_frozen raising FROZEN_ARTIFACT_WRITE_REJECTED,
   wired into the B2-confirmation builder/evaluator; (4) content-addressed writes
   (root/protocol_id/<sha256>.bin) as the required path for new frozen evidence —
   no update operation exists, only new versions; (5) OS read-only flags via
   --lock; (6) a GitHub Release snapshot of the frozen state on the public mirror.
   WORM/Object Lock is documented as unavailable on the current stack with
   compensating controls (docs/evidence_immutability_v1.md).
63. **Canonical state + reproducibility contract (2026-08-18)** — Two reviewer
   corrections accepted. (a) Stale-"current"-document risk: the project state is
   now a single generated artifact (data/CANONICAL_STATE.json + STATUS.md,
   generator scripts/generate_canonical_state.py) recording latest decision,
   frozen registry, gated pointers, active protocols with hashes, canonical
   result sources, future campaigns, CI contract and superseded documents; a
   hermetic CI test regenerates it and fails on any drift, and superseded
   documents (docs/architecture.md, reports/remaining_work_investigation_20260818.md)
   must carry a SUPERSEDED banner. (b) Computational vs data reproducibility:
   scripts/run_public_repro_demo.py runs the full methodological chain (PIT join,
   features, purge/embargo, three families, QLIKE, bootstraps, MCS, claim
   ledger) on redistributable synthetic data, tested in CI and packaged in a
   Dockerfile; docs/reproducibility_contract_v1.md states exactly what a third
   party can and cannot reproduce, and the Windows-path residual policy.
   Operationally, scripts/publish_mirror.sh now refuses to publish unless the
   tier-2 gates (including the ci-sim replica of the hosted hermetic job) pass —
   red CI runs and their failure emails stop at the local gate.
64. **Sequential multiplicity policy + transport-retry fix (2026-08-18)** — Two
   reviewer corrections accepted. (a) Within-campaign Holm cannot undo the bias
   of launching campaign k+1 after seeing campaign k; existing retrospective
   results stay capped at EXPLORATORY_DESCRIPTIVE permanently, and every FUTURE
   confirmatory campaign is governed by docs/sequential_multiplicity_policy_v1.md:
   alpha spending alpha_k = 0.05/(k(k+1)) over an open-ended sequence (Phase 8
   one-shot = k=1 at 0.025; Phase 9 evaluation = k=2 at 0.00833; binding
   threshold is the smaller of the spending budget and any frozen protocol
   alpha), e-values + test martingale + always-valid p-value reported alongside
   registered tests (mds650/sequential.py, unit-tested), and a pre-registered
   maximum of 3 further confirmatory campaigns this thesis cycle. Frozen
   protocol documents are not edited (decision 62); the policy composes with
   them. (b) ProviderHTTPClient now retries httpx transport errors (timeouts,
   resets, disconnects) inside the retry loop with the same exponential backoff
   as 429/5xx, preserving the last exception as the cause — previously a single
   transport error bypassed max_retries entirely (src/mds650/providers/base.py;
   regression tests in tests/unit/test_provider_client.py).
65. **Four-contrast hypothesis structure replaces the B1-first precondition
   (2026-08-18)** — Research Program v2 §0 corrects a premise that has governed
   every campaign so far. The registered framing required Delta_B1 > 0 *before*
   Delta_B2 could be interpreted. In nested information sets that ordering is not
   how information behaves: interactions, suppressor effects, redundancy,
   non-linearity and regions where B2 is only interpretable conditional on B1 all
   make a weak isolated B1 compatible with a real joint contribution. From this
   decision forward, the estimand set is **four contrasts plus one interaction**,
   all reported together and never cherry-picked:
   Delta_B1 = L(B0) - L(B0+B1);
   Delta_{B2|B1} = L(B0+B1) - L(B0+B1+B2);
   Delta_{B2|B0} = L(B0) - L(B0+B2);
   Delta_Total = L(B0) - L(B0+B1+B2);
   Delta_Interaction = Delta_Total - Delta_B1 - Delta_{B2|B0}.
   The scientific hypothesis is now "the option information set contains
   incremental predictive information over B0, and an identifiable part comes from
   recent transactional activity B2 — as a marginal effect **or** as an interaction
   with B1", replacing "B1 must win first". This decision is registered **before**
   any campaign reports the four-contrast set as primary, as required. It does not
   reinterpret any frozen result: C1-C6 were evaluated under the old two-contrast
   ladder and their recorded verdicts stand unchanged (decision 62). Delta_Total
   was already reported exploratorily under decision 56; that reading is consistent
   with this structure. Multiplicity: the four contrasts plus the interaction form a
   single Holm family of five per campaign, and the campaign itself still consumes
   one step of the decision-64 alpha-spending sequence.
66. **Discovery/Validation/Confirmation freeze (2026-08-18)** — Research Program v2
   Block 1 executed. Three temporally separated universes are frozen in
   `docs/DISCOVERY_VALIDATION_CONFIRMATION_PROTOCOL.md` and
   `artifacts/rp2_block1_partition/partition.json`
   (partition_sha256 93566e5771cb4eb7f4badf1bfc2c2cc9a491b45a4324fa141bd240f469b2a168):
   D = 2024-08-02..2026-03-23 (389 sessions), V = 2026-03-24..2026-07-17 (80
   sessions), C = the sealed Phase 8 one-shot cohort, which is recorded by protocol
   reference and **never enumerated or read**. Because every retrospective window in
   this project has already been observed, no retrospective sample can serve as C;
   this is stated rather than worked around. Selection of models, targets, horizons
   and features happens only in D and V. Every retrospective analysis produced by
   Research Program v2 Blocks 2-11 carries the label
   `EXPLORATORY_MECHANISM_DISCOVERY`, which is what makes them compatible with the
   decision-52 moratorium. Disclosed limitation: the first ten Phase 8 sessions
   (2026-07-20..07-31) coincide with the already-read C2 holdout window, so only
   2026-08-03..08-28 is strictly unobserved.
67. **Both discovery and validation reclassified as exploratory (2026-08-19)** — The
   D/V/C freeze of decision 66 gave V a quasi-confirmatory role ("choosing among a
   limited number of specifications"). In practice V was read for the specification
   comparisons of Blocks 3 and 8, the model-family choice, the recalibration
   decision and the 36-target battery of Extension 1, and each of those fed back
   into what was reported. A sample used for selection cannot also confirm.
   **Both D and V are therefore exploratory**, every result on either carries
   `EXPLORATORY_MECHANISM_DISCOVERY`, and replication across the two is evidence
   against a single-era accident rather than confirmation. The only confirmatory
   evidence available to this project is a cohort collected under a frozen protocol
   and read once; none has been read (`sealed_cohorts_read = 0`). This decision
   changes no frozen result; it changes what may be claimed from one.
68. **Clark-West restricted to nested linear models (2026-08-19)** — The Clark-West
   adjustment is derived for a linear model whose restricted form is a parameter
   restriction of the unrestricted one. A gradient-boosted tree fitted on a larger
   feature set is a different function class, not a nested restriction, so the
   adjustment has no derivation there and inflates the statistic toward
   significance. `clark_west_terms` now requires an explicit `nested_linear`
   assertion and refuses otherwise; the tree families are compared with the
   session-blocked bootstrap instead. Any Clark-West figure previously reported for
   a tree family is withdrawn.
69. **Ex-post max-|t| power superseded by blocked simulation (2026-08-19)** — The
   direction-contrast power figure rescaled the largest |t| over 36 searched targets
   by sqrt(n). The maximum of many noisy statistics is biased upward by
   construction, so that figure is an optimistic bound that grows more optimistic
   with the number of targets searched, and it is withdrawn as a design input.
   `src/mds650/rp2/power.py` replaces it: the target, score, sign and effect are
   frozen before simulation, the effect is shrunk by sqrt(2 ln k) standard errors
   for selection, the null is generated by circular block resampling of observed
   session scores, and every result reports its own null rejection rate so a
   mis-sized test cannot present a power number. The Supabase rows carrying the old
   method are relabelled `ex_post_max_t_INVALIDATED` and excluded from the public
   view rather than deleted.
70. **B1 and B2 are cut from disjoint rows (2026-08-19)** — Both feature blocks are
   derived from one option tape, and both windows were `[origin - 1920 s,
   origin - 120 s]`: the same interval. "Does flow add information beyond the
   surface?" asked of overlapping rows is partly a comparison of B2 against itself.
   B1's snapshot now ends where B2's longest window begins — `[origin - 5520 s,
   origin - 1920 s)` against `[origin - 1920 s, origin - 120 s]` — and
   `assert_disjoint_from_flow_window` fails the run if the constants drift back into
   overlap. The cost is a staler surface, which is recorded rather than absorbed.
   This buys row-disjointness, **not** independence: a contract enters the surface
   only because it traded, so quote selection is still driven by flow. Every result
   computed on the previous overlapping windows is superseded by the rebuild, not
   restated.
71. **Time to expiry is exact and 0DTE is priced (2026-08-19)** — Tenors were whole
   calendar days floored at one, so a contract expiring at 16:00 on the session being
   processed was priced as a one-day option; at noon that overstates its variance
   sixfold, in the fastest-growing and most heavily traded part of the surface. Tenor
   is now measured in seconds from the origin to the 16:00 ET close on the expiry
   date, and an expired contract returns zero and is dropped rather than priced.
72. **The forward is measured from parity, not assumed (2026-08-19)** — Moneyness,
   delta and the parity residual assumed zero rates and zero dividends. At a 4-5%
   rate over 90 days the forward sits about 1% above the spot, which moves a 25-delta
   strike by several delta points and made the parity diagnostic report financing as
   a quote defect. Rather than plug in an external curve, the forward is read out of
   the quotes: `C - P = D (F - K)` is an arbitrage identity, so a least-squares line
   across co-strike pairs returns the discount factor and the forward the market is
   quoting, with the implied rate and dividend yield as by-products. The measurement
   is noisy at this quote staleness — co-strike mids come from different instants —
   so fits outside a plausibility band are refused, the forward falls back to the
   spot for those expiries, and the count of expiries where parity did fit travels
   with the panel.
73. **Multi-leg prints carry volume but not direction (2026-08-19)** — A side tag on a
   spread leg describes how that leg crossed the NBBO, not what the trader was
   expressing: the short leg of a call vertical prints `bid_side` while the order is
   bullish. Every signed channel, including all Greeks-weighted flow, was reading
   direction out of structures that have none. Multi-leg prints are identified from
   the rise in the contract's running `multi_vol` total and are now unsigned; they
   still count as volume and their share of each window is a feature.
74. **One session-grid builder, and callers that respect its length (2026-08-19)** — The
   calendar fix of decision 65 corrected `mds650.rp2.bars` and left three callers
   wrong. `build_session_grid` replaced a holiday's zero length with the full session,
   rebuilding the fabrication the zero prevented; `rp2_block4_b0_panel.py` sized its
   origins from a module constant in three places; and `rp2_block3_target_panel.py`
   kept a private copy of the grid builder, backward fill and all, in the block that
   builds the **targets**. Blocks 3 and 4 now derive origins from `grid.minutes`, drop
   origins whose window would reach before the first observed minute, and call the
   shared builder. Measured effect: block 4 dropped 54 of 2,838 session-assets as
   "too much missing data" before — every early close, because the fixed grid invented
   180 minutes of NaN and the fill-share gate then judged them missing — and drops 0
   after, growing the panel from 183,744 to 185,351 origins. Block 3's published
   conclusions move only in the fourth decimal, because its first origin is minute 120.
   All results computed on the previous panels are superseded by the rebuild.
75. **WITHDRAWN AND REPLACED — B0 was market-blind in *both* samples (2026-08-19)** —
   This decision originally recorded that "B0 means underlying state plus market-wide
   state in discovery and underlying state alone in validation". **That was wrong.**
   `market_control_rows` did differ (71,192 in D, 0 in V), but those columns were only
   ever read by Block 4's internal `b0_market` ladder variant: `B0_FEATURES`, the
   registry every block from 7 onward reads, contained eighteen entries and none of them
   was SPY or QQQ. The baseline was identical across the two samples — identically blind
   to the market. The real defect was larger than the one recorded: **every B2 increment
   in this programme was measured against a baseline that could not see the market**, and
   a model blind to the index attributes common movement to the only thing it can see.
   SPY and QQQ one-minute bars were acquired for the 289 sessions that lacked them (418
   FMP requests, no empty payloads, 100 % coverage in both universes), the four columns
   are registered in `B0_FEATURES`, and the programme was rebuilt. **The finding survived
   the control**: the Block 7 discovery Wald rose from 206.8 to 241.7 and validation was
   unchanged at p = 0.062, so the incremental information is not market beta.
76. **A registered feature must reach the panel, and a panel column must be declared
   (2026-08-19)** — `build_design` skips columns absent from the panel "so a partially
   built panel degrades to a smaller design rather than crashing", which meant the B2
   registry could claim four features the builder cannot produce — concentration and
   arrival-shape statistics are not prefix-summable and exist on the 5-minute window only
   — and nothing said so. The registry now generates them for that window alone (58
   features, not 62), and `tests/contract/test_feature_registry_reaches_the_panel.py`
   fails in both directions: a registered feature missing from the panel, and a panel
   column that is neither a registered feature nor a **declared** diagnostic. The market
   controls sat outside the registry for the whole programme precisely because there was
   no list for them to be absent from.
77. **Trade selection flattens the skew and leaves the level alone (2026-08-19)** — B1 is
   reconstructed from the NBBO carried on option *trades*, so a contract enters the
   surface only because somebody traded it. Rebuilding 184,632 origins from an
   independent quote feed is millions of directed requests and is not affordable, so the
   bias was measured instead: `scripts/rp2_block5b_independent_surface.py` builds the same
   surface twice at 36 sampled origins, once from traded NBBO and once from the *listed*
   chain quoted contract by contract, over a matched log-moneyness span. Result: the
   traded surface understates put skew by 46 % (slope −0.249 against −0.461, t = −3.56)
   and its at-the-money level is essentially unbiased (−0.0010 in volatility, t = −2.83,
   against a level of 0.31). `b1_iv_30d`, the surface feature every later block consumes,
   is therefore near-free of this selection; the skew features are not, and any claim
   resting on them carries this correction. Cost: 1,152 directed quotes, zero empty, no
   chain download. The listing is taken `as_of` the session — without that the endpoint
   answers with today's chain, and quoting contracts that were not yet listed returns
   silence that would have been mistaken for illiquidity.
78. **The variance-carry proxy overstated economics by an order of magnitude and a sign
   (2026-08-19)** — Block 11 reports a Sharpe near +77 on a synthetic short-variance
   position marked at implied minus realised variance. `scripts/rp2_block11b_forward_economics.py`
   replaces it with the instrument: one option contract per origin selected point-in-time
   from what was quoted at entry, entered at the ask, exited at the bid a horizon later,
   delta-hedged at the entry delta, with fees and slippage per contract per side and a
   book capped per name and in gross. Every net Sharpe is **negative** — −23.8 to −24.1
   in discovery over 5,758 legs, −38.8 to −41.3 in validation over 954 — with execution
   cost at **71 % of gross P&L in discovery and 148 % in validation**, and every deflated
   Sharpe probability at 0.000. Adding B1 and B2 makes it marginally worse. The proxy's
   number was not a smaller version of this one; it was a different sign, because it never
   paid a spread on a contract anybody could buy.
79. **The EWMA challenger was a smoothed copy of the answer (2026-08-20)** — Block 4 built
   its EWMA benchmark as `ewma_variance(np.sqrt(rv30))`: an exponentially weighted mean of
   the square root of the very target it was scored against, not a forecast from observed
   returns. `causal_ewma_horizon_variance` replaces it with the RiskMetrics recursion
   `h_t = 0.97 h_{t-1} + 0.03 r_{t-1}^2` over one-minute returns, one recursion per asset,
   carried across session breaks, with `RV30_hat = 30 h_t`. Rebuilt on the same bars, the
   B0 panel is byte-identical (`c2d230c3…`), every other challenger is unchanged to five
   decimals, and the EWMA QLIKE moves from **0.28074 to 0.18923** in discovery and from
   **0.27923 to 0.23134** in validation. The corrected challenger is *harder* to beat, not
   easier: the old one was leaky **and** mis-scaled, because it exponentially smoothed a
   standard deviation and then reported it as a variance. B0 still beats it — 0.14243
   against 0.18923 in D and 0.17622 against 0.23134 in V — on 61,336 and 12,672 scored
   rows, which is every test row in both roles. Its calibration slope, 0.839 and 0.759, is
   reported as measured and is not corrected. The recursion runs over Discovery and
   Validation in one calendar order rather than per partition: Discovery ends 2026-03-23
   and Validation opens 2026-03-24 with no overlap, so restarting at the boundary threw
   away state that is strictly past information. Measured on the real bars, that reset
   moved Validation's first session by up to **50.4 %** and its second by 1.3e-05, and was
   exactly zero from the fifth session on; the reported Validation QLIKE does not move,
   because its test window opens 48 sessions after the boundary.
80. **B1 was the option market half an hour ago, and 40 % of the rows were lost to a
   diagnostic (2026-08-20)** — RP2-v2 ended B1's snapshot 1 920 seconds before the forecast
   origin so that no tape row could feed both B1 and B2. The contrast is conditional —
   `E[Y | B0, B1, B2]` against `E[Y | B0, B1]` — so row-disjointness was never required, and
   it cost B1 the one thing it exists for. `src/mds650/rp2/b1_snapshot.py` now reads
   `[t - 120 s - 30 min, t - 120 s]` and keeps each contract's last quote. Rebuilt over all
   184,632 origins, the median quote age **against the forecast origin** falls from
   **2,588 s to 579 s** and the P95 from **2,941 s to 758 s**, with zero post-cutoff
   observations and zero duplicate contracts per snapshot (verified over 66 origins of a
   real session carrying 259,274 tape rows, 538 contracts per snapshot at the median).
   Separately, the primary B1 set is cut to the ten B1-core features. `b1_implied_rate` and
   `b1_implied_dividend_yield` fit on 59.7 % of origins, and because they were in the
   primary set every nested contrast dropped the other 40 %: the common evaluation mask held
   **90,548 of 152,954** discovery rows. The two are retained as B1-rich, reported and
   hashed, and the mask becomes **149,206 of 152,954 (97.5 %)** in discovery and **31,471 of
   31,678 (99.3 %)** in validation. The attribution is not flattering to the window and is
   reported as measured: on the new panel the old 26-feature set keeps 56.6 % of discovery
   rows, *fewer* than the 59.2 % it kept on the stale panel, because a fresher window sees
   fewer contracts and fits parity less often. The rows come from the core/rich split; the
   window buys freshness. Two features are added because B1-core names them and they did not
   exist: `b1_smile_level`, the at-the-money level every shape feature was already measured
   against, and `b1_surface_coverage`, the share of four grid requirements the snapshot met.
   Block 5b, which measures the trade-sampling bias of decision 77 against an independent
   quote feed, now reads the window through the same rule; in RP2-v2 it defined its own and
   audited a surface the panel did not carry.
81. **B2 measured its economics on the provider's clock, and priced 0DTE as a full day
   (2026-08-20)** — every tape row carries two timestamps. `created_at` is the operational record-creation
   stamp, which `docs/provider_timing_pit_contract_v22.md` registers as a *proxy* for
   availability and explicitly not as proven publication, receipt or provider-confirmed
   visibility; `executed_at` is when the trade happened and answers economics. Using the
   proxy as an availability bound is conservative, because a record cannot be created before
   the event it records; reading it as evidence of provider behaviour is not supported. Block 6 selected windows on availability, correctly, and then also
   chose the spot minute, the interarrivals and the decay intensity on it, so provider
   behaviour entered the features as market behaviour. `src/mds650/rp2/option_clock.py`
   separates them: spot as-of, Greeks, tenor and intensity now run on `executed_at`, and
   only visibility runs on `created_at`. Time to expiry was
   `max(expiry_date - session_date, 1 day)`, so a contract with four hours left was priced
   as if it had twenty-four, and 0DTE and 1DTE at the same strike collided in the contract
   key. It is now `(expiry_close_utc - executed_at) / (365.25 x 24 x 3600)`. A second floor
   was hiding inside `black_scholes_greeks`, `MIN_TENOR_YEARS = 1/365`, which silently
   re-rounded every 0DTE contract back up to a day and would have made the exact clock
   change nothing where it mattered most; it is now one minute, which is all a square root
   needs. Rebuilt over all 184,632 origins: `b2_5m_vega_flow_short_dte` moves by 7.4 %,
   `b2_5m_gamma_flow` by 3.7 %, the vega and delta flows by about 1.3 % at the median, and
   33 of 56 shared features do not move at all. The contract-key collision affected 0.9 % of
   windows. The clock swap itself is small in this provider's data — median latency is
   0.073 s, so the two clocks nearly coincide — and it is now correct by construction rather
   than by the provider's speed. Five features are added because the mechanism was
   unmeasurable without them: `zero_dte_premium_share`, `zero_dte_signed_premium` and
   `zero_dte_trade_share` per window, which show that **11.9 % of trades and 4.3 % of
   premium** in a five-minute window are same-session expiries. `mean_latency_s` becomes
   `mean_provider_latency_s` — the name the master plan gives it, kept, with the
   accompanying disavowal that `created_at - executed_at` is a record-creation lag and
   not proven provider delivery behaviour (`docs/provider_timing_pit_contract_v22.md`);
   using it as an availability bound is conservative, reading it as a measurement of the
   provider's pipe is not supported — and `median_age_s` becomes `mean_age_s` because it was always
   the mean. A session whose tape cannot be read is now recorded by name as a provider
   failure rather than arriving downstream as a window in which nobody traded. Verified on a
   real session of 304,386 tape rows: 1,607,405 events used across all windows, **zero PIT
   violations**, and zero rows where execution followed publication. Two further corrections
   followed from the same principle. The tape arrives in publication order and latency does
   not preserve execution order — **42.1 % of adjacent rows are inverted** over 725,914 rows
   of three sessions — so feeding those timestamps to an exponential decay made it amplify
   rather than decay; the recursion now runs on the execution-ordered permutation and is
   mapped back, and window spans and interarrival gaps are taken from the window's extremes
   and from sorted gaps rather than from its first and last published rows. The measured
   effect is small, 0.17 % on the decay innovation, because the inversions are sub-second
   and the decay constant is much longer; it is now correct by construction rather than by
   that coincidence. And the expiry close comes from the exchange calendar rather than a
   fixed 16:00: **five sessions in the study window close at 13:00**, where the fixed time
   would have handed every same-day contract three hours it never had, straight into the
   0DTE Greeks. A session whose tape cannot be read, a session too thin to build
   microstructure from, and a window in which nobody traded are three separate facts and are
   now counted separately: 0 provider failures, 0 sparse sessions, and 0.226 % empty
   five-minute windows. Ordering by execution alone would have introduced a point-in-time
   violation of its own — an earlier-executed print the provider had not published yet would
   have raised the intensity of a later-executed one it had — so the decay is now evaluated
   *at* each instant over the rows visible there: `decay_intensity_at` takes the cutoff and
   the window start, ages every visible row on the exchange clock, and admits none the
   provider had not published. `decay_intensity_innovation` is therefore redefined as the
   rise in intensity across the window rather than the last row minus the window mean; it
   moves by 106 %, and that is a change of definition, not a correction of arithmetic.
   Evaluating the window start at the exact instant rather than at an earlier origin keeps
   the feature defined everywhere: taking it from a lagged origin left the first six origins
   of every session undefined and cost 9.3 % of evaluation rows under the fail-closed rule.
   Finally, the coverage accounting was
   itself incomplete: a session-asset the B0 panel carried but the tape inventory or the bar
   grid did not was skipped before any counter saw it, so every number in the artifact
   described only the part of the study that happened to be complete. The denominator is now
   what the study asked for. Measured: **2,814 of 2,814 session-assets**, with zero missing
   inventory entries, zero missing bar grids, zero provider failures and zero sparse
   sessions. One enumerable state is encoded rather than imputed: a window in which nobody
   traded, 0.226 % of five-minute windows, sets `is_empty_window` to 1 and its three
   per-trade averages to 0. A NaN there would be honest and would also remove the origin
   from every contrast under the fail-closed rule; the indicator lets a model read the zeros
   as an absence. Fold-local imputation of the general case is its own gate. **All 70
   features now cover 100 % of the 184,632 origins**, against a minimum of 59.7 % before the
   gate. One further mistiming, pre-existing and not a point-in-time violation: bars are
   labelled by their start, so `closes[m]` is the price at the *end* of minute m and a trade
   executed inside that minute was marked at a price from its own future. The whole window
   still sat before the forecast origin, so no forecast ever saw the future; what was wrong
   was the exposure of each trade. Marking at the last completed bar moves
   `b2_5m_delta_flow` by 1.06 %, `b2_5m_gamma_flow` by 1.59 % and `b2_5m_vega_flow` by
   0.49 % at the median across essentially every window, and drops the opening minute's
   prints. Those are the most active minute of the day and sit inside the thirty-minute
   window of every early origin, so dropping them would have taken 9.1 million trades and
   28.7 billion of premium out of 2,799 windows; they are marked at the session's opening
   print instead, the earliest price that exists. And the Greeks floor is applied only to a
   non-positive tenor now: a 0DTE contract with one second left keeps that second, where a
   sixty-second floor would have flattened exactly the gamma and vega that make it
   interesting. The opening mark is never borrowed from the close: two of the six bar
   stores carry no `open` column, and filling it would have handed their opening-minute
   trades the price at the *end* of that minute. Those prints are dropped instead, which
   costs 0.037 % of thirty-minute trade volume across 347 windows and is a loss the data
   actually has rather than a number invented to cover it.
82. **One hundred dimensions against eighty validation sessions (2026-08-20)** — the primary
   B2 information set carried every channel the block emits, at both windows: 68 features,
   making a `B0+B1+B2` design 101 columns wide against 389 discovery and **80 validation
   sessions**. That is 1.25 features per independent validation session, which is estimation
   variance rather than information. `configs/rp2_v3_feature_sets.json` freezes five sets —
   `B0_CORE` (22), `B1_CORE` (10), `B2_CORE` (12), `B1_RICH` (18), `B2_RICH` (56) — and
   `src/mds650/rp2/feature_registry.py` is the only place that decides what is in them.
   `panel.py` loads them rather than restating them, because a second copy of a feature list
   is a copy that drifts, and that is now a test. The core dozen is the mechanism list of the
   master plan's section 7, chosen for economic mechanism, coverage, stability and
   point-in-time availability — never for an individual feature's historical p-value, which
   is how a null becomes a finding. Measured on the real panels: the design falls from
   **101 columns to 45**, evaluation rows per fitted column rise from 316 to 718 in
   validation and from 1,498 to 3,405 in discovery, and the common evaluation mask is
   unchanged at 98.0 % of discovery and 99.8 % of validation rows — the reduction costs no
   evidence. Core coverage on the rebuilt panels is 98.93 % at worst (`rv_week`), 99.34 %
   for B1 (`b1_risk_reversal_25`) and 100 % for every B2 core feature. Each set declares a
   coverage floor and `load_merged_panel` enforces it on every run — **within each partition,
   not across them**, because validation is a sixth of the rows and a complete discovery
   partition would otherwise hold the average above a floor validation had already broken.
   Measured per role: worst B0 coverage 98.71 % in discovery and 100 % in validation,
   worst B1 99.26 % and 99.76 %, and 100 % for every B2 core feature in both. The same
   floor is checked on the two segments each run fits and scores, because a partition can
   hold its average while the held-out tail it is scored on falls through — measured at
   0.6 and 0.8 train shares, the worst segment coverage is 97.84 %, so it does not bind
   today and a future gap cannot become a result. A floor nobody checks is not a floor. `registry_sha256` hashes the sets and their floors and ignores the
   prose beside them, so a run's provenance moves when a feature moves and not when a
   sentence is edited. Registry `3c108a14a5a88e4d…`.
83. **A missing diagnostic removed the origin from B0's evaluation too (2026-08-20)** — the
   common mask of a nested contrast was "every design column is finite", so a single absent
   B1 or B2 feature dropped that origin from *every* set in the comparison, B0 included. The
   larger information set was then judged on a sample its own missingness had chosen, and the
   smaller one was credited with rows the contrast never used. `src/mds650/rp2/preprocessing.py`
   replaces it. The mask becomes the master plan's `M = valid target ∩ valid keys ∩ valid
   availability` — availability being whether the join found option data at that origin at
   all, read from `b1_surface_coverage` and `b2_5m_is_empty_window`, both of which every block
   emits at every origin it produced. Values missing *inside* the design are imputed with the
   median of the fold's **training rows only**, and the fact that a value was absent survives
   as its own indicator column rather than being dissolved into that median. Nothing is learned
   from the rows being scored: a validation row of 10⁴ or 10⁻⁴ leaves the training median,
   centre and scale bit-identical, which is a test. A feature complete in training earns no
   indicator, because a column that is constant by construction costs a degree of freedom and
   says nothing; its absence at scoring time is imputed and the run records that it happened.
   Measured on the real panels through Block 8: the evaluation mask rises from **149,837 to
   152,954** discovery rows and from **31,601 to 31,678** validation rows — every origin the
   blocks produced. Three features are imputed in discovery (`rv_prev_day`, `rv_week`,
   `b1_risk_reversal_25`) and one in validation (`b1_risk_reversal_25`), each with its own
   indicator, so the `B0+B1+B2` design is 48 columns in discovery and 46 in validation rather
   than 45. The tensor and sequence arms of the level-4 extension keep the plain
   standardisation: they are inputs the registry does not describe and are never part of a
   primary contrast.

84. **The study window for RP2 is the frozen partition, by recorded configuration change
    (2026-08-21)** — the repository stated two windows and had never reconciled them.
    `AGENTS.md` froze `2025-07-21` through `2026-07-21` (end exclusive) on the strength of the
    window probe; `artifacts/rp2_block1_partition/partition.json`, written 2026-08-18, covers
    D `2024-08-02..2026-03-23` (389 sessions) and V `2026-03-24..2026-07-17` (80), and every
    RP2 and RP2-v3 artifact was built on it. The rule itself says widening or shortening
    requires another recorded configuration change, so this is that change: **the partition is
    the RP2 study window**, and the twelve-month rule is retained for the acquisition
    programme it was written for. Measured against
    `artifacts/rp2_block1_partition/inventory.jsonl` before deciding: of the 389 development
    sessions, **170** fall inside the twelve-month window and all 80 validation sessions do.
    Adopting the twelve-month window would therefore have discarded 219 development sessions —
    a 56 % reduction — requiring Block 1 to be re-run with a lower bound it does not have, and
    superseding every frozen result the repository cites, to answer a different question on a
    smaller sample. The programme owner's reasons, recorded as given: it preserves D=389/V=80,
    uses the rebuild already completed, keeps the statistical power of every contrast, and
    does not stall the project. What this decision does **not** do is change any number: no
    sample was widened, nothing was re-fitted, and the artifacts are exactly the ones that
    existed before it. It records which of two written statements governs, and
    `configs/rp2_v3_study_window.json` is where publication reads it.
