# Block 7 — the decisive experiment: DML orthogonalisation of B2

**Status:** `EXECUTED — 2026-08-19` · label `EXPLORATORY_MECHANISM_DISCOVERY`
**Artifact:** `artifacts/rp2_block7_dml/dml.json`
(`dml_sha256 = 68f1c6d77c56b726173874babf6baeec4d3792fe86364978d4621042b138d461`)
**Code:** `src/mds650/rp2/dml.py`, `scripts/rp2_block7_dml.py`
**Tests:** `tests/unit/test_rp2_dml.py` (8 tests)

---

## 1. The question this block answers, and the one it does not

> *"The correct question is not whether a model with B2 happens to have lower loss, but
> whether B2 contains information that cannot be reconstructed from B0+B1."*

Partialling-out double machine learning:

```
m(X) = E[Y | B0, B1]      g(X) = E[B2 | B0, B1]
Ỹ = Y − m̂⁽⁻ᵏ⁾(X)          B̃2 = B2 − ĝ⁽⁻ᵏ⁾(X)          Ỹ = θᵀ B̃2 + ε
```

Nuisance functions are cross-fitted over **five contiguous time blocks with a one-session
purge** — never random folds — and inference is clustered by session, because five-minute
origins share overlapping thirty-minute targets and treating them as independent would shrink
every standard error by roughly √66.

**What a rejection of `H₀: θ = 0` means:** there is a population-level linear relationship
between residualised B2 and the residualised outcome. **What it does not mean:** that a model
using B2 forecasts better out of sample. Block 8 answers that separately, and the two answers
differ — which is the main scientific content of this program.

| Universe | Origins | Sessions | Nuisance features | Folds |
|---|---|---|---|---|
| D | 89,889 | 230 | 38 | 5 |
| V | 31,131 | 80 | 38 | 5 |

## 2. Primary result — the core block replicates

Ten economically distinct treatments from the 5-minute window. Joint cluster-robust Wald:

| Outcome | D (230 clusters) | V (80 clusters) |
|---|---|---|
| `log RV30` | Wald 76.06, **p = 3.0 × 10⁻¹²** | Wald 17.75, p = 0.059 |
| `log jump30` (H_B2,J) | Wald 14.20, p = 0.164 | Wald 13.00, p = 0.224 |
| `Δ log RV30` (H_B2,ΔRV) | Wald 76.06, p = 3.0 × 10⁻¹² | Wald 17.75, p = 0.059 |

> **Structural identity, not a duplicate row.** `Δ log RV30 = log RV30 − log RV_back30`, and
> `log RV_back30` is inside the B0 nuisance set. After partialling out B0+B1 the two
> residuals are numerically identical, so the two tests must coincide. This is a correctness
> check on the implementation, and it means **H_B2,ΔRV is not a separate hypothesis** once
> the baseline already contains the trailing realized variance.

### Which features carry it

| Treatment | D: θ (t, p) | V: θ (t, p) |
|---|---|---|
| **`b2_5m_hawkes_innovation`** | +0.00185 (t = **+4.39**, p = 1.8 × 10⁻⁵) | +0.00137 (t = **+2.30**, p = 0.024) |
| **`b2_5m_buy_premium_share`** | +0.0528 (t = +2.03, p = 0.044) | +0.0946 (t = **+2.04**, p = 0.045) |
| `b2_5m_premium` | +0.0379 (t = +3.59, p = 4.1 × 10⁻⁴) | +0.0104 (t = +0.55, ns) |
| `b2_5m_delta_flow` | −0.00040 (t = −3.05, p = 0.003) | +0.00008 (t = +0.39, ns) |
| `b2_5m_strike_hhi` | −0.1158 (t = −2.42, p = 0.017) | +0.0339 (t = +0.49, ns) |
| `b2_5m_trades` | +0.0376 (t = +2.14, p = 0.034) | +0.0443 (t = +1.40, ns) |
| `b2_5m_vega_flow` | +0.00015 (t = +0.87, ns) | −0.00038 (t = −1.36, ns) |
| `b2_5m_gamma_flow` | +0.00003 (t = +0.28, ns) | +0.00014 (t = +0.82, ns) |
| `b2_5m_d_iv` | +1.829 (t = +0.60, ns) | −0.918 (t = −0.27, ns) |
| `b2_5m_otm_premium_share` | −0.0037 (t = −0.17, ns) | −0.0025 (t = −0.07, ns) |

**Two treatments and only two survive in both universes with the same sign: the Hawkes
burst-intensity innovation and the buyer-initiated premium share.**

## 3. The finding, stated plainly

**It is the *timing* and the *direction* of option flow that carry incremental information,
not its Greeks-weighted size.**

Vega, gamma and delta flow — the exposure-weighted quantities the program's §6.1 proposed as
the primary redesign, and the ones a practitioner would name first — are null in both
universes. What survives is:

* `hawkes_innovation` — how far the current arrival intensity exceeds its own recent
  conditional expectation, i.e. an unexpected *burst*; and
* `buy_premium_share` — the fraction of premium that was buyer-initiated.

That has a coherent reading. A sudden, unexpected cluster of buyer-initiated option trades is
informative about the next thirty minutes of realized variance in a way that the same dollar
value of vega, arriving smoothly, is not. It also explains why the incumbent B2 found nothing:
five-minute counts of trades and premium cannot represent an intensity innovation at all, and
did not carry a side split.

This is the program's §1 explanation **5** — *"the current aggregation destroys the signal"* —
confirmed on its own terms. But see Block 8: the recovered signal is real and too small to
matter, which is §1 explanation **6**.

## 4. The full-block test is reported and then set aside

| Universe | Treatments | Clusters | Wald | p |
|---|---|---|---|---|
| D | 50 | 230 | 211.47 | 9.5 × 10⁻²² |
| V | 50 | **80** | 284.55 | 1.5 × 10⁻³⁴ |

**The V row is not trustworthy and is not used.** With 50 treatments and 80 clusters, the CR0
cluster-robust covariance is built from 80 outer products of a 50-vector; it is close to rank
deficient, and its pseudo-inverse inflates the Wald statistic. A p-value of 10⁻³⁴ on 80
trading days is a symptom of that, not evidence. The rule applied here is that the treatment
count must stay well below the cluster count, which the ten-treatment core test satisfies
(10 ≪ 80) and the full block does not.

The D full-block row (50 treatments, 230 clusters) is better conditioned but still ranks near
the boundary; it is reported as supporting, never as primary. Its jump result (p = 0.003)
is the only support `H_B2,J` receives anywhere, and it does not survive the core test
(p = 0.164), so **`H_B2,J` is recorded as not supported**.

## 5. Advance rule

**"Preliminary incremental evidence": PASS.** `H₀: θ = 0` is rejected for the core B2 block
in discovery at p = 3 × 10⁻¹², and the two driving treatments replicate in validation at the
5 % level with the same sign. B2 contains structure that B0 and a full arbitrage-aware B1
surface cannot reconstruct.

Whether that structure is worth anything is Block 8's question, and the answer there is no.
