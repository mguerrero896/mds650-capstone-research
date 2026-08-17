# Gate 2 — Calibration repair vs information (v1)

Compiled 2026-08-17. Re-analysis of already-read frozen forecasts only (decision-52
compliant). Code: `src/mds650/calibration.py`, runner `scripts/run_gate2_calibration.py`,
artifact `artifacts/gate2_calibration/results.json` (+ `.sha256`; input parquet sha256s
recorded inside). Design and interpretation rules were pre-stated in the runner docstring
and `docs/execution_backlog_20260817.md` before any delta was computed.

## Question

The Gamma GLM gains from B2 exactly where it is worst calibrated (R-020). Under QLIKE,
features that merely repair a biased baseline register as "information". Does Δ(B2)
survive when forecasts are Mincer-Zarnowitz-recalibrated (log scale, out-of-evaluation
fit, lognormal smearing)?

## Method

- MZ regression `ln(RV30) = a + b·ln(forecast)` per model × information set × campaign.
- Recalibration fitted strictly outside the scored sample: C6 Gamma on the frozen
  training OOF forecasts (`training_oof`); all other cells on the first half of
  evaluation sessions, scored on the second half (`split_sample`, prespecified). A C6
  split-sample sensitivity is reported so the two methods can be compared on the same
  campaign.
- Primary estimand: symmetric recalibrated Δ(B2) (both sides corrected). Secondary:
  base-only. Rules: C6 collapse below MDE 0.013040 ⇒ calibration artifact; C4c below
  0.005035 ⇒ same; C5 exploratory.

## Results (Gamma, symmetric recalibration; cluster-t p)

| Campaign | Method | Raw Δ(B2) (scored half) | Recalibrated Δ(B2) | Verdict vs rule |
|---|---|---|---|---|
| C6 B1v3 conf. | training_oof | +0.0532 (p 8.9e−08) | **+0.1351 (p 5.6e−09)** | **Survives ≫ MDE** |
| C6 B1v3 conf. | split sensitivity | +0.0696 (p 4.7e−07) | **+0.0528 (p 3.9e−06)** | **Survives ≫ MDE** |
| C4c PIT v2 | split_sample | +0.0338 (p 7.4e−05) | **−0.0152 (p 5.3e−04)** | **Collapses and reverses ⇒ calibration artifact** |
| C5-A 2024 (expl.) | split_sample | +0.0604 | +0.0811 (p 2.6e−09) | survives (exploratory) |
| C5-B 2024 (expl.) | split_sample | +0.0105 | +0.0372 (p 0.012) | survives (exploratory) |

LightGBM stays adverse-to-null everywhere after recalibration (C6 −0.0032, p 0.023;
C4c +0.0002 ns; C5-B −0.0005 ns). Full MZ tables (intercept/slope/R²/Wald) per cell are
in the artifact — headline calibration facts: C6 Gamma intercepts ≈ +2.8..+3.0 with
slopes ≈ 1.22..1.25 (severely miscalibrated) vs LightGBM ≈ (0, 1); C5 Gamma B0 slope
0.59 with intercept −4.6 (the R-020 explosion in MZ form).

## Bias-covariance diagnostic (2.2)

Per-day regression of the raw Gamma Δ(B2) differential on the day's mean baseline
log-bias `ln(actual/forecast_base)`:

| Campaign | Slope | t | R² |
|---|---|---|---|
| C6 | +0.145 | +7.45 | 0.66 |
| C5-A | +0.188 | +3.24 | 0.45 |
| C5-B | +0.040 | +1.12 | 0.09 |
| C4c | −0.052 | −2.02 | 0.24 |

On C6, two thirds of the daily variation in the B2 gain is explained by how biased the
baseline was that day — the calibration channel is real even where the effect survives.

## Verdict (pre-stated rules applied)

**SAMPLE_DEPENDENT.** On the binding C6 sample the Gamma-specific B2 increment survives
out-of-evaluation recalibration under both fitting methods, well above the frozen MDE —
objection R-020 no longer suffices to dismiss C6. On the corrected replication (C4c) the
same estimand collapses below the MDE and reverses sign — there, the raw gain was
calibration repair. The global/model-family-independent claim remains unsupported
(`confirmed_contrasts` untouched); what changes is the attribution: the C6 effect is not
*purely* bias repair, but its day-to-day size still tracks baseline bias (R² 0.66).

## Deferred (explicit)

- LightGBM gain/split importances → Gate 9 (requires refits).
- Stabilized-Gamma refit and OLS-on-log-RV benchmark for the 2024 blocks → Gate 3
  ladder (requires feature panels). MZ recalibration delivered here is the
  forecast-level stabilization.
