# Unusual activity definition (Phase 3F calibration)

`option_activity_present` means that at least one eligible option trade is observed before the
configured operational cutoff. It is not an unusualness label. The primary dataset keeps the
natural prevalence of activity and does not balance or subsample evaluation origins.

The secondary `unusual_event` label is calibrated only after a historical trailing window. For
this controlled phase, the twenty sessions before Pilot V2 provide the calibration history. The
primary normalization is per asset and 30-minute New York time band, with median/MAD robust
scales, IQR fallback and asset-level fallback. A constant feature is recorded explicitly rather
than silently dividing by zero.

The intensity score is the median of the three largest positive robust z-scores among five
log-transformed continuous features: total premium, trade count, unique contract count, maximum
trade premium and repeated-contract premium. The p95 threshold is estimated from the same asset
and time band using calibration sessions only. The label is descriptive and must not be
interpreted as informed trading, bullishness, bearishness, opening activity or a recommendation.

The 15-second and zero-second cutoffs, asset-only/5-minute/60-minute bands and p90/p97.5
thresholds are sensitivities. No sensitivity may be selected because it has a more favorable
relationship with RV30.
