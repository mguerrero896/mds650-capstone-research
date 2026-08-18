# Block 3 — Gate 2: is RV30 the right target?

**Status:** `EXECUTED — 2026-08-18` · label `EXPLORATORY_MECHANISM_DISCOVERY`
**Artifacts:** `artifacts/rp2_block3_target/{target_panel.parquet, comparison.json}`
**Comparison SHA-256:** `7e5f833a83f8df2638a1a507fd061950e59b9b32b3fcd871a34e363da9e097b4`
**Code:** `src/mds650/rp2/realized.py`, `scripts/rp2_block3_target_panel.py`
**Tests:** `tests/unit/test_rp2_realized.py`

---

## 1. Design

Candidate targets are built from one-minute closes on a **common origin grid** so that all
horizons see the same origins: session minutes 120..265 in steps of 5, i.e. 30 origins per
session-asset. The restriction is required for comparability — an origin admissible for
`h = 120` must have 120 future minutes *and* 120 past minutes inside the session. It is not
the project's production grid and is used only for this comparison.

| Universe | Sessions | Session-assets | Panel rows |
|---|---|---|---|
| D | 240 | 1,772 | 53,160 |
| V | 80 | 480 | 14,400 |

2,280 session-assets were seen; **28 (1.2 %)** were dropped for having more than 5 % of their
minute grid absent.

> **Defect found and fixed while executing this block.** The first implementation measured
> session minutes from a fixed 13:30 UTC open. That is only correct under daylight saving;
> every winter (EST) session was silently truncated by 60 minutes and then discarded for
> excessive fill, throwing away **836 of 2,280 session-assets (37 %)**, most of the 2024
> discovery era. Session minutes are now measured from the 09:30 America/New_York open.
> Any future intraday grid in this project must do the same.

Measures per window of `h` one-minute returns, all verified against brute-force references
in the unit tests: `RV`, `BV = (π/2) Σ|r_j||r_{j-1}|`, `J = max(RV − BV, 0)`, `C = RV − J`,
`RQ = (h/3) Σ r_j⁴`, `RS+`, `RS−`.

## 2. Measurement noise is a property of the horizon, not of the model

Barndorff-Nielsen–Shephard relative standard error, `sqrt(2·RQ/h) / RV`, median over D:

| h | 5 | 15 | 30 | 60 | 120 |
|---|---|---|---|---|---|
| relative noise | **52.1 %** | 34.3 % | **25.7 %** | 19.1 % | 14.1 % |

At the project's registered horizon roughly **a quarter of the target is the estimator's own
sampling error**. No model can explain that part. This alone caps the attainable R² and is
the single strongest argument against shorter horizons: at `h = 5` more than half the target
is noise.

## 3. Predictability from underlying history alone

Out-of-sample log-scale R² of `log target ~ 1 + log RV_back(h) + log RV_session-to-date +
log RV_prev-day`, fitted on the first 60 % of each universe's sessions and evaluated on the
rest.

| target | h=5 | h=15 | h=30 | h=60 | h=120 |
|---|---|---|---|---|---|
| **RV** (D) | 0.527 | 0.726 | 0.796 | **0.823** | 0.788 |
| **RV** (V) | 0.319 | 0.477 | 0.553 | **0.566** | 0.522 |
| Continuous (D) | 0.478 | 0.714 | 0.791 | **0.823** | 0.791 |
| Continuous (V) | 0.271 | 0.470 | 0.554 | **0.581** | 0.540 |
| Bipower (D) | 0.473 | 0.706 | 0.786 | **0.820** | 0.788 |
| Upside semivariance (D) | 0.281 | 0.598 | 0.728 | **0.791** | 0.772 |
| Downside semivariance (D) | 0.281 | 0.579 | 0.717 | **0.783** | 0.765 |
| **Jump** (D) | 0.308 | 0.347 | 0.354 | 0.350 | **0.357** |
| **Jump** (V) | 0.150 | 0.167 | **0.178** | 0.160 | 0.138 |

### Four findings

1. **Predictability peaks at h = 60, not at h = 30, in both universes.** RV60 beats RV30 by
   +0.027 log-R² in D and +0.013 in V, and it is simultaneously less noisy (19.1 % vs
   25.7 %). h = 120 falls back: the gain from averaging away noise is exhausted and the
   information in the conditioning set decays.
2. **The jump component is nearly unpredictable from underlying history** — R² ≈ 0.35 in D
   and ≈ 0.17 in V at every horizon, roughly half the level of total RV. That is precisely
   what makes `H_{B2,J}` worth testing: the jump component is where a baseline built on
   price history leaves the most unexplained, so option information has room to matter there
   that it does not have in the continuous part.
3. **Splitting RV does not help a price-only baseline.** The continuous component is no more
   predictable than total RV (0.791 vs 0.796 at h=30 in D; 0.554 vs 0.553 in V), and both
   semivariances are *less* predictable than the total at short horizons. Upside and
   downside are near-identical, so there is no asymmetry to exploit at these horizons.
4. **The 2026 validation era is much harder than the 2024–2025 discovery era.** Identical
   specification, identical grid: R² 0.796 → 0.553 at h=30. This is the same direction as the
   documented decay of the option-information effect, and it shows the decay is not specific
   to option features — the *underlying* itself became less forecastable from its own history.
   Any comparison of effect sizes across eras must carry this.

## 4. Approval rule and what it means for the frozen target

The program requires exactly one target/horizon to pass into confirmation, chosen using D
and V only. The evidence chooses **RV60**, not RV30.

**RV30 is not overturned here, because it is not mine to overturn.**
`docs/target_horizon_decision.md` is an owner-approved decision fixing RV30 (31 prices, 30
one-minute log returns) as the sole primary target, and every frozen campaign C1–C6 and the
sealed Phase 8 cohort are built on it. Changing the primary horizon would invalidate the
comparability of the entire existing record and cannot be done by an execution run.

Recorded therefore as a **decision requiring the owner's signature**:

> *Keep RV30 as the sole primary target (comparability with C1–C6 and the sealed Phase 8
> cohort preserved, accepting 25.7 % measurement noise and a 0.027 log-R² predictability
> deficit), or add RV60 as a co-primary in future prospective work only.*

Until that signature exists, **RV30 remains frozen as primary**, and RV60 is carried as a
registered secondary in discovery/validation only.

## 5. Advance rule

"One primary target frozen": **PASS** — RV30 stays frozen as the single primary, on the
owner's standing decision, with the empirical case for RV60 documented and escalated rather
than acted on unilaterally. `J_h` and `ΔRV_h` are registered as secondary discovery targets
for the mechanism hypotheses `H_{B2,J}` and `H_{B2,ΔRV}`.
