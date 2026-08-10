# Development stability audit v2

Status: `PASS_DEVELOPMENT_DESCRIPTIVE_ONLY`

This audit summarizes the frozen Phase 5 development stability artifact. It
does not read independent outcomes, does not alter the method freeze, and does
not select a model from a favorable sign.

## Scope and rule

The audit covers 12 predeclared strata: six assets, three session terciles and
three development-defined volatility regimes. A material negative stratum is
defined as a paired-day bootstrap interval with `ci_high < 0`. The registered
systematic-reversal rule requires at least two such strata, at least two
sessions per stratum and at least 50% of the corresponding dimension's origins.
The numerical rule was operationalized after development and before holdout;
it is therefore disclosed as an operational rule, not represented as
pre-development knowledge.

## Findings

- B1a-to-B2 is positive in 11/12 strata for HAR-RV and Ridge, with 10/12
  intervals entirely above zero and no material-negative stratum.
- Gamma GLM is positive in 11/12 B1a-to-B2 strata, with 7/12 intervals above
  zero and no material-negative stratum.
- LightGBM is positive in 8/12 B1a-to-B2 strata, but has material-negative
  strata for META and the low-volatility regime.
- Persistence produces the expected zero contrast because the information-set
  expansion is not consumed by that baseline.
- B0-to-B1a is weaker and heterogeneous; Gamma GLM has a material-negative
  AMZN stratum, while LightGBM has material-negative AAPL and NVDA strata.

These are development descriptions only. Gamma GLM remains the confirmatory
role and LightGBM the robustness challenger; HAR-RV and Ridge remain
diagnostic comparators until the independent replication is available.

## Reproducibility

The source is
`artifacts/methodology/development_stability_v2.parquet`, SHA-256
`E641293F3CF6BA689E7A6A719F389A5B01CFA1C78C64AC9160FB6EB8113698F9`.
The machine-readable summary is
`artifacts/methodology/development_stability_summary_v2.json`.
The independent evaluation ledger remains at zero reads.
