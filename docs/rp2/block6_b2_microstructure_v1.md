# Block 6 — Gate 5: B2 rebuilt as microstructure

**Status:** `EXECUTED — 2026-08-19` · label `EXPLORATORY_MECHANISM_DISCOVERY`
**Artifacts:** `artifacts/rp2_block6_flow/flow_coverage.json`
(`flow_sha256 = a64484c0cc32402dfcd8c9cb2837ddad91a4b19263b3548c16f9bf11c6cd98fc`);
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

Medians over all origins:

| Feature | 5 min | 30 min |
|---|---|---|
| trades | 873 | 5,619 |
| distinct contracts | 156 | 743 |
| premium | $1.98 M | $32.5 M |
| buy premium share | 0.468 | 0.440 |
| sell premium share | 0.406 | 0.450 |
| passive premium share | 0.105 | 0.098 |
| sweep premium share | 0.012 | 0.015 |
| OTM premium share | 0.514 | 0.470 |
| interarrival CV | **1.82** | — |
| contract entropy | 3.32 nats | — |
| strike HHI | 0.151 | — |

The interarrival coefficient of variation of **1.82** is the single most important
descriptive number here: a Poisson process gives 1.0, so option trade arrivals are strongly
clustered and a Hawkes term is not decoration — it is measuring something the incumbent
five-minute count could not represent.

## 4. Advance rule

**"Target-blind features frozen": PASS.** Every feature is computed from information
strictly before `origin − 120 s`; no column touches the target, and the same builder ran
identically over the discovery and validation universes.

The program's approval rule for B2 ("must beat B1: on average; after residualization; under
calibration; in two families; without depending on a single feature, session or asset") is
evaluated in Blocks 7–9, not here. Its outcome, in short: **the residualization test passes
and everything else fails** — see `docs/rp2/block7_dml_v1.md` and
`docs/rp2/block8_ladder_v1.md`.
