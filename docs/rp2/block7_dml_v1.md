# Block 7 — the decisive experiment: DML orthogonalisation of B2

**Status:** `EXECUTED — 2026-08-19` · label `EXPLORATORY_MECHANISM_DISCOVERY`
**Artifact:** `artifacts/rp2_block7_dml/dml.json`
(`dml_sha256 = 01775dcb89b76979b5e0024126ac4bcaff1eef69cbe6b270a95df3364db8272a`)
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

## 2. Primary result — significant in discovery, absent in validation

Ten economically distinct treatments from the 5-minute window. Joint cluster-robust Wald:

| Outcome | D (383 clusters) | V (80 clusters) |
|---|---|---|
| `log RV30` | Wald 241.71, **p = 2.99e-46** | Wald 17.59, p = 0.0623 |
| `log jump30` (H_B2,J) | Wald 14.10, p = 0.169 | Wald 19.92, p = 0.03 |
| `Δ log RV30` (H_B2,ΔRV) | Wald 241.71, p = 2.99e-46 | Wald 17.59, p = 0.0623 |

> **Structural identity, not a duplicate row.** `Δ log RV30 = log RV30 − log RV_back30`, and
> `log RV_back30` is inside the B0 nuisance set. After partialling out B0+B1 the two
> residuals are numerically identical, so the two tests must coincide. This is a correctness
> check on the implementation, and it means **H_B2,ΔRV is not a separate hypothesis** once
> the baseline already contains the trailing realized variance.

### Which features carry it

| Treatment | D: θ (t, p) | V: θ (t, p) |
|---|---|---|
| `b2_5m_premium` | +0.053763 (t = +6.10, p = 2.64e-09) | -0.012157 (t = -0.65, ns) |
| `b2_5m_strike_hhi` | -0.18605 (t = -4.81, p = 2.14e-06) | +0.084708 (t = +0.91, ns) |
| `b2_5m_decay_intensity_innovation` | +0.0017087 (t = +4.35, p = 1.78e-05) | +0.00023915 (t = +0.29, ns) |
| `b2_5m_delta_flow` | -0.00064111 (t = -4.03, p = 6.85e-05) | -0.00026684 (t = -0.98, ns) |
| `b2_5m_otm_premium_share` | +0.036015 (t = +1.68, ns) | +0.036227 (t = +0.77, ns) |
| `b2_5m_trades` | +0.056656 (t = +5.32, p = 1.81e-07) | +0.092638 (t = +3.13, p = 0.00244) |
| `b2_5m_buy_premium_share` | +0.063958 (t = +2.74, p = 0.00653) | +0.00083511 (t = +0.01, ns) |
| `b2_5m_vega_flow` | -0.0001246 (t = -0.80, ns) | +1.0422e-05 (t = +0.03, ns) |
| `b2_5m_gamma_flow` | +8.1485e-05 (t = +0.81, ns) | +8.4811e-06 (t = +0.04, ns) |
| `b2_5m_d_iv` | -4.0094 (t = -1.50, ns) | +0.1084 (t = +0.03, ns) |

**On the rebuilt panels the joint test is overwhelming in discovery and does not reach
significance in validation** (p = 0.0623 against a 0.05 threshold). Only `b2_5m_trades`
carries the same sign at conventional significance in both.

This is a change from what this document previously reported, and it is a consequence of the
data corrections rather than of a different estimator: early-close sessions had been discarded
by a quality gate reading a fabricated 390-minute grid, two acquisitions overlapped on 24
session-assets so their origins were double-weighted, B1 is now built against a measured
forward and an exact tenor, and B1's snapshot window no longer overlaps the flow windows it is
being compared against.

The treatment named `b2_5m_hawkes_innovation` in the previous table is the same measure under
its honest name, `b2_5m_decay_intensity_innovation`: its baseline, excitation and decay were
fixed inputs, nothing was estimated, and there is no branching ratio behind it (decision 68's
companion rename).

**Read the discovery column against decision 75.** Validation's B0 carries no market-wide
state — SPY and QQQ bars exist for discovery sessions only — so its baseline is *weaker*, and a
weaker baseline should make a B2 increment easier to find, not harder. It is absent anyway.

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
| D | 58 | 383 | 501.87 | 5.9 × 10⁻⁷² |
| V | 58 | **80** | 548.92 | 4.4 × 10⁻⁸¹ |

**The V row is not trustworthy and is not used.** With 58 treatments and 80 clusters, the CR0
cluster-robust covariance is built from 80 outer products of a 58-vector; it is close to rank
deficient, and its pseudo-inverse inflates the Wald statistic. A p-value of 10⁻⁸¹ on 80
trading days is a symptom of that, not evidence — and it is the clearest possible illustration
of why: the same universe returns p = 0.059 on the ten-treatment core test, where the
covariance is well conditioned. The rule applied here is that the treatment count must stay
well below the cluster count, which the core test satisfies (10 ≪ 80) and the full block does
not.

The D full-block row (58 treatments, 383 clusters) is better conditioned; it is reported as
supporting, never as primary. Its jump result (p = 0.031) is the only support `H_B2,J`
receives anywhere, and it does not survive the core test (p = 0.224), so **`H_B2,J` is
recorded as not supported**.

## 5. Advance rule

**"Preliminary incremental evidence": PASS in discovery only.** `H₀: θ = 0` is rejected for
the core B2 block in discovery at p = 6 × 10⁻³⁹ — B2 contains structure that B0 and a full
arbitrage-aware B1 surface cannot reconstruct in that sample.

**It does not carry to the second sample** (p = 0.059, and only `b2_5m_trades` keeps its sign
at conventional significance). Neither sample is confirmatory (decision 67), so this is one
exploratory result that does not reproduce in a second exploratory sample — which is weaker
than the previous version of this document claimed, and the claim of replication is withdrawn.

Whether the discovery structure is worth anything is Block 8's question, and the answer there
is still no.
