# Gate cascade report — 2026-08-17

One-day execution of the ten-gate backlog derived from the scientific gap audit (the
working backlog itself is an internal record, kept local). Every gate: code merged on `main` with tests, ruff +
mypy-strict + full pytest green, hashed artifacts, per-gate doc, and the publication
mirror updated (`scripts/publish_mirror.sh`). This report is the reading order for a
committee member.

## What was asked

Close the gaps between the recorded verdict (`POSITIVE_BUT_NOT_GLOBALLY_CONFIRMED`,
model-family dependent, decaying toward the present) and a defensible thesis: harden
inference, test the calibration alternative, add field-standard baselines, arm the
prospective read, measure the PIT assumptions, and localize the signal — reporting
every number exactly as it lands.

## Verdict movement, gate by gate

| Gate | Question | Answer | Doc |
|---|---|---|---|
| 1 | Do the headline p-values survive real statistics? | Yes retrospectively: every Gamma B2 contrast survives Newey-West and wild cluster bootstrap (C6 p ≈ 1e−04 vs saturated 2e−04 floor). The family interaction is now a formal test: significant in every retrospective sample, **null in the prospective holdout** (p 0.89). **The Gamma family never enters any Model Confidence Set** — C6's sole survivor is LightGBM with no option data. | `gate1_inference_hardening_v1.md` |
| 2 | Is the Gamma B2 gain just calibration repair? | **Sample-dependent**: survives out-of-evaluation Mincer-Zarnowitz recalibration on C6 (+0.053..+0.135, ≫ MDE) under both fitting methods, but collapses and reverses on C4c (−0.015). C6 daily gains still track baseline bias (R² 0.66). R-020 alone no longer dismisses C6; no global claim changes. | `gate2_calibration_vs_information_v1.md` |
| 3 | Does B2 beat a proper HAR? | **No.** HARQ wins the ladder (pooled OOF QLIKE 0.18338) and B2 adds a null-to-negative increment on both HAR baselines (−0.0010/−0.0009). Bonus: reconstructed 30-min RV matches the frozen panel with log-correlation 1.0000 — bar convention pinned, FMP history reproducible. HARQ is the preregistered base for the prospective amendment. | `gate3_har_harq_ladder_v1.md` |
| 4 | Is the decay real, and is Phase 8 worth running? | Decay measured: −0.0277/year (wild p 1e−04); both families converge to ≈ +0.005 at the Phase 8 midpoint. TOST bound 0.005035 recorded pre-read — adequately powered for the frozen tree-family primary; a null becomes affirmative evidence and confirms the decay by precommitment. | `gate4_prospective_design_v1.md` + Phase 8 protocol amendment |
| 5 | Are the two foundational PIT assumptions true? | **A001 (bar semantics): measured and retired** — FMP and Massive agree exactly under identical labels across 2024/2025/2026. A002 (`created_at`): live latency campaign built, dry-run proven, four scheduled tasks Ready; first real capture from the 2026-08-17 NY session, first reconciliation ≈ 2026-08-24. | `gate5_pit_foundations_v1.md` |
| 6 | Is the effect an event/regime artifact? | **No**: leave-event-week-out leaves every retrospective contrast significant (two of three increase), and the calmest window (C6, VIX median 15.1) carries the largest effect. The decay is time-linked, not regime-linked. | `gate6_regime_composition_v1.md` |
| 7 | Is it microstructure-proxy error? | **No**: AC(1) is tiny (max |0.033|), implied noise bias ≤ 6.5% of RV, and the AC(1)-corrected target leaves both the Gamma gain (+0.0522) and the LightGBM reversal (−0.0050) intact. | `gate7_noise_robust_target_v1.md` |
| 8 | Is it common-complete selection? | **No**: inclusion is 97.4% on C6 and IPW reweighting moves estimates in the fourth decimal. The adverse B1-worse-than-B0 finding is not selection-driven either. | `gate8_selection_bias_v1.md` |
| 9 | Where does the signal live now? | **Nowhere current**: no feature group carries a dev increment (all negative), the effect concentrates AWAY from earnings (mechanism rejected), and the horizon term structure is flat. | `gate9_signal_localization_v1.md` |

## The thesis narrative these gates support

1. The only prospective, preregistered test was null (C2), and the second prospective
   test (Phase 8, 30/30 on 2026-08-29) is TOST-armed so a null is affirmative.
2. A recurring, statistically hardened, Gamma-specific retrospective B2 increment
   exists in 2024–mid-2025 samples. It survives HAC/wild inference, recalibration (on
   C6), event-week removal, a noise-robust proxy, and selection reweighting — and it
   still is **not** evidence of usable information: it is invisible to a calibrated
   tree challenger, absent against HAR(Q) baselines, outside every Model Confidence
   Set, unlocalizable in features, anti-concentrated around earnings, flat across
   horizons, and decaying at −0.028/year to zero in the present.
3. Conventional option state (B1) does not beat B0 at this horizon; that finding also
   survives the selection check.
4. Both foundational PIT assumptions are now measured facts or under live measurement,
   with a permanent, honestly-stated residual for the historical (2024/2025) tapes.

## Still open (calendar-bound, automated)

- First UW latency capture report: 2026-08-18 06:20 local; first tape reconciliation
  ≈ 2026-08-24 (scheduled tasks `MDS650_UW_Latency*`).
- Phase 8 completes 30/30 on 2026-08-29 (tasks `MDS650_Phase8A_*`); the one-shot read
  then requires the owner's written authorization per the protocol.
