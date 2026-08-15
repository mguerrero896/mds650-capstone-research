# B1v3 Development-Only Diagnostic Findings

## Decision

The observed failure of B1v3 to improve B0 is **not primarily explained by missing quotes, failed
IV inversion, rank deficiency, or unusable predictor coverage**. The development evidence instead
supports a model-and-regime instability diagnosis: ATM IV level has a meaningful fitted loading,
but the exact 5- and 30-minute IV-change terms contribute very small regularized Gamma
coefficients, and the B1 QLIKE contrast changes sign across chronological folds, assets, and
session segments. This is a predictive-mechanism diagnosis, not a causal finding.

The independent replication target was not read. Every statistic below comes from the frozen
60-session development block, 2024-09-16 through 2024-12-09.

## Data and coverage

| Evidence | Observed value | Consequence |
|---|---:|---|
| Predictor-only origins | 25,704 | Full diagnostic denominator across six assets and 60 sessions |
| Common complete origins | 23,134 (90.00%) | Sufficient B1v3a coverage for chronological modeling |
| B0-incomplete origins | 2,160 (8.40%) | Most exclusions occur before adding B1 |
| B1 level missing | 181 (0.70%) | Small B1-specific loss |
| Exact 5-minute lag missing | 123 (0.48%) | Small B1-specific loss after prior gates |
| Exact 30-minute lag missing | 106 (0.41%) | Small B1-specific terminal loss after prior gates |
| Quote/IV attempts in canonical origins | 767,376 | Large directed contract-origin evidence base |
| Quotes returned | 767,376 (100.00%) | Absence of quotes is not the dominant failure mechanism |
| Successful IV inversions | 755,772 (98.49%) | IV inversion generally succeeds |
| Median / P95 quote age | 2.22 s / 31.08 s | Quote freshness is technically strong under the registered filter |
| Median / P95 relative spread | 1.37% / 4.08% | Spread quality is generally strong |

The 11,604 failed IV attempts consist of 11,463 stale quotes, 114 invalid spreads and 27
arbitrage-bound failures. MSFT has the largest stale-quote count (4,630), but all six assets retain
high IV success; therefore these failures alone cannot explain the sign of the B1 contrast.

## Feature behavior and specification

The three B1v3a fields are not constant. Their finite coverage is 99.29% for ATM variance level,
97.41% for the exact 5-minute change, and 90.41% for the exact 30-minute change. The complete
14-column B0+B1v3a design matrix has full rank, condition number 8.77 and no zero-variance field.
The highest absolute pairwise correlation (0.943) is between the two pre-existing B0 market RV
controls, not a B1 field. Thus, exact multicollinearity is not the failure cause.

Under the final training-only Gamma selection, B0 chooses alpha 0.0 and B1v3a chooses alpha 0.1.
The B1v3a standardized/link-scale coefficients are:

| B1v3a feature | Coefficient |
|---|---:|
| Log ATM variance level, 30 DTE | 0.147143 |
| Log ATM variance change, 5 minutes | -0.004748 |
| Log ATM variance change, 30 minutes | 0.007359 |

The level term carries nearly all fitted B1 contribution while both change terms are numerically
small after regularization. ATM level also has moderate overlap with B0 information: its largest
cross-set correlations are 0.558 with five-minute log dollar volume and 0.346 with the underlying
30-minute realized-volatility control. This supports partial redundancy, not exact duplication.

## Chronological QLIKE diagnosis

Positive `QLIKE(B0) - QLIKE(B1v3a)` favors B1v3a. The three untouched development OOF folds show:

| Fold | Sessions | Origins | Delta B1v3 |
|---:|---:|---:|---:|
| 101 | 10 | 3,910 | +0.013131 |
| 102 | 10 | 3,948 | -0.031584 |
| 103 | 10 | 3,719 | -0.004535 |
| Pooled, origin-weighted | 30 | 11,577 | -0.007792 |

B1 improves B0 in only one of three chronological folds. Fold 102 is the clearest failure and is
concentrated in TSLA (-0.188089), with additional negative contributions from NVDA, AAPL and META.
All three session terciles are negative in that fold, especially the last tercile (-0.051705).
Fold 103 remains mildly negative in aggregate and in five of six assets. The mechanism is therefore
temporally and cross-sectionally unstable rather than globally absent in every period.

## Exact diagnosis

1. **Rejected as primary causes:** missing quote coverage, broad IV inversion failure, near-constant
   B1 fields, exact rank deficiency, and close-only availability.
2. **Supported mechanism:** B1v3a adds one useful ATM-level signal plus two weak incremental change
   terms to an already strong B0; regularization and moderate redundancy limit its incremental
   contribution.
3. **Dominant observed failure:** the incremental relationship is not stable across time and assets,
   with a large TSLA-specific reversal in the second OOF block.
4. **Scientific implication:** retain B1 as the conventional option-state benchmark, but do not
   claim it improves B0 globally. The preregistered independent block must adjudicate whether B2's
   incremental result reproduces under the unchanged B0/B1v3a/B2 contract.

## Evidence boundary

- Canonical machine-readable diagnostic:
  `artifacts/b1_diagnostic_replication/diagnostic/diagnostic.json`
- OOF losses:
  `artifacts/b1_diagnostic_replication/diagnostic/chronological_loss_deltas.csv`
- Coefficients:
  `artifacts/b1_diagnostic_replication/diagnostic/gamma_coefficients.csv`
- Complete evidence index:
  `artifacts/b1_diagnostic_replication/diagnostic/evidence_index.csv`
- Replication target reads recorded during this diagnostic: **0**.
- No result sign was used to alter dates, features, models, timing assumptions, or inference.
