# Block 4 — Gate 3: a B0 that is genuinely hard to beat

**Status:** `EXECUTED — 2026-08-18` · label `EXPLORATORY_MECHANISM_DISCOVERY`
**Artifacts:** `artifacts/rp2_block4_b0/{b0_panel.parquet, ladder.json}`
**Ladder SHA-256:** `e4a44706c283fb2a31896db8f7859ce6d90f193f307e9c1b644e610f2a258af3`
**Code:** `src/mds650/rp2/{bars.py, baseline.py}`, `scripts/rp2_block4_b0_panel.py`
**Tests:** `tests/unit/test_rp2_baseline.py`

---

## 1. What B0 contains

125,136 origins, 1,896 session-assets (24 dropped for excessive minute-grid gaps), six
target equities, target `rv30`, origins every 5 minutes from session minute 30 to 355.

| Group | Features |
|---|---|
| HAR components | log RV over the trailing 5, 15 and 30 minutes; session-to-date RV; previous-day RV; weekly RV (mean of five prior sessions) |
| HARQ term | log RQ over the trailing 30 minutes and the Bollerslev–Patton–Quaedvlieg attenuation `sqrt(RQ)·log RV` |
| Decomposition | upside and downside semivariance, jump proxy `max(RV−BV,0)`, all trailing 30 minutes |
| Liquidity / activity | Parkinson range variance, volume, dollar volume (trailing 30 minutes) |
| Returns | trailing 5- and 30-minute log return (leverage channel) |
| Seasonality | training-only mean log-variance index by 5-minute intraday bucket |
| Calendar | day of week, minutes since open, minutes to close |
| Market controls | SPY and QQQ trailing 30-minute RV and return — **where index bars exist** |

**Not included, and why.** VIX (or a PIT proxy) and sector ETFs are not held locally in any
form and would require new provider acquisition; earnings and macro event flags are governed
by `docs/corporate_event_contract.md` and are not wired into this panel. All three are
recorded as gaps rather than approximated.

**Market controls exist only for the phase6 window** (70,488 of 125,136 rows). The 2024
(gate7) and 2025 (gate8) discovery blocks and the whole validation window were collected
without SPY/QQQ bars. Rather than impute the gap, the model that uses them is fitted and
scored on that subset alone, against the same model without them on identical rows.

## 2. The ladder — B0 versus the five challengers

Fitted on the first 60 % of each universe's sessions, scored on the rest. QLIKE is the
project's primary loss (lower is better).

### Discovery (236 sessions, 53,856 train / 37,620 test origins)

| Model | QLIKE | log R² | MZ intercept | MZ slope | Calibrated |
|---|---|---|---|---|---|
| **B0 (core)** | **0.13382** | 0.7644 | −0.332 | 0.982 | no (marginal) |
| Simple HAR | 0.14123 | 0.7477 | +0.114 | 1.021 | yes |
| Persistence | 0.18993 | 0.6377 | **−2.749** | **0.772** | no |
| Intraday GARCH(1,1) | 0.19558 | 0.5153 | −0.478 | 0.993 | no |
| EWMA | 0.25243 | 0.4907 | +0.064 | 1.027 | yes |
| Intraday mean | 0.40698 | 0.2058 | −0.118 | 1.005 | yes |

### Validation (80 sessions, 19,008 train / 12,672 test origins)

| Model | QLIKE | log R² | MZ intercept | MZ slope | Calibrated |
|---|---|---|---|---|---|
| **B0 (core)** | **0.18145** | 0.6869 | +0.302 | 1.033 | no (marginal) |
| Simple HAR | 0.19322 | 0.6424 | −0.025 | 1.006 | yes |
| Intraday GARCH(1,1) | 0.22655 | 0.4012 | −0.813 | 0.961 | no |
| Persistence | 0.25553 | 0.4937 | **−3.662** | **0.682** | no |
| EWMA | 0.27923 | 0.3283 | −0.093 | 1.016 | yes |
| Intraday mean | 0.40567 | 0.3489 | −0.185 | 0.976 | yes |

**Approval rule — met.** B0 beats persistence, the intraday mean, EWMA, simple HAR and the
intraday GARCH on QLIKE in *both* universes, not just on average. The margin over the
nearest challenger (simple HAR) is −0.0074 QLIKE in D and −0.0118 in V.

## 3. Three findings worth keeping

**1. Market controls do not help. They hurt.** On identical rows (the phase6 subset), adding
SPY and QQQ trailing RV and return to B0 makes it *worse* out of sample:

| Model, same rows | QLIKE | log R² |
|---|---|---|
| B0 core | **0.12801** | **0.7872** |
| B0 + SPY/QQQ controls | 0.14072 | 0.7772 |

A +0.0127 QLIKE deterioration. Index-level variance carries no information about
next-30-minute single-name variance that the name's own trailing history does not already
carry, and four extra regressors cost more in estimation variance than they return. This
also settles the open question of whether the missing index bars in the 2024/2025 and
validation windows are a blocking gap: **they are not**, and no acquisition is warranted.

**2. Persistence is not just worse, it is badly biased.** MZ intercept −2.75 (D) and −3.66
(V) with slope 0.77 / 0.68. The trailing 30-minute RV is a noisy, downward-biased proxy for
the next 30 minutes. Any study using raw persistence as its baseline is manufacturing
headroom, exactly as the program warns.

**3. B0's calibration is era-dependent, and that is the honest caveat.** B0 fails the
intercept criterion marginally in both universes, and the sign **flips**: −0.332 in D
(over-forecasting) and +0.302 in V (under-forecasting), while the slope stays within 0.04 of
one. On the phase6-only rows B0 is well calibrated (intercept +0.020, slope 1.011). So the
miscalibration is not a defect of the specification — it is the level of realized variance
drifting between eras faster than a pooled intercept can track. This matters directly for
the project's central question: a shift in the *level* of the target between the fitting
window and the evaluation window shows up as a calibration error that any added information
set can appear to "repair", which is precisely the confound the Gate 2 recalibration test
was built for.

## 4. Advance rule

"Well-calibrated baseline": **PASS with a stated condition**. B0 dominates all five required
challengers on QLIKE in both universes and is well calibrated within an era; pooled across
eras it carries a level bias of about ±0.3 in log space whose sign flips between discovery
and validation. Downstream blocks therefore report every B1/B2 contrast **both raw and after
Mincer-Zarnowitz recalibration of the baseline**, so that a gain cannot be credited to
information when it is really repairing the baseline's level drift.
