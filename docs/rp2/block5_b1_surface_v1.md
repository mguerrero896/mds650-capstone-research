# Block 5 — Gate 4: B1 as a volatility surface, not an isolated ATM IV

**Status:** `EXECUTED — 2026-08-19` · label `EXPLORATORY_MECHANISM_DISCOVERY`
**Artifacts:** `artifacts/rp2_block5_surface/surface_coverage.json`
(`surface_sha256 = 7a89f88fd407cb2193ab1e42a0f692bad08a0f7915d2e9ee56928853c67ca2b5`);
panel `b1_surface_panel.parquet` is local-only, hashed in `artifacts/rp2_panel_pointers.json`
(`ec6409e9…fa65c`, 15.8 MB).
**Code:** `src/mds650/rp2/surface.py`, `scripts/rp2_block5_surface_panel.py`
**Tests:** `tests/unit/test_rp2_surface.py` (12 tests)

---

## 1. The acquisition problem, solved without new provider spend

Appendix A.2 of the program expected this block to require re-acquiring Massive quotes
across strikes and expiries — "far more volume than the current ATM-only extraction".

That turned out to be unnecessary. **Every row of the local option-trade tape carries the
prevailing NBBO (`nbbo_bid`, `nbbo_ask`) and the provider's implied volatility for that
contract at that instant.** Each trade is therefore a quote observation, and the union of
the most recent observation per contract before a cutoff is a point-in-time snapshot of the
surface. No new acquisition, no new cost.

The price of that shortcut is stated rather than hidden: **the strike grid is whatever
actually traded**, so the snapshot is sparse where the chain is illiquid, and the model-free
variance integral is biased downward on a sparse grid. Coverage is therefore reported per
origin (`b1_strikes`, `b1_expiries`, `b1_contracts`) and travels with every feature.

## 2. What was built

125,136 origins × 1,896 session-assets, **zero session-assets failed**, 99.7 % feature
coverage. Point-in-time rule: only rows with `created_at ≤ origin − 120 s` are visible — the
empirical cutoff established in Block 2, not the 60 s that Block 2 showed to be invalid.
Lookback window 30 minutes.

| Median per snapshot | Value |
|---|---|
| contracts | **724** |
| expiries | 22 |
| distinct strikes | 111 |
| quote age | 458 s |
| relative spread | 1.58 % |

Against the incumbent B1 — a single ATM implied volatility at 30–60 DTE — this is roughly
three orders of magnitude more of the surface.

### Features

| Group | Features |
|---|---|
| Constant-maturity level | `b1_iv_{7,14,30,60,90}d`, interpolated on **total variance** `w(T)=σ²T`, never on IV directly, with flat extrapolation in `w` |
| Term structure | `b1_term_slope` (60d−7d), `b1_term_convexity` (7d−2·30d+90d) |
| Smile shape | `b1_smile_slope`, `b1_smile_curvature`, `b1_smile_residual` from a quadratic fit in log-moneyness on the ~30-day bucket |
| Wings | `b1_risk_reversal_25`, `b1_butterfly_25` from Black-Scholes 25-delta interpolation |
| Model-free | `b1_mfiv`, the VIX-style integral over the observed OTM strike grid |
| Variance risk premium | `b1_vrp_30d = IV₃₀² − annualised trailing RV` |
| Quote quality / no-arbitrage | `b1_median_relative_spread`, `b1_median_quote_age_s`, `b1_strikes`, `b1_expiries`, `b1_pcp_residual`, `b1_calendar_violations` |

Deliberate simplifications, all recorded: zero rates and zero dividends (the tape carries no
discount curve; at 7–90 days the rate term moves delta by well under a delta-bucket width),
and forward ≈ spot. Surface PCA is not computed separately — level, slope, curvature and the
two term factors already span the modes PCA would recover, and adding a rotation of the same
span would inflate the feature count without adding information.

## 3. The surface is textbook, which is itself evidence

Medians over all 125,136 origins:

| Quantity | Median | Reading |
|---|---|---|
| IV 7d / 14d / 30d / 60d / 90d | 0.336 / 0.331 / 0.336 / 0.350 / 0.357 | upward-sloping term structure |
| `b1_term_slope` | +0.009 | mild contango |
| `b1_smile_slope` | **−0.190** | put skew — the classic equity sign |
| `b1_smile_curvature` | +1.164 | convex smile |
| `b1_risk_reversal_25` | **−0.0070** | puts richer than calls |
| `b1_vrp_30d` | **+0.0688** | implied variance exceeds trailing realized |
| `b1_calendar_violations` | 1 (of ~22 expiries) | mild, as expected from a traded-quote grid |
| `b1_pcp_residual` | 0.0034 of spot | put-call parity holds to ~34 bp |

Every sign is the one the literature reports for US equity options. That matters as a
validation of the reconstruction: a surface built from traded NBBO snapshots rather than a
continuous quote feed reproduces put skew, convexity, negative risk reversal and a positive
variance risk premium without any of them being imposed.

## 4. Approval rule

The program's rule is that B1 passes if `E[L(B0) − L(B1)] > δ_B1` in **at least two
independent families**, after calibration and with temporal stability.

Measured in Block 8 across six families:

| Universe | Δ_B1 |
|---|---|
| D, log-OLS | **+0.00303** [+0.00041, +0.00580], p = 0.019 |
| D, ridge (same family) | +0.00303 — does not count as a second family |
| D, Gamma GLM | +0.00121, ns |
| D, Tweedie GLM | −0.00177, ns |
| D, spline additive | +0.00446, ns |
| D, LightGBM | −0.00176, ns |
| **V, all six families** | **negative** (−0.0015 to −0.0023) |

**Verdict: FAIL on the stated rule.** One family is positive in discovery, none in
validation, and the program explicitly forbids counting ridge and log-OLS as two families.

**Advance rule — "improvement in D/V, *or* a clear mechanism": PASS on the second clause.**
The improvement is not there, but the mechanism is documented and reproducible: a
three-orders-of-magnitude richer, arbitrage-checked surface was built at zero acquisition
cost, and its failure to help is now a measurement rather than an absence of measurement.
The negative result is far stronger than the incumbent one precisely because B1 is no longer
a single ATM number — "B1 was under-represented" is no longer available as an explanation
for the null.
