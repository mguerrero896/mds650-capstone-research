# B2 confirmation model card

This run fits all registered estimators on the 80-session development panel and reads the two 30-session historical blocks once for confirmation.

- Status: `PASS_TWO_NEW_BLOCKS_EVALUATED`
- Models: gamma_glm, lightgbm, har_rv, ridge, elastic_net
- Information sets: B0, B1a, B2
- Bootstrap: 10000 paired XNYS session clusters
- MDE: 0.00503510
- Primary estimand: QLIKE(B1a) - QLIKE(B2); positive means B2 lowers loss.
- No RL or deep neural network is used: the frozen task is supervised RV30 forecasting with a small tabular information set.

## Interpretation guardrails

Gamma GLM is the confirmatory estimator and LightGBM is a registered nonlinear
robustness challenger.  The two historical blocks support a positive B2
contrast for Gamma GLM, HAR-RV and Ridge, while LightGBM is negative in both
blocks.  Therefore the evidence is a replicated, model-dependent positive
signal, not a universal model-independent edge.  Elastic Net is not stable
enough to carry the primary conclusion.  Calibration is reported separately;
extreme mean forecast-to-actual ratios show that QLIKE improvements must not
be described as perfect calibration.
