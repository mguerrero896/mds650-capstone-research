# Block 11 — a QLIKE improvement is not yet economic alpha

**Status:** `EXECUTED — 2026-08-19` · label `EXPLORATORY_MECHANISM_DISCOVERY`
**Artifacts:** `artifacts/rp2_block11_economics/economics.json`
(`economics_sha256 = 8f67eab020dc27c1ae4f9b8523c2fee3977724e42dbac0b67d9d18dfa8c5b10a`),
`buffer_sweep.json` (`sweep_sha256 = 2bc3c6f5433ab2d6b2b5619b555e51e775b113049cd92223c40601b2ff6fb48d`)
**Code:** `src/mds650/rp2/economics.py`, `scripts/rp2_block11_economics.py`
**Tests:** `tests/unit/test_rp2_economics.py` (8 tests)

---

## 1. Bridge A is not implemented, deliberately

A delta-hedged option strategy needs a per-contract execution simulator with the full quote
book **through the holding period**. The local tape carries NBBO only at trade instants. A
P&L built by interpolating between them would look like a result and would not be one, so it
is left unimplemented and named as a gap.

## 2. Bridge B — the honest reading of a very large Sharpe

Evaluation is on **non-overlapping origins only** (30-minute spacing, 6,012 rows in D and
2,080 in V); overlapping payoffs would count the same variance six times and inflate every
Sharpe by roughly √6. Transaction cost is measured, not assumed: half the round-trip option
relative spread at the origin, converted to annualised variance units (median ≈ 0.0009 in
variance units against an implied-minus-trailing variance spread of ≈ 0.069). That spread is
**not** a variance risk premium: a premium is measured against the physical expectation of
*future* variance, and substituting the trailing realisation makes the quantity a property of
the recent past. The signal is named `implied_minus_trailing_variance` throughout.

At the natural threshold (buffer 0) the strategy trades in **100 % of periods**.

> **That means it is not a forecast-driven strategy at all.** The implied-minus-trailing
> spread is almost always positive, so "short variance whenever `IV² − Ê[RV]` exceeds costs"
> degenerates
> into a static short-variance carry position. Its headline Sharpe (+67 annualised) is the
> product of unconditional carry, iid annualisation of an extremely fat-tailed payoff, and a
> cost model that is too small for a real variance replication. **It is not read as a
> result.**

What *is* valid is the like-for-like comparison: both arms use the identical cost model, trade
the same periods, and differ only in the information set behind the forecast.

### Buffer sweep — forcing the strategy to be selective

| buffer | traded share | D log-OLS B0 → B0+B1+B2 | V LightGBM B0 → B0+B1+B2 |
|---|---|---|---|
| 0.00 | 1.00 | +67.66 → **+67.55** | +55.36 → **+55.01** |
| 0.05 | 0.65 – 0.76 | +55.08 → **+54.52** | +52.88 → +55.11 |
| 0.15 | 0.15 – 0.22 | +22.62 → **+21.94** | +27.12 → +28.26 |

Adding option information makes the strategy **worse in discovery at every buffer** and
mixed in validation. There is no buffer at which the option-informed forecast produces a
consistent economic gain.

### Deflated Sharpe — the decisive statistic

| buffer | D log-OLS B0+B1+B2 | V LightGBM B0+B1+B2 |
|---|---|---|
| 0.00 | 0.007 | 0.000 |
| 0.05 | 0.002 | 0.189 |
| 0.15 | 0.000 | 0.000 |

The Bailey–López de Prado deflated Sharpe probability — the probability the Sharpe is not the
maximum one would expect from the number of configurations tried, given the payoff's skew and
kurtosis — is **at most 0.19 anywhere, and 0.000 at the selective buffer**. Every strategy in
this block, with or without option information, is statistically indistinguishable from luck
once its own selection and its fat tails are accounted for.

## 3. Bridge C — risk-management utility

Volatility targeting, VaR breach rate at 5 %, and mean-variance certainty equivalent, using
each forecast to size positions:

| Universe | model | vol-target tracking error | VaR breach rate (target 0.05) |
|---|---|---|---|
| D | log-OLS B0 | 0.914 | 0.047 |
| D | log-OLS **B0+B1+B2** | **0.776** | **0.044** |
| D | Gamma B0 → B0+B1+B2 | 0.880 → **0.740** | 0.047 → 0.045 |
| D | LightGBM B0 → B0+B1+B2 | 0.981 → 0.934 | 0.051 → 0.052 |
| V | log-OLS B0 → B0+B1+B2 | 1.523 → **1.590** | 0.069 → 0.064 |
| V | Gamma B0 → B0+B1+B2 | 1.441 → **1.474** | 0.070 → 0.062 |
| V | LightGBM B0 → B0+B1+B2 | 1.683 → 1.640 | 0.076 → 0.081 |

**The one place option information consistently helps is volatility targeting in discovery**:
tracking error falls 15 % (log-OLS 0.914 → 0.776) and 16 % (Gamma 0.880 → 0.740). In
validation it degrades for two of three models. VaR breach rates improve slightly with option
information in five of six comparisons, but the validation-era breach rates (0.062 – 0.081
against a 0.05 nominal) are poorly calibrated for **both** information sets, so this is not a
claim that options fix VaR.

## 4. Economic success criterion

The program's criterion is `E[P&L_net] > 0` with an interval compatible with positive
profitability, plus stability by asset and period.

**Not met, and not close.** No configuration produces a deflated Sharpe probability above
0.19; the option-informed arm is worse than the underlying-only arm in discovery at every
buffer; and no interval is reported as compatible with positive profitability because the
underlying strategy is unconditional carry rather than a forecast product.

**Advance rule "positive net value": FAIL.** The single economically interesting residue is
the discovery-era volatility-targeting improvement (≈ 15 % lower tracking error), which is
risk-management utility rather than P&L, does not replicate in validation, and is reported as
exploratory.
