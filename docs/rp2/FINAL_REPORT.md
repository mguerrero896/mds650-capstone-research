# Research Program v2 — final report

**Run:** 2026-08-18 → 2026-08-19, autonomous cascade, Blocks 1–18
**Progress book:** `docs/research_program_v2_progress.md`
**Per-block documents:** `docs/rp2/block*.md`
**Gates at close:** ruff clean · mypy --strict clean over 268 files · full pytest suite green
**Sealed cohorts read: 0.**

---

## 1. Status of the eighteen blocks

| # | Block | Status | Advance rule |
|---|---|---|---|
| 1 | Gate 0 — freeze D/V/C | **COMPLETED** | PASS |
| 2 | Gate 1 — operational PIT truth | **COMPLETED** | PASS with amendment |
| 3 | Gate 2 — validate the target | **COMPLETED** | PASS |
| 4 | Gate 3 — hard B0 baseline | **COMPLETED** | PASS with condition |
| 5 | Gate 4 — B1 as a surface | **COMPLETED** | PASS on the mechanism clause; the two-family improvement rule FAILS |
| 6 | Gate 5 — B2 microstructure | **COMPLETED** | PASS |
| 7 | DML orthogonalization | **COMPLETED** | **PASS** |
| 8 | Model ladder | **COMPLETED** | PASS procedurally, NULL substantively |
| 9 | Generalization | **COMPLETED** | PASS in D, FAIL in V |
| 10 | Inference | **COMPLETED** | **FAIL** |
| 11 | Economics | **COMPLETED** | **FAIL** |
| 12 | Prospective protocol | **COMPLETED** (designed, not launched) | NOT_APPLICABLE — no read |
| 13 | Cascade execution map | **COMPLETED** | — |
| 14 | Supabase evaluation | **COMPLETED** | — |
| 15 | Repository writing audit | **COMPLETED** | — |
| 16 | Professional structure | **COMPLETED** (proposed) | — |
| 17 | README opening | **COMPLETED** (implemented) | — |
| 18 | Keep / move | **COMPLETED** | — |

**Nothing is BLOCKED.** Every block ran. Three items inside blocks were *gated* rather than
blocked, and each is recorded as an unmet prerequisite rather than approximated (§4).

---

## 2. The scientific findings

### 2.1 The headline, in one sentence

> **Recent option-trade activity contains real incremental information that neither price
> history nor a full arbitrage-aware option surface can reconstruct — and that information is
> smaller than the cost of estimating the parameters needed to use it, so it produces no
> out-of-sample forecast improvement, no economic value, and cannot be confirmed by any
> prospective test of feasible size.**

This resolves the program's §1 question — which of six explanations accounts for the absent
signal — in favour of **two of them acting together**: explanation 5 (the old aggregation
destroyed the signal, now proven by recovering it) and explanation 6 (what was recovered is
too small to overcome estimation cost, let alone frictions).

### 2.2 Positive findings

**The 60-second point-in-time cutoff is not valid.** Measured over **1,461,521,313 option
trades across 469 sessions**: provider ingestion latency P50 0.073 s, P95 0.979 s, P99 4.76 s,
max 23,995 s. Local receipt latency P95 57.5 s — which is our own 60-second polling cadence,
not a provider delay. End-to-end P95 = **58.53 s**, so a 60-second cutoff leaves 1.5 seconds
of margin. The empirical cutoff is **120 s**. The registered "120 s sensitivity" was always
the correct primary convention.

**Option flow information lives in timing and direction, not in size.** Double machine
learning, cross-fitted over time blocks with a purge, clustered by session:

| Treatment | First sample (D, 383 clusters) | Second sample (V, 80 clusters) |
|---|---|---|
| Premium | t = **+6.10**, p = 2.6 × 10⁻⁹ | t = −0.12, ns |
| Strike concentration | t = **−4.79**, p = 2.3 × 10⁻⁶ | t = +0.29, ns |
| Arrival-intensity innovation | t = **+4.43**, p = 1.3 × 10⁻⁵ | t = +0.64, ns |
| Delta flow | t = **−4.10**, p = 5.1 × 10⁻⁵ | t = −0.67, ns |
| Trades | t = **+2.87**, p = 0.0043 | t = **+2.58**, p = 0.012 |
| Vega / gamma flow | null | null |

Joint Wald 241.71, **p = 3.0 × 10⁻⁴⁶** in the first sample; **Wald 17.59, p = 0.062 in the
second**. Only the trade count carries the same sign at conventional significance in both.

**Both figures are measured against a baseline that can now see the market.** Until this
revision B0 was blind to SPY and QQQ — the columns were in the panel and absent from the feature
registry, so no block after 4 ever used them (decision 75). Acquiring the missing bars and
registering the columns *raised* the discovery statistic from 206.8 to 241.7 and left validation
unchanged, which refutes the natural objection that the flow signal was market beta.

**Both columns are exploratory, and the second is not a replication** (decision 67). V was read
for the specification comparisons, the family choice, the recalibration decision and the
36-target battery, and every one of those readings fed back into what is reported. A sample used
for selection cannot also confirm.

**The previous version of this table claimed two treatments replicated across the samples.
That claim is withdrawn.** It was measured on panels where early-close sessions had been
discarded by a quality gate reading a fabricated grid, where two acquisitions overlapped on 24
session-assets so their origins were double-weighted, and where B1's snapshot window was the
same interval as the flow windows it was being compared against. On the rebuilt panels the
discovery evidence is far stronger and the second sample does not agree.

The intensity measure is a decay-weighted count of recent trades with fixed parameters. It was
previously called a Hawkes intensity, which asserts a fitted self-exciting point process —
there is no estimated excitation, no branching ratio and no stability condition here.

**In-sample evidence and out-of-sample loss disagree systematically, and the gap is the
answer.** The evidence that the population coefficients are non-zero is strong while the
corresponding ΔQLIKE is frequently negative: the information exists, and estimating the
parameters needed to use it costs more than the information is worth.

The Clark–West statistics that carried this section are **withdrawn for every tree family**
(decision 68). Clark–West is derived for a linear model whose restricted form is a parameter
restriction of the unrestricted one; a boosted tree on a larger feature set is a different
function class, so the adjustment had no derivation there and the figures are not restated. It
is now applied only where that precondition holds and refuses to run otherwise.

**B0 is genuinely hard to beat.** It beats persistence, intraday mean, EWMA, simple HAR and
an intraday GARCH(1,1) on QLIKE in **both** universes. Persistence is not merely worse but
badly biased (Mincer-Zarnowitz intercept −2.75 and −3.66, slope 0.77 and 0.68), so any study
baselining on it manufactures headroom.

**Predictability peaks at h = 60, not h = 30.** In both universes, and simultaneously less
noisy: Barndorff-Nielsen–Shephard relative measurement error is 25.7 % at h = 30 versus
19.1 % at h = 60. **About a quarter of RV30 is the estimator's own sampling error**, which no
model can explain.

**The reconstructed surface is textbook.** Put skew −0.190, smile convexity +1.164, 25-delta
risk reversal −0.0070 — every sign as the literature reports, none imposed, from traded NBBO
snapshots alone. The fourth quantity previously listed here as a variance risk premium of
+0.0688 is the gap between implied variance and *trailing* realised variance. A premium is the
gap against the physical expectation of *future* variance, which was never estimated, so the
quantity is now named `implied_minus_trailing_variance` and is not offered as evidence that the
surface reproduces a premium.

### 2.3 Null and negative findings

These are results, recorded as such.

* **Every contrast is null or negative in validation, in every family.** Six model families,
  four contrasts and the interaction. The decision-65 premise correction was tested and did
  not rescue the null: the interaction term ranges −0.009 to +0.003 with no consistent sign.
* **Market controls hurt.** Adding SPY and QQQ trailing variance and return to B0 on
  identical rows worsens QLIKE from 0.12801 to 0.14072.
* **H_B2,J is not supported** (core DML p = 0.164 in D, 0.224 in V). **H_B2,ΔRV is not a
  separate hypothesis at all** — once B0 contains trailing realized variance, the Δ-log-RV
  and log-RV residuals are numerically identical after partialling out.
* **Splitting the target does not help.** The continuous component is no more predictable
  than total RV; semivariances are less predictable; upside ≈ downside.
* **Hierarchical partial pooling adds nothing** (between-asset variance ≈ 1.4 × 10⁻⁴).
* **No economic value at any selectivity.** Deflated Sharpe probability ≤ 0.19 everywhere and
  0.000 when the strategy is made selective. The option-informed arm is *worse* in discovery
  at every trading threshold.
* **Nothing clears the sequential budget.** α₃ = 0.00417; best SPA p = 0.0070 (D) and 0.0250
  (V); White's Reality Check rejects nothing.
* **The 2026 era is intrinsically harder**: identical specification, OOS log-R² falls from
  0.796 to 0.553. The decay is not option-specific — the underlying itself became less
  forecastable from its own history.

### 2.4 Where the discovery effect actually lives

The two discovery contrasts that pass the generalization criterion (positive in 6/6 assets,
no dominating slice, no sign flips) concentrate sharply:

| | open | midday | close | ordinary week | expiry week |
|---|---|---|---|---|---|
| Δ_B2\|B1 (D, LightGBM) | +0.0005 | +0.0010 | **+0.0076** | +0.0019 | **+0.0058** |

Roughly **15× larger near the close** and **3× larger in expiration weeks**, and larger in
*low*-volatility terciles. Giacomini–White confirms state dependence in discovery
(p < 10⁻⁴) and none in validation. This is either a genuine microstructural concentration or
a conditioning artifact; both readings remain open on this evidence.

### 2.5 Defects found and fixed while executing

Recorded because they would have silently corrupted results:

1. **A DST bug** measured session minutes from a fixed 13:30 UTC open, truncating every
   winter session and silently discarding **836 of 2,280 session-assets (37 %)**, mostly the
   2024 discovery era. Now measured from the 09:30 New York open; drops fell to 1.2 %.
2. **An O(origins × window) flow builder** would have needed ~10⁹ Python iterations. Rewritten
   with per-session prefix sums: from "did not finish" to 13 minutes.
3. **A dominance diagnostic** divided by a near-zero signed total, producing values up to
   5 × 10¹³. Replaced with absolute-contribution share plus a leave-one-group-out jackknife.
4. **A false statement in the Supabase campaign register**: a C6-specific sign-convention note
   had been copied onto all five campaigns, where it is false for four of them.
5. **Derived panels (~70 MB) were committed to git** and then removed — they are licensed
   provider derivatives. Only hashed pointers are versioned now.

---

## 3. READY_TO_RUN and why it is not running

**Block 12's prospective protocol is frozen, complete and deliberately not launched.**

Sized against the **measured** session-level dispersion at α = 0.00250 (decision-64 spending
at look 4) and power 0.80:

| family / contrast | observed effect | session σ | sessions required |
|---|---|---|---|
| D LightGBM Δ_B2\|B1 | +0.00322 | 0.02043 | **537** |
| D Gamma Δ_B1 | +0.00118 | 0.01829 | 3,209 |
| V Gamma Δ_B2\|B1 | +0.00027 | 0.00888 | 14,753 |
| all others | ≤ 0 | — | unreachable at any n |

Every minimum detectable effect at n = 60, 90, 120 and 180 **exceeds the largest effect this
program ever measured**. The design under discussion proposed 60–120 sessions. Running it would
return a null whether or not the effect is real, and reporting that as evidence of absence would
be a foregone conclusion dressed as a finding. **That conclusion is the durable one and it does
not depend on the arithmetic below.**

**The session counts in this table are optimistic bounds, not estimates** (decision 69). Each is
the closed-form `n = ((z_α + z_β) σ / δ)²` evaluated at the *observed* effect — and the effect in
the first row was picked as the largest across six families and four contrasts. The maximum of
many noisy estimates is biased upward by construction, so dividing by it understates the sample
required, and understates it more the more candidates were searched. The figures are kept here
because the qualitative verdict (60–120 is not enough) survives any correction that can only
push the requirement up; they are not a design input.

Sizing a campaign now runs `src/mds650/rp2/power.py`: a design frozen before the simulation, the
effect shrunk by `sqrt(2 ln k)` standard errors for selection, the null generated by circular
block resampling of whole observed sessions, and the rejection rate under the null reported
alongside the power so a mis-sized test cannot present a power number.

---

## 4. Gated, not blocked

| Item | Gate that was not met |
|---|---|
| Moneyness × DTE tensor (§6.5) | the program gates it behind "only after demonstrating that the tabular baseline does not capture the signal" — the tabular baseline captures no signal to begin with |
| Level-4 sequence models: DeepSets, TCN, transformer, neural Hawkes (§8) | same gate, plus no deep-learning stack installed |
| Bridge A, delta-hedged options (§11) | needs a full quote book through the holding period; the local tape carries NBBO only at trade instants |
| CatBoost, Explainable Boosting Machine (§8 level 2) | not installed; LightGBM and an additive spline model cover the tree and smooth-additive families |
| Full 50-treatment DML in validation | 50 treatments on 80 clusters makes the CR0 covariance near rank-deficient; its p = 1.5 × 10⁻³⁴ is an artifact and is discarded, not reported as a win |
| VIX proxy, sector ETFs, PIT earnings/macro flags in B0 | not held locally; recorded as gaps rather than approximated |

None of these was approximated into a number that would look like a result.

---

## 5. Decisions requiring your signature

Eight, in descending order of consequence.

**① Primary horizon — RV30 or RV60.**
Block 3 shows predictability peaks at h = 60 in both universes (D 0.823 vs 0.796, V 0.566 vs
0.553) with simultaneously lower measurement noise (19.1 % vs 25.7 %). `docs/target_horizon_decision.md`
fixes RV30 as the sole primary target, and every frozen campaign C1–C6 plus the sealed Phase 8
cohort is built on it. **Keep RV30** (preserving comparability, accepting the deficit) **or add
RV60 as a co-primary in future prospective work only.** An execution run may not overturn an
owner-approved target; RV30 remains frozen until you decide.

**② Whether to run any prospective test at all.**
Three options: (a) **do not run** a 60–120 session test — it is underpowered by construction —
and publish the null with the Block 7 mechanism finding and the Block 10 decomposition as the
contribution; (b) fund a campaign sized by simulation from a frozen design, which the table in
§3 bounds below at roughly two years of forward collection and which a selection-corrected
effect would lengthen; (c) **change the estimand** to closing-period origins in expiration
weeks, where the effect is ~15× larger, pre-registered before any new data is seen — a
different scientific claim.

**③ Phase 8 sealed holdout — complete or close.**
Untouched by this program (`sealed_cohorts_read = 0`). Note the disclosed limitation from
Block 1: its first ten sessions (2026-07-20..07-31) coincide with the already-read C2 window,
so only 2026-08-03..08-28 is strictly unobserved.

**④ Supabase migrations withheld pending signature** — `supabase/migrations_pending/rp2_block14_pending.sql`.
Type casts over 161k rows; primary keys on up to 1.55 M rows; six provenance columns whose
*values* must come from your frozen registry; and the `api`-schema read model that decides
**what becomes public** under the provider licence. Two reversible fixes were already applied
(migration `rp2_block14_evidence_hygiene`): the false campaign note removed, and `p_wild`
labelled `AVAILABLE_IN_ARTIFACT_ONLY` rather than left as an ambiguous NULL.

**⑤ Documentation structure** — adopt Block 16's numbered reading layer, and create
`docs/governance/` + `docs/operations/` by moving only files nothing references. A bulk move
would break `docs/INDEX.md`, `CANONICAL_STATE.json`, `STATUS.md`, the mirror exclude list and
~40 cross-references at once.

**⑥ C3 is missing from the Supabase campaign register.** The reconciliation registers C1–C6;
the table holds five rows and Phase 6 (100 OOS sessions) is absent. Load it or record
deliberately why not.

**⑧ A new prospective cohort for the DIRECTION contrast.** The direction estimand emerged from
a battery of 36 targets searched after the fact, and it is the only one that survived Holm in
both samples. **The 42-session figure once quoted here is withdrawn** (decision 69): it rescaled
the largest |t| of those 36 by `sqrt(n)`, which is the winner's curse expressed as an effect
size. Any cohort for this estimand has to be sized by simulation from a design frozen before the
simulation runs, and the number will be larger — possibly much larger — than 42.

What does not change: a directional cohort is the only confirmatory test within this project's
reach, and **Phase 8 cannot be re-aimed at it** — its protocol is hash-frozen for variance, and
re-aiming would break the seal that gives it value. See `docs/rp2/extensions_1_4_v1.md`.

**⑦ Publication of the null.** Blocks 15–18 leave the repository ready. Nothing has been
pushed to any public mirror during this run.

---

## 5b. Extensions 1-4 (2026-08-19)

Four extensions ran after the cascade closed; `docs/rp2/extensions_1_4_v1.md` has the detail.
Three confirmed the null was not an artefact of the programme's own choices - the moneyness x
DTE tensor does not help (D -0.00169), level-4 DeepSets on the GPU delivers nothing against a
competent tabular model (D -0.0122, V +0.0027), and the mechanism is useless as a regime flag
or an execution-timing ranker.

The fourth found what the programme had never tested: **the signed forward return at 60-120
minutes** is the only target surviving Holm in validation (p = 1.26e-06), driven by strike
concentration and total premium with consistent signs across universes. Power for that
contrast is 94% at 60 sessions against 5.6% for variance - a thirteen-fold difference in
required sample size. It was found by searching 36 targets after the variance nulls were
known, so it is an upper bound, not an unbiased estimate.

Discovery also grew from 236 to 384 sessions (153 acquired bar sessions, 906 requests, zero
empty), taking the panel from 125,136 to 183,744 origins.

## 6. What this program contributes

Not a signal. A negative result with its mechanism identified and its magnitude measured:

1. A **point-in-time measurement** over 1.46 billion rows showing the field-standard
   convention this project used was invalid, with the corrected value and a per-session
   admissibility rule.
2. A demonstration that **option-flow information is real and lives in arrival timing and
   trade direction**, not in exposure-weighted size — recovered only after abandoning
   five-minute aggregation.
3. A clean empirical separation of **population-level predictive content from usable
   predictive value**, via the Clark–West/QLIKE gap, on the same data.
4. A **power analysis that says the confirmatory experiment is infeasible** at the sizes
   under discussion — which is more useful than running it and reporting the null it would
   have produced regardless.
