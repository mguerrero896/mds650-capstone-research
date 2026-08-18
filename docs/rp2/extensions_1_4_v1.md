# Extensions 1–4 — what was tried after the cascade closed

**Status:** `EXECUTED — 2026-08-19` · label `EXPLORATORY_MECHANISM_DISCOVERY`
**Artifacts:** `artifacts/rp2_ext1_mechanism_utility/`, `artifacts/rp2_ext12_level4/`,
`artifacts/rp2_ext4_power/`, `D:/MDS650/data/fmp/rp2_ext3/acquisition.json`

The eighteen blocks closed with a null. Four extensions asked whether that null was a
property of the market or of the choices the programme had made. Three said "the choices
were fine, the null stands". One found something the programme had never tested.

---

## Extension 1 — is the mechanism useful for a job other than RV30 level?

Block 7 found that option-flow timing and direction carry information; Block 8 found it does
not improve a level forecast. Three different jobs were measured, each one something a level
forecast is the wrong instrument for.

| Job | Measurement | Result |
|---|---|---|
| Regime / attention flag | AUC for "next window in the variance tail" | **NEGATIVE** — D 0.8875 → 0.8875, V 0.8659 → **0.8627** (worse) |
| Execution timing | Spearman rank correlation, decile spread | **NEGATIVE** — D 0.8533 → 0.8535, V 0.7877 → 0.7870 |
| Other targets | DML over 36 alternative targets, Holm within family | **POSITIVE** — see below |

### The one thing that replicates

In validation **only 3 of 36 tests survive Holm**, and two are the signed forward return:

| Universe | Target | p | Holm |
|---|---|---|---|
| V | signed return, 120 min | 1.26 × 10⁻⁶ | **0.0000** |
| V | signed return, 60 min | 1.67 × 10⁻⁴ | **0.0059** |
| D | signed return, 120 min | 3.91 × 10⁻³ | 0.0391 |
| D | signed return, 60 min | 1.30 × 10⁻³ | 0.0155 |

The same two features drive it in both universes **with the same signs**: strike
concentration positive (V t = +5.06 / +4.90) and total premium negative (V t = −3.70 /
−3.75). Premium concentrated on few strikes precedes a positive underlying return at 60–120
minutes; large diffuse premium precedes a negative one.

**Three caveats travel with this and are not optional.** The target family was chosen after
the variance nulls were known, so this is specification search. DML significance is
population-level structure, not out-of-sample value — the exact trap Block 10 documented. And
a directional claim deserves a *higher* bar than a variance one, not a lower one.

## Extension 2 — the moneyness × DTE tensor

The representation §6.5 proposed as the fix for premature aggregation, through the same
LightGBM the ladder used, so the comparison is like-for-like.

| Universe | tabular | + tensor | Δ | p |
|---|---|---|---|---|
| D | 0.13742 | 0.13912 | **−0.00169** | 0.057 |
| V | 0.21331 | 0.21168 | +0.00163 | 0.477 |

**It does not help.** Worse in discovery, not significant in validation.

## Extension 1b — level-4 sequence models

DeepSets over the last 48 trades before each cutoff, on the RTX 5090. The control is the
identical network with the sequence branch removed, same seed, same schedule, same data.

The headline contrast (+0.63 in D, +0.32 in V, both significant) **is not reported as a
finding**, because the control is weak:

| | log-RMSE D | log-RMSE V | QLIKE D | QLIKE V |
|---|---|---|---|---|
| MLP tabular | 0.5364 | 0.7446 | 0.7834 | 0.5344 |
| DeepSets | **0.4901** | **0.5239** | 0.1496 | 0.2107 |
| LightGBM (reference) | — | — | **0.13742** | **0.21331** |

The MLP is not broken; it is simply worse, and QLIKE amplifies that because it punishes
under-forecast small variances brutally — a 9–30 % log-RMSE gap becomes a 4× QLIKE gap.
Against a properly fit model:

* D: DeepSets 0.1496 vs LightGBM 0.1374 → **−0.0122, worse**
* V: DeepSets 0.2107 vs LightGBM 0.2133 → **+0.0027, better**

**Correction to an earlier reading.** Before recalibration the V advantage looked like
+0.0207. After recalibrating both arms it collapses to +0.0027 — that apparent improvement
was a calibration accident, not information.

**Verdict:** the trade sequence consistently improves the network's own objective and
delivers essentially nothing against a competent tabular model.

## Extension 3 — the 153 sessions that had no bars

The local tape covers 469 sessions; only 316 entered the panel because the rest had no
underlying bars. **906 FMP requests, 153/153 sessions acquired, zero empty**
(`b1150c4d4814…`). Discovery grows from 236 to **384 sessions** and the panel from 125,136
to **183,744 origins**.

These are already-observed eras, so they cannot serve as confirmation. What they buy is
precision on the mechanism estimate.

## Extension 4 — power for both contrasts

Block 12 sized only the variance contrast. With the direction result in hand, both had to be
compared before any one-read cohort is spent. One-sided, α = 0.00250 (decision-64 spending at
look 4), power target 0.80:

| Contrast | detail | n=30 | n=60 | n=120 | **sessions for 80 %** |
|---|---|---|---|---|---|
| **direction** | V, signed return 120 min | 61.4 % | **94.2 %** | 100 % | **42** |
| direction | V, signed return 60 min | 57.7 % | 92.5 % | 99.9 % | 44 |
| direction | D, signed return 120 min | 5.7 % | 14.1 % | 35.9 % | 267 |
| variance | D, LightGBM Δ_B2\|B1 | 2.6 % | 5.6 % | 13.9 % | **537** |
| variance | D, Gamma Δ_B1 | 0.7 % | 1.0 % | 1.8 % | 3,209 |
| variance | V, Gamma Δ_B2\|B1 | 0.4 % | 0.5 % | 0.7 % | 14,753 |
| variance | every other family | 0.0 % | 0.0 % | 0.0 % | unreachable |

**A thirteen-fold difference in required sample size.** The direction contrast is testable
with a feasible cohort; the variance one is not, in any family.

The direction figures are an **upper bound**: the target was found by searching 36 candidates
after the variance nulls were known, so a pre-registered test would face a smaller effect.
Halving it still leaves ≈ 170 sessions — far better than 537, but not 42.

---

## Why the sealed Phase 8 cohort was not read

Phase 8's protocol is hash-frozen for the **variance** contrast. Reading it tests variance at
n = 30, which Extension 4 puts at **2.6 % power**. Re-aiming it at the direction hypothesis
would break the seal, and the seal is the only thing that makes it worth anything.

The cohort that would answer the live question is a **new** prospective collection of roughly
60 sessions, pre-registered for the directional estimand before any of it is seen. That is a
decision requiring the owner's signature, and it is the eighth item on the list in
`docs/rp2/FINAL_REPORT.md`.
