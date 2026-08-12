# Target-Blind Primary Comparison Contract v1

## Purpose

The earlier v4 method freeze fixes the target, predictors, models, metrics and
inference procedure, but it does not state the two primary nested comparisons
as first-class contract fields. This additive v1 record closes that omission
without changing or overwriting the immutable v4 record.

It is metadata-only and does not read a predictor panel, RV30, forecasts,
QLIKE values, model artefacts, holdout/OOS results, or provider credentials.

## Frozen primary ladder

| Information set | Composition | Role |
| --- | --- | --- |
| B0 | Parent v4 `B0` controls | Underlying/market benchmark |
| B1a | B0 plus parent v4 `B1a_addition` | Primary ordinary-options-state challenger |
| B2 | B1a plus the nine frozen parent v4 `B2_addition` features | Primary options-activity challenger |

The fixed primary estimands are the daily means of:

- `QLIKE(B0) - QLIKE(B1a)`: a positive value favors B1a.
- `QLIKE(B1a) - QLIKE(B2)`: a positive value favors B2.

Those statements define a future test direction; they do not assert that
either value is positive.

## Anti-selection rules

- B1a cannot be replaced by B1b or B1c because of coverage, sign, QLIKE or a
  predictive outcome. B1b and B1c remain pre-specified robustness analyses.
- Features, assets, model family and the primary comparison cannot be selected
  after RV30 or QLIKE is observed.
- The parent’s Gamma-log GLM, fixed LightGBM robustness model, QLIKE primary
  metric, daily-cluster paired bootstrap and Holm procedure remain binding.

## Gates retained

The contract leaves all operational gates closed: no reconciliation of sealed
results, no OOS access, no model fit or metric evaluation, no new historical
acquisition and no prospective capture. A fresh date-level PIT preflight and
separate explicit authorization are still needed before those operations.
