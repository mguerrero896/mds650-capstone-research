# Literature reconciliation and contribution statement (v1, 2026-08-18)

Ex-ante predictions of each relevant literature strand versus what this project observed,
so the null/adverse findings read as *findings*, not defects. Citation discipline: only
ledger-verified sources (`docs/literature_evidence_ledger_v2.csv`) may be cited in the
thesis; strands whose anchors are still being retrieved are marked.

## Ex-ante predictions vs observations

| Strand | What it predicts here | What was observed | Reconciliation |
|---|---|---|---|
| HAR persistence (Corsi 2009 — retrieval pending, LIT-011; Puke & Schweikert 2026) | Lagged multi-horizon RV components dominate intraday RV forecasting; new predictors must beat them | HARQ is the best baseline of the ladder; B2 adds null-to-negative increments on HAR(Q) (Gate 3) | Fully consistent — the field's default explains the data; the candidate predictor does not improve on it |
| IV-predicts-RV (implied-volatility informativeness literature) | Option prices (B1/ATM-IV) should improve RV forecasts | B1 does not reliably beat B0 at 30 minutes; adverse under Gamma on two samples, selection-robust (Gates 1, 8) | Not a contradiction: that literature is predominantly daily-or-longer horizon without lagged-intraday-RV controls; with rich B0 dynamics at 30 minutes, ATM-IV level adds little. This is a *scope refinement* of the IV result, and one of the thesis's clearest findings |
| Options-activity / informed-trading (activity beyond prices) | Trade activity carries information, plausibly concentrated around information events (earnings) | Retrospective Gamma-only effect, era-bound (2024–mid-2025), anti-concentrated around earnings, invisible to calibrated/tree/HAR families, unlocalizable in features (Gates 1–3, 9) | The economically motivated version of the hypothesis is rejected in the current era; whatever the 2024 effect was, it does not behave like informed-trading signal |
| QLIKE proxy/calibration robustness (Patton 2011, retained LIT-012; Patton-Sheppard) | QLIKE rankings are trustworthy only for conditionally unbiased proxies and well-calibrated forecasts; miscalibrated models can rank-flip | Exactly observed: the family disagreement lives in the miscalibrated Gamma; recalibration flips C4c; the noise-robust proxy changes nothing (Gates 2, 7) | The "weird model dependence" is an anticipated phenomenon of the loss function — this strand *predicts* our headline complication |
| Options-driven ML volatility forecasting (Michael et al. 2025) | Option-surface features + ML beat econometric baselines at daily horizons | At 30 minutes, the ML challenger assigns B2 no value and the best MCS cell is the tree model with no option data (Gate 1) | Horizon matters: the daily-horizon result does not transfer intraday under strict PIT rules |

## Contribution statement (for the thesis)

1. **A preregistered, prospective, one-read null at an intraday horizon** for both
   conventional option state and option-trade activity, executed under hash-sealed
   protocols with access-ledger control — with a second prospective, TOST-armed read
   scheduled, so absence of effect is evidence, not silence.
2. **A scope refinement of the IV-informativeness result**: at the 30-minute horizon,
   with lagged intraday RV controlled, ATM-IV adds no reliable predictive value for six
   mega-cap equities — a boundary the daily-horizon literature does not map.
3. **A worked demonstration of Patton (2011) in the field**: a statistically strong,
   robustness-surviving increment that exists only inside a miscalibrated model family,
   with the calibration channel quantified (recalibration tests, bias-covariance) — a
   cautionary result for QLIKE-based model comparisons.
4. **A methods contribution**: the fail-closed PIT/preregistration infrastructure —
   measured bar semantics with a cross-provider tripwire, live latency measurement of a
   vendor availability field, one-read seals, and studentized day-clustered inference —
   reusable for any intraday forecasting study on commercial data.
