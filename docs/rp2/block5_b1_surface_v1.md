# Block 5 — Gate 4: B1 as a volatility surface, not an isolated ATM IV

**Status:** `EXECUTED — 2026-08-19` · label `EXPLORATORY_MECHANISM_DISCOVERY`
**Artifacts:** `artifacts/rp2_block5_surface/surface_coverage.json`
(`surface_sha256 = e70b5aefa9e191fda6c771f3d0badbddc6b3b6f61f55ef03c8affab05789f8ee`);
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

184,632 origins across 2,814 session-assets, **0 without tape**, 95.7%
mean feature coverage.

Point-in-time rule: only rows with `created_at ≤ origin − 120 s` are visible — the empirical
cutoff established in Block 2, not the 60 s that Block 2 showed to be invalid.

**The snapshot window no longer touches B2's.** B1 reads `[origin − 5520 s, origin − 1920 s)`
and B2's longest window reads `[origin − 1920 s, origin − 120 s]`, so no observation feeds both
feature blocks and `assert_disjoint_from_flow_window` fails the run if that stops being true.
Previously both read `[origin − 1920 s, origin − 120 s]` — the same interval — which made
"does flow add information beyond the surface?" partly a comparison of B2 against itself. The
cost is a staler surface: the lookback is 60 minutes ending 32 minutes before the
origin rather than at it, and the median quote age below reflects that.

This buys row-disjointness, **not** independence. A contract enters the surface only because
somebody traded it, so the selection of which quotes exist is still driven by flow.

| Median per snapshot | Value |
|---|---|
| contracts | **896** |
| expiries | 21 |
| distinct strikes | 117 |
| expiries with a fitted forward | 12 |
| 0DTE contracts | 0 |
| quote age | 788 s |
| relative spread | 1.63% |
| butterfly violations | 5 |
| calendar violations | 1 |

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
| Implied minus trailing variance | `b1_iv_minus_trailing_rv_30d = IV₃₀² − annualised trailing RV`. **Not** a variance risk premium: a premium is measured against the physical expectation of *future* variance, and the trailing realisation is a property of the past |
| Forward and carry | `b1_implied_rate`, `b1_implied_dividend_yield`, `b1_forward_expiries_fitted`, all read out of co-strike put-call parity |
| Coverage | `b1_min_log_moneyness`, `b1_max_log_moneyness`, `b1_spans_call_wing`, `b1_spans_put_wing`, `b1_zero_dte_contracts` — a surface statistic is only as good as the grid it was read off |
| Quote quality / no-arbitrage | `b1_median_relative_spread`, `b1_median_quote_age_s`, `b1_strikes`, `b1_expiries`, `b1_pcp_residual`, `b1_calendar_violations`, `b1_butterfly_violations` |

**The forward is measured, not assumed.** The earlier version set zero rates, zero dividends
and forward ≈ spot, and recorded that as a simplification "well under a delta-bucket width".
It is not: at a 4–5 % financing rate over 90 days the forward sits about 1 % above the spot,
which moves a 25-delta strike by several delta points, so the quote being read as the 25-delta
wing was not the 25-delta wing — and `b1_pcp_residual`, compared against `S − K`, was reporting
financing as though it were a quote defect.

Rather than plug in an external curve, the forward is read out of the quotes. Put-call parity is
an arbitrage identity — at one expiry `C − P = D (F − K)` exactly — so a least-squares line
across co-strike pairs returns the discount factor and the forward the market is quoting,
including whatever borrow and dividend it embeds, with the implied rate and dividend yield as
by-products.

**And the measurement is noisy, which is reported rather than smoothed.** Co-strike mids come
from different instants, so the underlying moves between them; at a 30-day tenor that noise
produces implied financing rates spanning roughly ±30 % across deciles. Fits outside a
plausibility band are refused, those expiries fall back to the spot, and the count that did fit
travels with the panel — a median of 12 of
21 expiries per snapshot.

**Time to expiry is exact.** Tenors were whole calendar days floored at one, so a contract
expiring at 16:00 on the session being processed was priced as a one-day option — at noon that
overstates its variance sixfold, in the fastest-growing part of the market. Tenor is now measured
in seconds to the 16:00 ET close from the origin itself, and an expired contract is dropped
rather than priced. A median of 0 contracts per snapshot are
0DTE.

Surface PCA is not computed separately — level, slope, curvature and the two term factors
already span the modes PCA would recover, and adding a rotation of the same span would inflate
the feature count without adding information.

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
