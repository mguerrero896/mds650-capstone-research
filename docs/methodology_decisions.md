# Methodology decisions (recovery baseline)

Status: recovery baseline, 2026-07-21. These decisions govern later implementation. Bounded
authenticated provider audits are retained as evidence; they do not authorize backfill,
normalization, pilot construction or modeling.

1. **Target** — RV30 only. At origin `t`, use the fully observed close `C(i,t)` and the next
   thirty consecutive one-minute closes. Compute `r(i,t+j)=ln[C(i,t+j)/C(i,t+j-1)]` for
   `j=1..30` and `RV(i,t:t+30)=Σ(r(i,t+j)^2)`. Exactly 31 prices and 30 returns are required.
2. **Candidates and freeze** — Audit SPY, QQQ, AAPL, MSFT, NVDA, TSLA, AMZN and META
   together. Freeze 4–6 only by coverage, quality, timestamp integrity, contract resolution
   and verified common overlap; predictive results are excluded.
3. **Benchmarks** — B0 controls; B1 adds independently verified ordinary PIT IV/skew/term
   structure; B2 adds unusual activity. Primary contrast is `Delta_Q = QLIKE(B1)-QLIKE(B2)`.
4. **Evidence state** — The current manifest is immutable exploratory v0. It is not a v1
   acceptance result. The repeated eight-asset depth probes are retained and classified as an
   idempotency defect.
5. **Timestamp policy** — FMP bar start/close semantics, exact origin close, last valid origin,
   early-close and halt handling must be proven before pilot work. Missing prices fail closed;
   interpolation is forbidden. Market completeness uses an exchange calendar, not 390 times
   calendar days.
6. **Unusual Whales** — Canonical aliases are `ivStart -> iv_start` and `ivEnd -> iv_end`.
   `event_iv_fields_present` is separate from `ordinary_option_state_pit_verified`; alert
   fields do not prove a historical ordinary option-state series. Document `created_at`,
   `start_time` and `end_time` independently. Do not assert `executed_at` without raw proof.
   The official term-structure and historical risk-reversal endpoints may establish field
   coverage, but a market date without an independent publication/availability timestamp keeps
   `ordinary_option_state_pit_verified=false` and cannot unlock B1.
7. **Earnings applicability** — Require `returned_symbol == requested_symbol`; use
   `applicable`, `not_applicable`, `unsupported` or `invalid_response`. ETFs do not inherit a
   company earnings contract.
8. **Prevalence** — Construct event and no-event forecast origins while preserving natural
   prevalence. Training-only weighting/subsampling must be documented; validation and final
   testing preserve the natural distribution.
9. **Statistical pre-registration** — Daily paired bootstrap keeps all observed assets on the
   same trading day. Primary/secondary/robustness analyses, Holm/BH use, MDE estimation from
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
12. **FMP bar-label evidence** — FMP's official intraday guidance says each response object is
    one minute and that a new point appears after the one-minute candle closes, but it does not
    specify whether `date` labels the interval start or interval close. The retained authenticated
    samples show regular-session labels from `09:30` through `15:59` (and early-close labels
    through `12:59`), which is consistent with start-labelled bars but is not sufficient to accept
    the convention. Until FMP supplies an explicit contract or a paired timestamp experiment
    establishes it, the gate remains `FMP_BAR_SEMANTICS_UNRESOLVED`; no origin close or RV30
    window may be constructed. Source: `https://site.financialmodelingprep.com/how-to/how-to-get-stock-intraday-data-with-fmp-apis`.
