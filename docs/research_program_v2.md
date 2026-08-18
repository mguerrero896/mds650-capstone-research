# Research Program v2 — Cascade to a Real, Defensible Signal

**Status:** `OWNER_SPECIFICATION — NOT YET EXECUTED`
**Recorded:** 2026-08-18 · transcribed verbatim-faithful from the owner's specification
**Nature:** execution program. Nothing in the repository was modified when this document
was written. Each block below is designed to be executed one at a time and verified before
the next one starts. Publication to the public GitHub repository happens **after**
execution, not before.

---

## 0. The premise to correct first

The current framing requires:

$$\Delta_{B1} > 0 \quad \text{and only then} \quad \Delta_{B2} > 0.$$

In **nested models this is not necessarily how information behaves**. There can be:

- interactions between B1 and B2;
- suppressor effects;
- redundancy between variables;
- non-linearities;
- regions of the state space where B2 works *only* conditioned on B1;
- a B1 that is individually weak but **necessary to interpret** B2.

Therefore at least **four contrasts** must be estimated:

$$\Delta_{B1} = L(B0) - L(B0{+}B1)$$
$$\Delta_{B2\mid B1} = L(B0{+}B1) - L(B0{+}B1{+}B2)$$
$$\Delta_{B2\mid B0} = L(B0) - L(B0{+}B2)$$
$$\Delta_{\text{Total}} = L(B0) - L(B0{+}B1{+}B2)$$

Plus **complementarity**:

$$\Delta_{\text{Interaction}} = \Delta_{\text{Total}} - \Delta_{B1} - \Delta_{B2\mid B0}$$

It is entirely possible that

$$\Delta_{B1} \approx 0, \quad \Delta_{B2\mid B0} \approx 0, \quad \Delta_{\text{Total}} > 0,$$

because the information is only interpretable **jointly**.

**Consequence.** Do not impose, as a mandatory scientific condition, that B1 must win
first in isolation. The correct hypothesis is:

> The options information set contains incremental predictive information over B0, and an
> identifiable part of that contribution comes from recent transactional activity B2 —
> either as a marginal effect or as an interaction with B1.

---

## 1. Data availability is not predictive information

Having full access to FMP, Massive, Unusual Whales, Supabase, millions of rows, PIT
storage and multiple models is **necessary but not sufficient**. Formally:

$$\text{data availability} \nRightarrow I(\mathrm{RV30};\, B2 \mid B0, B1) > 0$$

The current absence of a robust signal has **six** possible explanations:

1. B2 contains no real incremental information.
2. The information exists but is already embedded in B1.
3. The information exists but not at the RV30 horizon.
4. It exists only in certain assets, hours, events or regimes.
5. The current aggregation destroys the signal.
6. The predictive signal exists but is too small to overcome economic frictions.

Future research must **discriminate between these six**, not add variables indiscriminately.

---

## BLOCK 1 — Gate 0: freeze the discovery/validation/confirmation frame

Before creating any new variable, separate three universes.

**Dataset D — Discovery.** May be used for: feature engineering, horizon exploration,
mechanism identification, model-family selection, error diagnosis. **Produces no
confirmation.**

**Dataset V — Validation.** Used for: choosing among a limited number of specifications,
measuring calibration, estimating MDE, checking preliminary stability. **Produces no
definitive confirmation.**

**Dataset C — Confirmation.** Must be: entirely future, never observed, sealed protocol,
no changes once started, **read exactly once**.

The separation must be **temporal, not a random partition**:

$$D < V < C$$

**Approval rule.** Do not start another retrospective confirmatory campaign. Every new
retrospective analysis is labeled:

```
EXPLORATORY_MECHANISM_DISCOVERY
```

**Deliverable:** `DISCOVERY_VALIDATION_CONFIRMATION_PROTOCOL.md`
**Advance rule:** three temporally separated samples exist and are hash-frozen.

---

## BLOCK 2 — Gate 1: demonstrate operational PIT truth

B2 depends critically on what information was **actually available** at origin $t$.

For every trade or quote, retain:

- `exchange_timestamp`
- `provider_created_at`
- `provider_received_at`
- `local_received_at`
- `ingested_at`
- `reconciled_at`
- `revision_version`

Measure receipt latency:

$$\ell_i = t_i^{\text{local receipt}} - t_i^{\text{provider created}}$$

Report: median, P90, P95, P99, maximum, percentage of backfill, percentage of revisions,
rows appearing **only** in the historical tape, and differences between live stream and
historical tape.

**Rule.** The B2 cutoff must not be arbitrarily 60 seconds. It must satisfy:

$$c_{B2} \ge Q_{0.95}(\ell) + \text{safety margin}$$

If the observed P95 is 83 seconds, 60 seconds cannot continue to be used as if it were PIT.

**Gate approval:** stable P95; backfill below the registered threshold; revision rate below
threshold; clocks synchronized; no observation used before its receipt time.

**Deliverable:** receipt-latency / backfill / revisions ledger.
**Advance rule:** empirical cutoff approved.

---

## BLOCK 3 — Gate 2: validate that RV30 is the right target

B2 may fail to predict the standard sum of squared returns because the target carries
microstructure noise, or because the information materializes at another horizon.

In **discovery only**, evaluate:

$$RV_h = \sum_{j=1}^{h} r_{t+j}^2, \qquad h \in \{5, 15, 30, 60, 120\}$$

Only **one** may pass into confirmation as primary.

Also add:

**Bipower variation**

$$BV_t = \frac{\pi}{2}\sum_{j=2}^{n} |r_j|\,|r_{j-1}|$$

**Jump component**

$$J_t = \max(RV_t - BV_t,\; 0)$$

**Continuous variation**

$$C_t = RV_t - J_t$$

**Realized quarticity**

$$RQ_t = \frac{n}{3}\sum_{j=1}^{n} r_j^4$$

Options activity might predict: jumps rather than continuous variance; upside
semivariance; downside semivariance; tail events; **change** in volatility rather than
level; the conditional distribution rather than the mean.

**Additional hypotheses**

$$H_{B2,J}: I(J_{t,t+h};\, B2_t \mid B0_t, B1_t) > 0$$
$$H_{B2,\Delta RV}: I(\Delta RV_{t,t+h};\, B2_t \mid B0_t, B1_t) > 0$$

**Approval rule.** Choose target/horizon using **only D and V**. Freeze it before C.

**Deliverable:** RV / jump / semivariance / horizon comparison.
**Advance rule:** one primary target frozen.

---

## BLOCK 4 — Gate 3: build a B0 that is genuinely hard to beat

A weak baseline manufactures fictitious alpha. B0 must contain all public underlying
information that would reasonably be available.

Include:

- HAR and HARQ, intraday;
- $RV_{5m}$, $RV_{15m}$, $RV_{30m}$;
- session cumulative RV;
- previous-day RV;
- weekly RV;
- realized quarticity;
- semivariances;
- jump proxy;
- volume;
- dollar volume;
- underlying spread and liquidity;
- SPY return and RV;
- QQQ return and RV;
- sector ETF;
- VIX or a PIT proxy;
- intraday seasonality;
- day of week;
- proximity to open/close;
- earnings and macro events available PIT.

The baseline must approximate:

$$\mathbb{E}\left[RV_{t,t+30} \mid \mathcal{F}_t^{\text{underlying}}\right]$$

**Approval rule.** B0 must persistently beat: persistence, intraday mean, EWMA, simple
HAR, and a basic intraday GARCH. If B0 is not well calibrated, **no B1/B2 advantage is
interpretable**.

**Deliverable:** HARQ + market + liquidity baseline.
**Advance rule:** well-calibrated baseline.

---

## BLOCK 5 — Gate 4: redesign B1 as a volatility surface, not an isolated ATM IV

The current B1 may be under-representing ordinary options information. A single ATM IV at
30–60 DTE is excessive compression. Build an **arbitrage-aware** representation of the
surface.

### 5.1 Model-free implied variance

VIX-type approximation:

$$\sigma^2(T) \approx \frac{2}{T}\sum_i \frac{\Delta K_i}{K_i^2} e^{rT} Q(K_i) - \frac{1}{T}\left(\frac{F}{K_0} - 1\right)^2$$

Use: 7, 14, 30, 60 and 90 days.

### 5.2 Constant-maturity interpolation

For total variance:

$$w(T) = \sigma^2(T)\,T$$

Interpolate $w(T)$, **not** IV directly.

### 5.3 Surface shape

Include: ATM level; ATM change; 25-delta risk reversal; 25-delta butterfly; smile
curvature; left-tail slope; right-tail slope; term slope; term convexity; calendar-spread
deformation; surface PCA factors.

### 5.4 Variance risk premium

$$VRP_t = IV_t^2 - \hat{\mathbb{E}}_t[RV]$$

The informative part may live in the discrepancy between risk-neutral and physical
measures, not in absolute IV.

### 5.5 Quote quality

Include: relative spread; quote age; quote update intensity; cross call/put consistency;
put-call parity residual; no-arbitrage violations; surface fit error; number of valid
strikes; number of valid expiries.

**Approval rule.** B1 passes if

$$\mathbb{E}\left[L(B0) - L(B1)\right] > \delta_{B1}$$

in **at least two independent families**, after calibration and with temporal stability.

**Deliverable:** constant-maturity surface + VRP.
**Advance rule:** improvement in D/V, or a clear mechanism.

---

## BLOCK 6 — Gate 5: redesign B2 without destroying microstructure

The most likely problem with B2 is **premature aggregation**. Reducing thousands of trades
to nine variables in five-minute windows can eliminate: sequence, direction, clustering,
moneyness, DTE, Greeks, impact on quotes, and temporal dynamics.

### 6.1 Greeks-weighted flow

Instead of raw premium:

$$\text{VegaFlow}_t = \sum_i s_i\, \nu_i\, q_i$$
$$\text{GammaFlow}_t = \sum_i s_i\, \Gamma_i\, q_i\, S_t^2$$
$$\text{DeltaFlow}_t = \sum_i s_i\, \Delta_i\, q_i\, S_t$$

where $s_i$ is the inferred direction. Split by: call/put; bid/ask side; moneyness; DTE;
customer/dealer proxy; single-leg/multileg; sweep/non-sweep.

### 6.2 Abnormal flow innovation

What matters is not absolute flow but **surprise**:

$$B2_t^{\perp} = B2_t - \mathbb{E}\left[B2_t \mid \text{asset}, \text{time-of-day}, \text{volatility}, \text{volume}, \text{day}\right]$$

Expectation models trained **exclusively on prior history**.

### 6.3 Intensity and burstiness

Model: interarrival times; Hawkes intensity; clusters; acceleration; entropy;
concentration; persistence. A Hawkes approximation:

$$\lambda_t = \mu + \sum_{t_i < t} \alpha e^{-\beta(t - t_i)}$$

The innovation

$$\lambda_t - \mathbb{E}_{t^-}[\lambda_t]$$

may carry more information than trade count.

### 6.4 Trade-to-quote impact

Measure subsequent changes, still **before** the origin:

$$\Delta IV_i = IV_{t_i + \tau} - IV_{t_i^-}, \qquad \Delta \text{spread}_i, \qquad \Delta \text{mid}_i$$

This separates: trades that genuinely move the surface; passive prints; multileg; already
absorbed trades; spurious activity.

### 6.5 Moneyness × DTE tensor

Keep a grid

$$X_t[m, d, o]$$

with $m$ = moneyness bucket, $d$ = DTE bucket, $o$ = option type / aggressor side. Then use
group-lasso regularization, PCA, autoencoder, DeepSets or an event transformer — **but only
after demonstrating that the tabular baseline does not capture the signal**.

### 6.6 Separate activity types

Do not mix: opening vs closing; speculative vs hedge proxy; single-leg vs multileg;
earnings-related vs ordinary; index vs single-stock; retail-sized vs institutional-sized;
deep-OTM lottery flow vs ATM variance flow.

**Approval rule.** B2 must beat B1: on average; after residualization; under calibration;
in two families; without depending on a single feature, session or asset.

**Deliverable:** Greeks flow + intensity + sequence, target-blind features frozen.

---

## BLOCK 7 — The decisive experiment: DML and orthogonalization of B2

This is one of the most important experiments still to attempt. The correct question is
not whether a model with B2 happens to have lower loss, but whether **B2 contains
information that cannot be reconstructed from B0+B1**.

First:

$$m(X_t) = \mathbb{E}[Y_t \mid B0_t, B1_t]$$
$$g(X_t) = \mathbb{E}[B2_t \mid B0_t, B1_t]$$

Then generate cross-fitted residuals:

$$\tilde{Y}_t = Y_t - \hat{m}^{(-k)}(X_t)$$
$$\tilde{B2}_t = B2_t - \hat{g}^{(-k)}(X_t)$$

Finally:

$$\tilde{Y}_t = \theta^{\top} \tilde{B2}_t + \varepsilon_t$$

This allows the direct question:

$$H_0: \theta = 0$$

Must apply: temporal cross-fitting; day clusters; HAC; fixed regularization; **no use of the
holdout**. This does not replace QLIKE evaluation, but it identifies whether a structural
incremental relationship exists in B2.

**Deliverable:** DML of B2 on B0+B1.
**Advance rule:** preliminary incremental evidence.

---

## BLOCK 8 — Model ladder

**Level 1 — Baselines:** persistence; EWMA; HAR; HARQ; log-OLS; Gamma GLM; Tweedie GLM.

**Level 2 — Non-linear tabular:** LightGBM; CatBoost; monotonic gradient boosting; GAM;
Explainable Boosting Machine.

**Level 3 — Hierarchical.** A Bayesian partial-pooling model:

$$\theta_{a,r} \sim \mathcal{N}(\mu_\theta,\, \tau_\theta^2)$$

where $a$ is asset and $r$ is regime. This avoids two extremes: total pooling that hides
heterogeneity, and per-asset models that overfit.

**Level 4 — Trade sequence.** Only after preserving the tape: DeepSets; temporal
convolution; transformer with relative-time encoding; marked point process; neural Hawkes.

**Reinforcement learning is not used** for this problem: there is no sufficiently
identified policy, reward and simulator yet.

**Advance rule:** selection only in D/V.

---

## BLOCK 9 — Generalization validation

An aggregate walk-forward is not enough.

**Leave-one-asset-out.** Train on five equities, evaluate on the sixth:

$$A_{\text{train}} = A \setminus \{a\}$$

This tests whether the mechanism generalizes cross-sectionally.

**Leave-one-era-out.** Train on all eras except one.

**Leave-event-out.** Exclude: earnings; CPI; FOMC; payrolls; expiration; rebalance; triple
witching; market stress events.

**Leave-one-month-out.** Detects dependence on a particular month.

**Non-overlapping origins.** Besides the five-minute grid, repeat with origins separated by
30 minutes to eliminate target overlap.

**Stress regimes.** Separate: high/low VIX; high/low liquidity; open/midday/close;
earnings/no-earnings; high/low dispersion; positive/negative market return.

**Minimum criterion.** Do not require every subgroup to be positive. Require: no systematic
inversion; no single asset dominating the result; no month explaining more than a
predefined proportion; sign stability in the majority of blocks; positive meta-estimate
with heterogeneity reported.

---

## BLOCK 10 — Inference still to be added

**Clark–West for nested models.** When B1 and B2 are nested, conventional Diebold–Mariano
can be biased against the expanded model. Use the Clark–West adjustment:

$$f_t^{CW} = e_{0,t}^2 - \left[e_{1,t}^2 - (\hat{y}_{0,t} - \hat{y}_{1,t})^2\right]$$

It does not replace QLIKE, but it is an important sensitivity for nested predictive accuracy.

**Giacomini–White.** For conditional predictive ability:

$$\mathbb{E}[d_t \mid Z_t] = 0$$

This detects whether B2 works only under certain ex-ante observable conditions.

**Hansen SPA / White Reality Check.** Given the number of transformations and models, any
"best strategy" must survive: the Superior Predictive Ability test; the Reality Check;
bootstrap with temporal dependence.

**E-values or alpha spending.** For future sequential experiments:

$$\sum_k \alpha_k \le 0.05$$

One option:

$$\alpha_k = \frac{0.05}{k(k+1)}$$

This prevents an indefinite sequence of campaigns from eventually producing a false positive.

---

## BLOCK 11 — A QLIKE improvement is not yet economic alpha

Even if $\Delta \text{QLIKE} > 0$, the following have **not** been demonstrated: an
executable strategy; return; Sharpe; capacity; profitability after spreads; economic utility.

### Three possible economic bridges

**A. Delta-hedged option strategy.** Use the forecast to decide when to buy or sell
straddles, adjust vega/gamma exposure, and avoid trading when the estimated edge does not
exceed costs.

**B. Variance-risk strategy.** Build a proxy:

$$VRP_{t,h} = IV_t^2 - \widehat{RV}_{t,t+h}$$

Trade only when:

$$|VRP_{t,h}| > \text{costs} + \text{uncertainty buffer}$$

**C. Risk-management utility.** Even without direct P&L, measure: reduction in VaR
breaches; reduction in expected-shortfall error; lower tracking error of volatility
targeting; certainty-equivalent return; lower reserve capital.

### Economic metrics

Net P&L; Sharpe; Sortino; maximum drawdown; turnover; hit rate; expected shortfall;
capacity; profit per unit vega; utility gain; break-even transaction cost; deflated Sharpe
ratio; probability of backtest overfitting.

**Economic success criterion**

$$\mathbb{E}\left[\text{P\&L}_{\text{net}}\right] > 0$$

with an interval compatible with positive profitability, plus stability by asset and period.

---

## BLOCK 12 — Definitive prospective protocol

The signal will only be robust after a fully future test.

**Primary hypotheses**

$$H_{0,1}: \mathbb{E}\left[\Delta \text{QLIKE}_{B1}\right] \le \delta_1$$
$$H_{0,2}: \mathbb{E}\left[\Delta \text{QLIKE}_{B2\mid B1}\right] \le \delta_2$$

**Requirements**

- at least 60–120 sessions;
- first date strictly after the freeze;
- six assets or more;
- two genuinely independent families;
- a strong B0;
- immutable features;
- frozen inclusion rules;
- frozen MDE;
- frozen alpha spending;
- a single read;
- no model change after the result;
- economic result reported separately from the predictive result.

**Two valid families**

1. HARQ/GAM or a calibrated smooth model.
2. Gradient-boosted tree.

Ridge and log-OLS **do not** count as independent families.

**Success rule for B2**

$$\Delta_{B2\mid B1} > \delta_2$$

with: lower interval bound > 0; multiplicity controlled; both families positive in sign; at
least one family above the MDE; no adverse interaction between families; no dominant asset
or session; net economic improvement or positive utility.

**Replication.** Even with a positive result, a **second independent prospective window** is
required. One positive window does not demonstrate generalization.

---

## BLOCK 13 — Cascade execution map

| Order | Block | Deliverable | Advance rule |
|---|---|---|---|
| 1 | Freeze | `DISCOVERY_VALIDATION_CONFIRMATION_PROTOCOL.md` | Three temporally separated samples |
| 2 | PIT | Receipt-latency / backfill / revisions ledger | Empirical cutoff approved |
| 3 | Target | RV / jump / semivariance / horizon comparison | One primary target frozen |
| 4 | B0 | HARQ + market + liquidity | Well-calibrated baseline |
| 5 | B1 | Constant-maturity surface + VRP | Improvement in D/V or clear mechanism |
| 6 | B2 | Greeks flow + intensity + sequence | Target-blind features frozen |
| 7 | Orthogonalization | DML of B2 on B0+B1 | Preliminary incremental evidence |
| 8 | Model ladder | Smooth + tree + hierarchical | Selection only in D/V |
| 9 | Generalization | LOAO / LOEO / event / regime | No concentrated dependence |
| 10 | Inference | CW / GW / SPA / block-MCS | Survives multiplicity |
| 11 | Economics | P&L / utility after costs | Positive net value |
| 12 | Prospective | One-read future holdout | Binding result |
| 13 | Replication | Second window / implementation | External confirmation |

---

## BLOCK 14 — Supabase evaluation

Supabase is useful as: a public layer; a results catalog; an audit data mart; a dashboard;
a query API. It **must not become the primary scientific source**. Authority remains:

```
raw immutable evidence
  → manifests
    → protocol hash
      → code commit
        → derived artifacts
          → public read model
```

The connected instance has a broad structure (campaigns, contrasts, MCS, forecasts,
features, literature and documents), but the following must be corrected before presenting
it as professional infrastructure.

### Concrete problems

**Weak types.** Some numeric variables are stored as text, including trade counts. Some
timestamps also appear as text. They must be:

```
option_trade_count_5m      bigint
unique_contract_count_5m   bigint
forecast_origin_utc        timestamptz
```

**Fact tables without robust keys.** Add keys or unique constraints such as: `campaign_id`,
`block_id`, `origin_id`, `asset`, `model_role`, `information_set`, `timing_variant`.

**Incorrect evidence chain.** Records from different campaigns show repeated evidence
chains, or chains associated with the wrong campaign. Every campaign must carry:
`source_commit`, `protocol_sha256`, `input_manifest_sha256`, `result_artifact_sha256`,
`schema_version`, `generated_at`.

**Incomplete statistical results.** Several wild-bootstrap, Newey–West and global-Holm
columns are empty in the Supabase layer even though they are described in the artifacts.
They must be synchronized or explicitly labeled: `NOT_SYNCED`, `NOT_APPLICABLE`,
`AVAILABLE_IN_ARTIFACT_ONLY`. **Never leave an ambiguous NULL.**

**Security.** Public `USING (true)` policies on base tables are too broad. For a public
repository: private base tables; whitelisted public views; read-only RPC; sensitive columns
excluded; public bucket only for sanitized documents.

**Optimization.** Fix: foreign keys without indexes; duplicate indexes; RLS policies that
re-evaluate `auth.role()` per row; unused indexes; leaked-password protection.

---

## BLOCK 15 — Repository writing audit

The public writing is still too internal for an outside reader. The problem is not that the
information is irrelevant — it is that **governance and audit material occupies the place of
the scientific narrative**.

An external examiner or researcher should not have to decode `C2`, `C4c`, `C6`, `D003`,
`D006`, `R-020`, `decision 53`, `Gate 11`, `B1v3`, `PIT v2.4` before understanding the
research.

### Current problems

**1. Too many internal identifiers.** Identifiers are useful for traceability but must
appear *after* the descriptive name.

- Incorrect: `C6 B1v3 confirmation returned…`
- Better: `The retrospective 90-session B1v3 confirmation campaign (internal ID C6) returned…`

**2. The narrative mixes science and operations.** The introduction must not contain: task
counts; read tokens; `D:\` paths; scheduled-task names; serialization incidents; owner
decisions; collector status. Those belong in `docs/governance/`, `docs/operations/`,
`docs/audit-trail/`.

**3. Temporal inconsistencies.** The README is pinned to an earlier commit although the
repository advanced; it also says "decision 53 so far" when later decisions exist. It must
be **generated automatically from the canonical state**.

**4. Ambiguity in session counts.** Clearly distinguish: total panel sessions; warm-up
sessions; training sessions; OOS sessions; prospective sessions. Example:

```
80-session development panel:
  40 warm-up/training sessions
  40 out-of-sample forecast sessions
```

Do not alternate between "80 development sessions" and "40 evaluated sessions" without
explanation.

**5. Too many conclusions inside the abstract.** The current abstract tries to tell design,
PIT, campaigns, calibration, models, eras, positive results, nulls, Phase 8 and Phase 9. It
must answer only: question; data; method; primary result; contribution; limitation.

---

## BLOCK 16 — Recommended professional structure

```
README.md
docs/
├── 01_research_question.md
├── 02_data_and_point_in_time_design.md
├── 03_methodology.md
├── 04_results.md
├── 05_economic_evaluation.md
├── 06_limitations.md
├── 07_reproducibility.md
├── glossary.md
├── governance/
│   ├── decision_log.md
│   ├── campaign_registry.md
│   ├── claims_ledger.md
│   ├── multiplicity_register.md
│   └── incidents.md
└── operations/
    ├── collectors.md
    ├── storage.md
    └── recovery.md
protocols/
src/mds650/
tests/
artifacts/public/
artifacts/schemas/
```

---

## BLOCK 17 — Recommended README opening

```markdown
# Point-in-Time Option Information for Forecasting 30-Minute Realized Variance

This repository studies whether information from the US equity-options market
improves forecasts of next-30-minute realized variance for six liquid equities.

We compare three nested information sets:

| Set | Information available at the forecast origin |
|---|---|
| B0 | Underlying-price history, realized-variance lags, market controls and intraday seasonality |
| B1 | B0 plus the contemporaneous point-in-time option-implied volatility surface |
| B2 | B1 plus recent point-in-time option-trade activity |

The primary questions are:

1. Does option-market state improve forecasts relative to an underlying-only baseline?
2. Does recent option-trade activity provide additional information beyond option-market state?
3. Are any predictive gains stable across models, assets, market regimes and future samples?
4. Do the gains remain economically useful after transaction costs and operational latency?

The only completed prospective holdout currently provides no robust evidence that
B1 or B2 improves RV30 forecasts. Several retrospective periods contain positive
option-information effects, but these are reported separately because they are
model-dependent, era-dependent or exploratory. The repository therefore makes no
current claim of a generalizable or profitable trading edge.
```

This wording lets any reader understand the project without knowing the internal taxonomy.

---

## BLOCK 18 — What to keep and what to move

**Keep in the README:** question; B0/B1/B2; universe; target; design; primary result;
limitations; quickstart; reproducibility; current status.

**Move to governance:** numbered decisions; campaign counts; one-read tokens;
serialization; incidents; moratoria; full multiplicity; long hashes; historical paths.

**Move to operations:** scheduled tasks; collector scripts; Windows paths; storage guards;
alert files; recovery procedure.

**Move to appendix:** all sensitivity tables; MCS by block length; provider diagnostics;
invalidated claims; provenance trees.

---

# Appendix A — Execution notes

*Added when transcribing; not part of the owner's specification. These are prerequisites and
conflicts to resolve before or during execution — they change nothing in the program above.*

**A.1 Governance interactions to resolve first.**

- The premise correction in §0 changes the registered hypothesis structure (B1-first is no
  longer a precondition). This requires a numbered methodology decision before any campaign
  reports the four-contrast set as primary.
- Decision 52 imposes a moratorium on new retrospective campaigns. Blocks 3–10 are
  discovery/validation work, which the moratorium permits only under the
  `EXPLORATORY_MECHANISM_DISCOVERY` label defined in Block 1 — Block 1 must therefore run
  first, literally.
- Decision 53 (reporting hierarchy) continues to bind every deliverable produced by these
  blocks.
- Phase 8 (sealed, 30/30 on 2026-08-29) and Phase 9 must not be touched by any block. Block
  12 defines a **future** protocol; it does not modify the already-frozen ones.

**A.2 Blocks requiring new provider calls (cost and time).**

- Block 2 (PIT ledger) requires live dual-capture: streaming receipt timestamps compared
  against the historical tape. Only forward collection can produce it.
- Block 5 (surface) requires re-acquiring Massive quotes across strikes/expiries — far more
  volume than the current ATM-only extraction.
- Block 6 (microstructure) requires re-processing the full option tape with Greeks, which
  in turn needs the surface from Block 5.

**A.3 Compute-heavy blocks.** 6 (tensor + Hawkes), 7 (DML cross-fitting), 8 (level 3–4
models), 9 (all leave-one-out variants), 10 (bootstrap families). Expect these to dominate
the runtime budget.

**A.4 Publication.** Nothing here is published until its block is executed and verified.
Blocks 15–18 (writing audit, structure, README, keep/move) are the publication pass, and
they run **after** the science blocks so the new narrative describes real results.
