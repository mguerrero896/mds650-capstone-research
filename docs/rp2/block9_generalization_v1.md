# Block 9 — generalization validation

**Status:** `EXECUTED — 2026-08-19` · label `EXPLORATORY_MECHANISM_DISCOVERY`
**Artifact:** `artifacts/rp2_block9_generalization/generalization.json`
(`generalization_sha256 = 7cc50e688cbf592671afab6c180d540b7676b91a29a561b44e0fd83ddb38c4b5`)
**Code:** `scripts/rp2_block9_generalization.py`

---

## 1. What is sliced, and how

Leave-one-asset-out **refits** (train on five equities, evaluate on the sixth) because that
is the only slice that genuinely asks whether the mechanism transfers across the
cross-section. Month, era, regime and event slices are evaluation-side jackknives on the same
frozen forecasts — which is what "does one month explain the result" actually means.

Slices: asset, month, era (source window), volatility tercile, liquidity tercile, session
period (open / midday / close), market direction, expiration week, and a non-overlapping
origin subsample at 30-minute spacing.

### Two defects in this block's own diagnostics, found and fixed

1. The dominance metric was `sum(slice) / sum(total)`. The totals here are near zero, so the
   ratio produced values up to 5 × 10¹³ — arithmetically correct, informationally worthless.
   It is now the share of **absolute** contribution, bounded in [0, 1], plus an explicit
   leave-one-group-out jackknife and a count of groups whose removal flips the overall sign.
2. Single-group slices emitted `NaN`, which is not JSON-compliant and broke artifact hashing.
   They now emit `null`.

## 2. The two contrasts that pass the minimum criterion — in discovery only

The program's criterion is deliberately not "every subgroup positive". It is: no systematic
inversion, no single asset dominating, no month explaining a disproportionate share, sign
stability in the majority of blocks.

| Universe / model / contrast | overall | assets + | dominance | sign flips |
|---|---|---|---|---|
| **D log-OLS Δ_B1** | +0.00303 | **6/6** | 0.39 | 0 |
| **D LightGBM Δ_B2\|B1** | +0.00323 | **6/6** | 0.46 | 0 |
| D Gamma Δ_B1 | +0.00121 | 4/6 | 0.46 | 0 |
| D LightGBM Δ_Total | +0.00147 | 4/6 | 0.42 | 0 |
| V LightGBM Δ_B2\|B1 | **−0.00506** | 3/6 | 0.48 | 1 |
| V log-OLS Δ_B2\|B1 | +0.00002 | 4/6 | 0.36 | **4** |

Two discovery contrasts pass cleanly: positive in all six assets, no single asset carrying
more than 46 % of the absolute contribution, and no slice whose removal flips the sign. They
also survive the non-overlapping-origin subsample (D LightGBM Δ_B2|B1 +0.00237 on 6,012
independent origins, versus +0.00323 on the full overlapping grid), so the effect is not an
artifact of counting the same 30-minute target six times.

`V log-OLS Δ_B2|B1` with four sign-flipping groups out of six is the signature of pure noise
around zero, and is recorded as such.

## 3. Where the discovery effect lives — a timing dependence, not a uniform effect

Both passing contrasts concentrate in the same two places:

| Slice | D log-OLS Δ_B1 | D LightGBM Δ_B2\|B1 |
|---|---|---|
| open (first 2 h) | +0.00037 | +0.00051 |
| midday | +0.00090 | +0.00099 |
| **close (last ~2 h)** | **+0.00721** | **+0.00758** |
| ordinary week | +0.00168 | +0.00187 |
| **expiration week** | **+0.00553** | **+0.00577** |
| high volatility | +0.00052 | +0.00078 |
| low volatility | +0.00420 | +0.00336 |

The effect is roughly **fifteen times larger near the close than at the open**, and about
three times larger in monthly expiration weeks. It is also larger in *low*-volatility
terciles, i.e. it is not a crisis phenomenon.

That pattern is interpretable — option activity concentrates into the close and into
expiration, and that is where an intensity innovation would plausibly say most about the next
thirty minutes — but it is also exactly the pattern a conditioning-set artifact would
produce, and Block 10's Giacomini-White test confirms the loss differential **is** state
dependent in discovery (p < 10⁻⁴). Both readings remain open on this evidence.

## 4. Leave-one-asset-out: the mechanism does not transfer cleanly

D, LightGBM, Δ_B2|B1, refitting on the other five assets each time:

| held-out asset | AAPL | AMZN | META | MSFT | NVDA | TSLA |
|---|---|---|---|---|---|---|
| Δ_B2\|B1 | +0.0021 | +0.0076 | +0.0059 | +0.0077 | +0.0010 | **−0.0021** |

Five positive, one negative, spanning a factor of eight. In validation the same exercise
gives −0.025 (AMZN) to +0.042 (META) — a range twenty times the effect size, i.e. no
information at all about a common mechanism.

## 5. Minimum criterion — verdict

| Requirement | D | V |
|---|---|---|
| No systematic inversion | met for the two passing contrasts | met (nothing to invert) |
| No single asset dominating | met (≤ 0.46 absolute share) | met |
| No month dominating | met (4/5 and 3/5 months positive, 0 flips) | not met (1/2 months, 1 flip) |
| Sign stability in the majority of blocks | met | **not met** |
| Positive meta-estimate with heterogeneity reported | met, heterogeneity large | **not met — negative** |

**Advance rule "no concentrated dependence": PASS in D, FAIL in V.** The two discovery
contrasts are not driven by one asset, one month or one regime; they are driven by a *time of
day* and by expiration weeks, which is a genuine finding and is reported as such. Neither
survives into the validation era under any slicing.
