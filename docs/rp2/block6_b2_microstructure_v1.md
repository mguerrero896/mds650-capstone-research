# Block 6 — Gate 5: B2 rebuilt as microstructure

**Status:** `SUPERSEDED_BY_RP2_V3` — executed 2026-08-19, superseded 2026-08-20 by
`fix/rp2-v3-exact-clock-b2` (methodology decision 81). The run below is retained
unchanged; the replacement is
`artifacts/rp2_v3/gate5-exact-clock-b2/flow_coverage.json`
(`flow_sha256 = 773c3d3d7f07ef9214ba6b4bc5383ab34723b6fbdbd4a468544cbbb244516f69`, 70 features, panel
`972fa80b…a3de2`, 75.5 MB).
· label `EXPLORATORY_MECHANISM_DISCOVERY`
**Artifacts:** `artifacts/rp2_block6_flow/flow_coverage.json`
(`flow_sha256 = d7320a546cfe2ffc113baab555b3b663bbcffa678495d7ee80fb4b31820d3306`);
panel `b2_flow_panel.parquet` is local-only, hashed in `artifacts/rp2_panel_pointers.json`
(`b4066780…5e9e4`, 43.7 MB).
**Code:** `src/mds650/rp2/flow.py`, `scripts/rp2_block6_flow_panel.py`
**Tests:** `tests/unit/test_rp2_flow.py` (10 tests)

---

## 1. The diagnosis being tested

The program's hypothesis is that the incumbent B2 destroyed the signal by **premature
aggregation**: thousands of trades reduced to nine counts in five-minute windows, discarding
sequence, direction, clustering, moneyness, tenor, Greeks and quote impact.

This block rebuilds B2 keeping all of them: **52 features** over two windows (5 minutes and
30 minutes) at each of 125,136 origins, 1,896 session-assets, **zero failures**, 99.7 %
coverage. Point-in-time rule: `created_at ≤ origin − 120 s`.

| Group | Features |
|---|---|
| Greeks-weighted signed flow (6.1) | `vega_flow`, `gamma_flow` (×S²), `delta_flow` (×S), plus splits by call/put and by short (≤7d) / long (>30d) tenor, and `vega_flow_abs` |
| Activity level | `trades`, `contracts`, `size`, `premium` |
| Direction and type (6.6) | `buy_/sell_/passive_premium_share`, `sweep_premium_share`, `otm_premium_share` |
| Intensity and burstiness (6.3) | `hawkes_last`, `hawkes_innovation`, `rate_per_second`, `interarrival_cv` |
| Concentration (6.3) | `strike_hhi`, `expiry_hhi`, `contract_entropy` |
| Trade-to-quote impact (6.4) | `d_iv`, `d_mid_rel`, `d_spread`, each versus the previous trade **in the same contract** |
| Age | `median_age_s` |

### Direction is read, not inferred

The tape carries a per-trade side tag (`ask_side` = buyer initiated, `bid_side` = seller
initiated, `mid_side` = passive). Direction comes from that tag and never from subsequent
price moves. The provider's `ask_vol` / `bid_vol` / `multi_vol` columns look like per-trade
side volumes but are **cumulative per contract** — over 97 % of rows have all three positive
— and are deliberately unused. This is consistent with the existing
`docs/b2_feature_contract_v2.md` exclusion of provider cumulative fields.

### The moneyness × DTE tensor (6.5) is not built

The program gates it explicitly: use a tensor with group-lasso / PCA / DeepSets "**but only
after demonstrating that the tabular baseline does not capture the signal**". Block 8 shows
the tabular baseline captures no signal to begin with, so there is nothing for a tensor to
recover that the tabular features missed; the prerequisite is not met and the tensor is not
built. Tenor and moneyness enter as the registered splits instead.

## 2. A performance defect found and fixed during execution

The first implementation computed the Hawkes intensity, the Greeks and the trade-to-quote
impact **inside each origin's window**. That is `O(origins × window)`: with ~5,000 trades in
a 30-minute window, 66 origins per session and 1,896 session-assets, the Hawkes recursion
alone would have executed on the order of 10⁹ Python iterations. The run was aborted after
it failed to make measurable progress.

The rewrite computes every per-trade quantity **once per session** and prefix-sums it, so a
window feature is one subtraction regardless of how many trades the window contains. The
normal CDF also moved from `np.vectorize(math.erf)` (a Python call per element) to
`scipy.special.ndtr`. Only the three concentration statistics, which are not prefix-summable,
are still evaluated on a window slice — and only on the short 5-minute one.

**Result: from "did not finish" to 13 minutes** for the whole 1.4-billion-row tape.

## 3. What the rebuilt B2 looks like

184,632 origins over 2,814 session-assets,
0 without tape, **60 features**.

Medians over all origins:

| Feature | 5 min | 30 min |
|---|---|---|
| trades | 1,464 | 9,526 |
| distinct contracts | 271 | 697 |
| premium | $4,416,104 | $30,118,926 |
| buy premium share | 0.351 | 0.352 |
| sell premium share | 0.349 | 0.348 |
| passive premium share | 0.266 | 0.285 |
| sweep premium share | 0.014 | 0.017 |
| OTM premium share (sided) | 0.182 | 0.189 |
| multi-leg size share | 0.134 | 0.147 |
| mean provider latency (s) | 0.1 | 0.1 |
| late arrival share (>60 s) | 0.000 | 0.000 |
| interarrival CV | 1.75 | — |
| contract entropy (normalised) | 0.722 | — |
| strike HHI (normalised) | 0.079 | — |

The interarrival coefficient of variation of **1.75** is the single
most important descriptive number here: a Poisson process gives 1.0, so option trade arrivals
are strongly clustered, and a decay-weighted arrival measure is not decoration — it captures
something a five-minute count cannot represent.

**On the name of that measure.** It was called a Hawkes intensity. Its baseline, excitation and
decay were fixed inputs at every call site; nothing was estimated, so there is no
self-excitation parameter, no branching ratio and no stability condition behind it. Calling it
Hawkes asserted a fitted point-process model that does not exist. It is
`exponential_decay_intensity`, and the clustering above is evidence that *some* self-exciting
model would be worth fitting — not evidence that one was.

**Concentration is normalised.** Raw Herfindahl has a floor of `1/n` and raw entropy a ceiling
of `log n`, so both moved simply because more contracts traded: `strike_hhi` fell on busy
windows regardless of how concentrated the flow actually was. Both are now mapped to `[0, 1]`,
and a single positive weight returns NaN rather than 1 — concentration relative to nothing is
undefined.

**Multi-leg prints carry volume but not direction.** A side tag on a spread leg describes how
that leg crossed the NBBO, not what the trader was expressing: the short leg of a call vertical
prints `bid_side` while the order is bullish. Those prints are identified from the rise in the
contract's running `multi_vol` total and are now unsigned, so they no longer manufacture signed
flow — they still count as volume, and their share is a feature.

**Both clocks travel.** `executed_at` is the exchange clock and `created_at` is when the
provider made the trade available. Windows still select on availability, because that is what a
forecaster could see, but the gap between the two is now measured rather than assumed.

## 4. Advance rule

**"Target-blind features frozen": PASS.** Every feature is computed from information
strictly before `origin − 120 s`; no column touches the target, and the same builder ran
identically over the discovery and validation universes.

The program's approval rule for B2 ("must beat B1: on average; after residualization; under
calibration; in two families; without depending on a single feature, session or asset") is
evaluated in Blocks 7–9, not here. Its outcome, in short: **the residualization test passes
and everything else fails** — see `docs/rp2/block7_dml_v1.md` and
`docs/rp2/block8_ladder_v1.md`.
