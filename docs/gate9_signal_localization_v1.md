# Gate 9 — Signal localization (v1, exploratory)

Compiled 2026-08-17. Code: `scripts/run_gate9_localization.py`; artifact
`artifacts/gate9_localization/results.json` (+ sha256; all input hashes recorded).
Label: EXPLORATORY_DEVELOPMENT_ONLY (the earnings section stratifies already-read
frozen differentials; nothing sealed is touched).

## 9.1 Grouped ablation (dev, log-OLS smooth-family proxy)

Feature groups: volume (trade count, unique-contract share), premium size (mean/max
premium, repeated-premium share), direction/concentration (call-put and side
imbalance, strike/expiry concentration). Walk-forward identical to Gate 3.

Every addition of B2 content to the base (B0+ATM-IV) specification makes development
OOF QLIKE **worse**: all nine −0.0035 (p 0.10); each group alone −0.0005..−0.0010;
each leave-one-group-out still negative. **On development data there is no positive
signal to localize — no feature group carries an increment.** Consistent with Gate 3
(B2 null-to-negative on HAR baselines) and the C1 LightGBM null.

## 9.2 Earnings-proximity stratification (frozen Gamma differentials)

Sessions t−1 / t / t+1 around date-only FMP earnings vs all other sessions:

| Campaign | Near earnings | Other sessions |
|---|---|---|
| C6 | +0.0234 (p 0.31, 7 strata days) | **+0.0548 (p 1.5e−08, 30 days)** |
| C4c | −0.0118 (p 0.79, 3 strata days) | **+0.0358 (p 7.0e−08, 30 days)** |

The economically most plausible mechanism — option flow is informative around
earnings — is **rejected**: the Gamma-specific effect lives in ordinary sessions and
disappears (or reverses) near earnings. No earnings-conditional estimand is available
as a rescue, and none will be registered (consistent with Gate 6's no-new-subgroups
position).

## 9.3 Horizon term structure (dev, HARQ baseline)

| Horizon | B2 increment | p |
|---|---|---|
| RV15 | −0.0019 | 0.39 |
| RV30 | −0.0011 | 0.57 |
| RV60 | +0.0011 | 0.56 |

Flat and null everywhere. A genuine short-lived information effect should be strongest
at 15 minutes and fade with horizon; a flat term structure supports the
artifact/era-specific interpretation of the retrospective effect.

## Synthesis

All three probes agree: **in the current (2026) era there is no localizable B2
information signal** — not in any feature group, not around earnings, not at any
horizon. Combined with Gates 1–8 this closes the localization question: the
retrospective Gamma-specific effect is era-bound (2024–mid-2025), family-bound, and
partially calibration-linked, and the prospective Phase 8 read (TOST-armed) is
positioned to state that conclusion affirmatively.
