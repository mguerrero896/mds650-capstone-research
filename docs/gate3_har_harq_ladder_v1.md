# Gate 3 — HAR intraday + HARQ in the ladder (v1)

Compiled 2026-08-17. Development data only; no sealed reads; decision-52 compliant.
Code: `src/mds650/har.py`, `scripts/acquire_gate3_dev_bars.py`, `scripts/run_gate3_har.py`.
Artifacts: `artifacts/gate3_har/{results.json,oof_forecasts.parquet}` (+ sha256; bar and
panel input hashes recorded), bars + manifest under
`MDS650_EXTERNAL_ROOT/data/fmp/gate3/`.

## What was added

The field-standard realized-variance baselines the confirmatory ladder never had:
an intraday HAR at the 30-minute horizon (components: 30-minute RV, session-to-date RV,
previous-session RV, 5-session mean RV, intraday-periodicity terms) and HARQ
(Bollerslev-Patton-Quaedvlieg realized-quarticity attenuation term
`(√RQ₃₀ₘ / RV₃₀ₘ)·ln RV₃₀ₘ`), fitted by log-OLS with lognormal smearing. Realized
quarticity comes from freshly acquired FMP 1-minute bars for the 80 development sessions
(6 outcome assets, 187,197 bars, per-session requests; manifest + sha256 recorded).

## Bar-label convention validated (A001 evidence)

The reconstructed 30-minute lagged RV matches the frozen panel's `b0_rv_30m_lag` with
**log-correlation 1.0000 under shift 0** (0.9962 under +1 minute). Two implications:
(a) the frozen pipeline's bar-availability convention is now empirically pinned and
reproducible; (b) FMP's historical 1-minute bars, re-downloaded on 2026-08-17,
reproduce the panel built months earlier — no silent historical revision for these
sessions. (Full cross-provider reconciliation stays Gate 5.1.)

## Design (pre-stated)

Common-complete development origins joined to the frozen B2 features; expanding
walk-forward with 30-session warm-up and 10-session test blocks (45 OOF sessions,
28,787 origin rows over 75 usable sessions — the first 5 sessions only feed the weekly
component). Winner rule: lower pooled OOF QLIKE between HAR and HARQ becomes the
preregistered base model of the prospective protocol.

## Results

Pooled OOF QLIKE: HAR 0.18394, **HARQ 0.18338 (winner)**, HAR+B2 0.18495,
HARQ+B2 0.18427.

| Contrast | Estimate | t | p_t | p_NW | p_wild |
|---|---|---|---|---|---|
| HARQ vs HAR | +0.00057 | +0.72 | 0.48 | 0.49 | 0.49 |
| HAR → HAR+B2 | **−0.00102** | −0.50 | 0.62 | 0.52 | 0.61 |
| HARQ → HARQ+B2 | **−0.00090** | −0.48 | 0.63 | 0.52 | 0.63 |

## Reading

**Against a competently specified HAR(Q) baseline, the B2 option-activity block adds
nothing on development data — the increment is null-to-negative.** This answers the
committee's first question ("does B2 beat a proper HAR?") in the negative for the
development window, and it is consistent with Gate 1 (the Gamma family never enters any
Model Confidence Set) and with the fixed LightGBM challenger's nulls: the recurring
positive B2 increment is specific to the miscalibrated Gamma GLM family, not to the
information set. HARQ is the preregistered base model for the Gate 4 prospective
amendment; the registered contrast there is HARQ vs HARQ+B2, reported next to the total
B0→B2 contrast.

Deferred note: the "stabilized Gamma / OLS-on-log-RV benchmark" item from roadmap 3.5 is
delivered functionally by this ladder (log-OLS on RV components) plus Gate 2's MZ
recalibration; no separate 2024-block refit is planned while the moratorium stands.
