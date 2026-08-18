# Block 10 — the inference that was still missing

**Status:** `EXECUTED — 2026-08-19` · label `EXPLORATORY_MECHANISM_DISCOVERY`
**Artifact:** `artifacts/rp2_block10_inference/inference.json`
(`inference_sha256 = 9a38a99fe63ddff127b3031cd393dcb9d9131fe7f542069cc9d2e3f983961623`)
**Code:** `src/mds650/rp2/inference.py`, `scripts/rp2_block10_inference.py`
**Tests:** `tests/unit/test_rp2_inference.py` (11 tests)

---

## 1. Clark–West and QLIKE disagree, and the disagreement is the finding

Clark–West adjusts the nested comparison for the estimation noise the larger model carries
under the null: `f_t = e₀ₜ² − [e₁ₜ² − (ŷ₀ₜ − ŷ₁ₜ)²]`. It is computed on the log scale, where
the nested models are actually linear in their extra parameters, and tested with a
session-clustered mean.

### Discovery (92 evaluation clusters)

| Model | contrast | CW t | CW p (1-sided) | GW p | ΔQLIKE |
|---|---|---|---|---|---|
| log-OLS | B1 over B0 | +3.85 | 0.0001 | <10⁻⁴ | **+0.00303** |
| log-OLS | B2 over B1 | −1.15 | 0.874 | <10⁻⁴ | −0.00027 |
| log-OLS | B2 over B0 | **+6.95** | <10⁻⁴ | <10⁻⁴ | **−0.00096** |
| log-OLS | total over B0 | +3.07 | 0.0014 | 0.0063 | +0.00275 |
| Gamma GLM | B2 over B0 | +6.87 | <10⁻⁴ | 0.0022 | −0.00115 |
| LightGBM | B1 over B0 | +4.57 | <10⁻⁴ | 0.023 | −0.00176 |
| LightGBM | B2 over B1 | **+5.21** | <10⁻⁴ | 0.306 | +0.00323 |
| LightGBM | B2 over B0 | +7.30 | <10⁻⁴ | 0.041 | −0.00008 |

### Validation (32 evaluation clusters)

| Model | contrast | CW t | CW p | GW p | ΔQLIKE |
|---|---|---|---|---|---|
| log-OLS | B1 over B0 | +3.39 | 0.0010 | 0.420 | **−0.00161** |
| log-OLS | B2 over B0 | +3.72 | 0.0004 | 0.0068 | +0.00003 |
| Gamma GLM | B1 over B0 | +0.28 | 0.392 | 0.241 | −0.00228 |
| LightGBM | B1 over B0 | **+5.39** | <10⁻⁴ | 0.080 | **−0.00180** |
| LightGBM | B2 over B1 | **+4.21** | 0.0001 | 0.245 | **−0.00506** |
| LightGBM | total over B0 | +5.26 | <10⁻⁴ | 0.511 | **−0.00685** |

**Clark–West is significant almost everywhere; the corresponding ΔQLIKE is frequently
negative.** `log-OLS B2 over B0` in D: CW t = +6.95 with ΔQLIKE = −0.00096. `LightGBM total
over B0` in V: CW t = +5.26 with ΔQLIKE = −0.00685.

This is not a contradiction, it is the definition of the two statistics. Clark–West asks
whether the *population* coefficients on the extra regressors are non-zero. QLIKE asks
whether the *estimated* larger model forecasts better. The gap between them is the cost of
estimating those coefficients. The measured answer here is unambiguous:

> **There is population-level predictive content in the option information sets, and it is
> smaller than the cost of estimating the parameters needed to use it.**

That is the same conclusion Blocks 7 and 8 reach from different directions, and it is the
sharpest statement this project can make about why a real mechanism produces no usable
forecast improvement.

## 2. Giacomini–White: the advantage is state dependent in discovery

Conditioning on ex-ante observables (trailing 30-minute realized variance, minute of session,
trailing dollar volume), `E[dₜ | Zₜ] = 0` is rejected at p < 10⁻⁴ for most discovery
contrasts and is generally not rejected in validation.

So in discovery the loss differential *does* depend on observable state — consistent with
Block 9's finding that the effect concentrates near the close and in expiration weeks. In
validation the conditional structure is gone too, not merely the unconditional mean.

## 3. Superior Predictive Ability — nothing clears the alpha budget

Every model × information-set combination against the plain `log_ols|B0` benchmark,
stationary bootstrap (mean block 5, 1,000 replications):

| Universe | best candidate | mean ΔQLIKE | Hansen SPA p | White Reality Check p |
|---|---|---|---|---|
| D | `lightgbm\|B0+B1+B2` | +0.00306 | **0.0070** | 0.140 |
| V | `gamma_glm\|B0+B2` | +0.00317 | **0.0250** | 0.494 |

Two caveats, both material:

1. **The SPA family mixes model changes with information changes.** The best D candidate beats
   the benchmark partly because LightGBM beats log-OLS, not only because B1+B2 beats B0.
   The information-only comparison is Block 8's contrast table, which is null.
2. **Neither p-value clears the project's own sequential budget.** Decision 64 sets
   `α_k = 0.05 / (k(k+1))`; this program is look k = 3, so **α₃ = 0.00417**. SPA p = 0.0070
   (D) and 0.0250 (V) both exceed it. White's Reality Check, which does not recentre away
   poor candidates, rejects nothing at any conventional level.

## 4. E-values and alpha spending

The sequential machinery required by §10 already exists in the project
(`src/mds650/sequential.py`, decision 64) and is not re-implemented here. What this block adds
is the arithmetic that binds it: at look 3 the budget is 0.00417, and **no test in this
program produces a p-value below it in the validation universe** — the largest claim available
is the discovery-only SPA at 0.0070, which fails the budget by a factor of 1.7.

## 5. Advance rule

**"Survives multiplicity": FAIL, and that is the result.** Clark–West detects population
content; Giacomini–White shows what content there is is state dependent in discovery only;
SPA's best candidate does not clear the pre-registered alpha budget in either universe; and
the Reality Check rejects nothing. Nothing in this program is eligible to be called a
confirmed predictive improvement.
