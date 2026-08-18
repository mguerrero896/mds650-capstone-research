# Gate 1 — Studentized inference over the frozen campaigns (v1)

Compiled 2026-08-17. Re-analysis of already-read frozen forecast artifacts only (no new
data exposure; decision-52 compliant). Code: `src/mds650/inference.py`, runner
`scripts/run_gate1_inference.py`, artifact `artifacts/gate1_inference/results.json`
(sha256 in `results.sha256`; every input parquet's sha256 is recorded inside).

## Why

Every registered contrast was previously summarized by the whole-day sign bootstrap in
`src/mds650/metrics.py`, whose p-value saturates at `2/(N+1) ≈ 0.0002` — all four C6
global contrasts reported exactly `0.00019998`, carrying no information beyond "every
resample had one sign". Gate R-020 and roadmap 3.6 require studentized statistics before
any Gamma-only number is cited. This gate adds: cluster t, Newey-West (Diebold-Mariano)
t with automatic Bartlett lag, wild cluster bootstrap-t (Rademacher and Webb weights),
ACF/Ljung-Box diagnostics, circular moving-block bootstrap CIs, a Hansen-Lunde-Nason
Model Confidence Set per campaign, the first formal test of the Gamma-minus-LightGBM
interaction, and Gelman-Carlin design analysis for the LightGBM challenger.

C3 (Phase 6) is excluded explicitly: its evaluation forecasts were never persisted
(aggregates only in `evidence_root/artifacts/phase6/results.json`).

## Headline table (B2 increment, daily-equal-weight estimates)

Positive favors the expanded set. `p_t` = cluster t; `p_NW` = Newey-West t;
`p_wild` = wild cluster bootstrap-t (Rademacher, 9,999 reps, seed 650); `ρ₁` = lag-1
autocorrelation of the daily differential; `LB` = Ljung-Box p at lag ≤ 5.

| Campaign | Contrast | Model | Estimate | t | p_t | p_NW | p_wild | ρ₁ | LB p |
|---|---|---|---|---|---|---|---|---|---|
| C1 dev | B1a→B2 | Gamma | +0.0131 | +2.46 | 0.019 | 0.040 | 0.017 | +0.20 | 0.43 |
| C1 dev | B1a→B2 | LightGBM | +0.0022 | +1.01 | 0.32 | 0.41 | 0.32 | +0.24 | 0.29 |
| **C2 holdout (prospective)** | B1a→B2 | Gamma | +0.0006 | +0.08 | 0.94 | 0.94 | 0.90 | +0.13 | 0.81 |
| **C2 holdout (prospective)** | B1a→B2 | LightGBM | −0.0005 | −0.59 | 0.57 | 0.58 | 0.58 | −0.07 | 0.68 |
| C4c PIT v2 | B1v2a→B2v2 | Gamma | +0.0347 | +7.71 | 1.7e−08 | 2.2e−08 | 1e−04 | +0.01 | 0.98 |
| C4c PIT v2 | B1v2a→B2v2 | LightGBM | +0.0003 | +1.13 | 0.27 | 0.36 | 0.27 | +0.30 | 0.06 |
| C5-A 2024 (expl.) | B1a→B2 | Gamma | +0.0784 | +4.66 | 6.5e−05 | **0.0048** | 1e−04 | **+0.62** | 0.002 |
| C5-A 2024 (expl.) | B1a→B2 | LightGBM | −0.0245 | −3.16 | 0.0036 | 0.033 | 4e−04 | +0.45 | 0.048 |
| C5-B 2024 (expl.) | B1a→B2 | Gamma | +0.0348 | +5.05 | 2.2e−05 | 0.0011 | 1e−04 | +0.48 | 0.003 |
| C5-B 2024 (expl.) | B1a→B2 | LightGBM | −0.0086 | −3.95 | 4.6e−04 | 4.6e−04 | 3e−04 | +0.15 | 0.20 |
| C6 B1v3 conf. | B1v3a→B2 | Gamma | +0.0532 | +7.07 | 8.9e−08 | **1.0e−04** | 1e−04 | **+0.58** | <0.001 |
| C6 B1v3 conf. | B1v3a→B2 | LightGBM | −0.0075 | −3.35 | 0.0023 | 0.0028 | 5e−04 | +0.11 | 0.89 |

Estimates here weight each day equally (mean of day means); the frozen artifacts pool
origins (ratio of sums), so point estimates differ slightly from the registered ones
(e.g. C6 Gamma B2 +0.0532 vs +0.0534). Both are reported; neither changes sign anywhere.

## The interaction is now a test, not a comparison of two CIs

Per-day series `Δ_t(Gamma, B2−B1) − Δ_t(LightGBM, B2−B1)` on identical origins:

| Campaign | Estimate | t | p_t | p_wild |
|---|---|---|---|---|
| C1 dev | +0.0109 | +2.37 | 0.023 | 0.022 |
| **C2 holdout (prospective)** | **+0.0012** | **+0.15** | **0.89** | **0.88** |
| C4c PIT v2 | +0.0345 | +7.83 | 1.2e−08 | 1e−04 |
| C5-A 2024 | +0.1030 | +4.39 | 1.4e−04 | 1e−04 |
| C5-B 2024 | +0.0434 | +6.71 | 2.3e−07 | 1e−04 |
| C6 B1v3 conf. | +0.0606 | +7.11 | 7.9e−08 | 1e−04 |

Reading: model-family dependence is **retrospectively strong and formally significant in
every retrospective sample, and null in the only prospective sample**. The honest claim
narrows exactly as pre-stated in the backlog: "retrospective family dependence, not
prospectively demonstrated".

## Model Confidence Set (α = 0.10, model × information-set cells)

| Campaign | Survivors |
|---|---|
| C1 dev | LightGBM\|B1a, LightGBM\|B2 |
| C2 holdout | LightGBM\|B0 |
| C4c PIT v2 | LightGBM\|B1v2a, LightGBM\|B2v2 |
| C5-A 2024 | LightGBM\|B1a |
| C5-B 2024 | har_rv\|B2 (log-linear ext.†), LightGBM\|B1a, LightGBM\|B2, Ridge\|B2 |
| C6 B1v3 conf. | LightGBM\|B0 |

† Naming caution (see `docs/model_naming_note_v1.md`): the cell registered as `har_rv`
in the frozen C5 artifacts is a *log-linear fixed extension* (LinearRegression on the
log target over the frozen information-set columns), **not** the dedicated intraday
HAR/HARQ of `src/mds650/har.py` (Gate 3). No canonical MCS contains the Gate-3 HAR.

**The Gamma family never enters any Model Confidence Set.** On the binding C6 sample the
single best cell is LightGBM with *no option information at all*. The Gamma-specific B2
increment is an improvement *within* a model family that is itself always dominated —
this is the sharpest statement yet of why the increment cannot be read as a global edge,
and it makes Gate 2 (calibration-repair vs information) the decisive next question.

## Serial dependence and the legacy bootstrap

The iid-day assumption of `paired_day_bootstrap` is violated exactly where the headline
lives: C6 Gamma B2 has ρ₁ = +0.58 (Ljung-Box p < 0.001); C5-A Gamma B2 ρ₁ = +0.62. The
Newey-West p-values are up to three orders of magnitude larger than the naive cluster-t
(C6: 8.9e−08 → 1.0e−04) yet every retrospectively significant Gamma B2 contrast
**survives** HAC correction and the wild bootstrap; moving-block bootstrap CIs are in the
artifact for every contrast. The correction changes precision claims, not signs.

## Gelman-Carlin design analysis (LightGBM challenger)

At the Gamma effect size, the LightGBM contrast is fully powered on every 30-session
sample (power ≈ 1.0), so its significantly negative estimates (C6 p_t = 0.0023) are a
genuine reversal, not an underpowered null. The underpowered regime is the C2 holdout
(n = 10): power 0.11, exaggeration ratio 3.5 — the pre-registered caution that any
significant estimate there would be inflated stands.

## Bindings

- Legacy sign-bootstrap results are reproduced beside every new statistic in the
  artifact (`legacy_sign_bootstrap_daily_equal_weight`).
- Seeds and repetitions are frozen (seed 650, 9,999 reps) and recorded per entry.
- Nothing here amends any registered verdict; decision 48/53 wording stands. These are
  the statistics the write-up must cite next to any Gamma-only number (R-020).

## Addendum (2026-08-18): block-bootstrap MCS sensitivity

Reviewer correction accepted: the original MCS resampled days IID, which ignores the
serial dependence measured on these same series. `model_confidence_set` now supports a
circular moving-block bootstrap (whole days drawn jointly across all model columns),
and `artifacts/mcs_block_sensitivity/` reruns every campaign at
L ∈ {IID, ⌈T^⅓⌉, 5, 10, 20}. Result: the survivor sets of **C6, C4c and both C5
blocks are invariant to block length** — "the Gamma family never enters any MCS"
holds under serial-dependence-preserving resampling everywhere the headline relies on
it. The two honest nuances: on development data (C1) the block MCS is more
conservative and `gamma|B2` enters the set at L ≥ 5; and at T = 10 (C2) L = 10 is
degenerate and non-informative. The IID variant remains available as the legacy
baseline (`block_length=None`, reported as L=0).
