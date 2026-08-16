# Literature synthesis for the B1/B2 closure

The ten rows in `docs/literature_matrix.csv` were checked against Crossref
metadata on 2026-07-21 (all ten DOI lookups returned HTTP 200). The evidence
ledger distinguishes four rows with source-text coordinates, three rows with
abstract-only support and three rows with publisher-record-only support. No row
is treated as evidence of MDS650 predictive performance unless its coordinates
and claim scope permit it.

## Ordinary option information

Michael, Cucuringu and Howison (2025) compare option-surface and activity
features against HAR using LASSO, Elastic Net, XGBoost and model-derived
Heston/Bates variants under rolling out-of-sample evaluation with QLIKE, RMSE,
DM and MCS. This supports an independently timestamped B1, not a substitution
of current snapshots for historical quotes.

## Option flow and informed trading

Asencio et al. (2026) decompose intraday option order flow into delta- and
vega-related informed components. It is not an RV forecast benchmark and does
not justify interpreting calls, puts, ask-side trades or sweeps as direction.

## Intraday realised-volatility forecasting

Caporin et al. (2024), Zhang et al. (2024), Li et al. (2024) and Puke and
Schweikert (2026) provide recent applications of HAR-type decompositions,
QLIKE/MSE evaluation, signed-jump features and coherent forecast
reconciliation. Their daily or component targets differ from RV30, so they
justify named controls and loss functions only; they do not establish an
option-activity effect for this project.

## Benchmark comparisons

Díaz et al. (2024) compare Ridge, LASSO, Elastic Net, Random Forest, Gradient
Boosting and NARX neural networks against HAR at monthly horizons. Li and Tang
(online 2024/issue 2025) compare LASSO, PCR, RF, GBRT, NN and weighted/simple
averages against HAR/OLSALL. Kiliç (2025) compares ARFIMA, HAR, THAR, STHAR,
MSHAR, Extreme Gradient Boosting, feed-forward NN, BRNN, LSTM, LSTM-A and GRU
under rolling regimes. Omer et al. (2026) compare Ridge, LASSO, Elastic Net,
regression trees, RF, NN5/NN10 and sparse-group LASSO against HAR/HAR-XX for
WTI. Li et al. (2024) compare standard HAR with LASSO and Elastic Net using
cross-market predictors. These are exact model lists and study-specific
results, not the prohibited generic claim that linear models are hard to beat.

## Implication for MDS650

Pre-register HAR/HARQ/OLS and named ML comparators only after PIT, common
history and asset gates pass. Keep B1 independent from B2; preserve the natural
continuous-feature prevalence; use QLIKE as the single primary loss only after
the final test protocol is frozen. The matrix is complete, but six rows remain
limited to abstract or publisher metadata. Those rows cannot support numeric
superiority, leakage or model-ranking claims until full text and coordinates are
captured; this evidence limitation does not authorize any model run or larger
backfill.
