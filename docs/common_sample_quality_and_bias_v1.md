# Common-sample quality and selection-bias audit v1

Evidence: `artifacts/audits/common_sample_quality_v1.json` and
`artifacts/audits/selection_bias_audit_v1.csv`. All comparisons are descriptive;
there are no p-values or causal claims.

## Retention

| Quantity | Rows |
|---|---:|
| Nominal origins | 14,200 |
| B0/RV30 availability-aware | 13,240 (93.24% of nominal) |
| Strict B0+B1Q+B2 | 9,589 (67.53% of nominal; 72.42% of availability-aware) |
| Duplicate canonical IDs | 0 |
| Post-origin B0 predictors | 0 |
| Post-origin Massive quotes | 0 |
| UW primary recheck failures | 0 of 13,240 |

Strict exclusions are 960 B0/target structural rows, 1,088 B1Q quote/IV quality
rows and 2,563 B2 rows whose mandatory continuous field is missing (principally
within-bin IV change in the five pilot sessions). This is an explicit missingness
outcome, not a zero fill.

## Concentration and missingness

Strict rows by asset: AAPL 1,300; AMZN 1,299; META 1,300; MSFT 1,298; NVDA
1,300; QQQ 1,042; SPY 750; TSLA 1,300. By session tercile, strict rows are
2,534 first, 3,889 middle and 3,166 last. B1Q coverage in the availability-aware
view is 56.68% for SPY, 81.39% for QQQ and at least 98.01% for the other six
assets. It is lower at the first tercile (81.96%) than the middle (93.77%) or
last tercile (99.13%).

The missingness profile is machine-readable in the quality JSON. Notable fields
are B1Q skew missing in 5,539 rows, B1Q ATM IV missing in 1,088 rows and
B2 within-bin IV change missing in 2,840 rows. The last field is not imputed;
it explains the pilot strict exclusion.

## Descriptive selection-bias diagnosis

The audit compares strict-retained and B1Q-excluded rows by asset and time of
day using RV30 mean/median, lagged volume, origin minute, quote age and spread.
For example, retained opening rows have median RV30 approximately `2.2e-5`
versus `1.5e-5` in B1Q-excluded opening rows; retained SPY rows are 750 versus
905 excluded rows, while TSLA retains 1,300 versus 355 excluded. These are
descriptive distribution differences, not evidence that quote availability causes
volatility.

The strict sample is visibly concentrated toward liquid assets and later session
origins. The purposive eight-asset universe has survivorship and liquidity bias;
it must not be generalized to all US equities. No predictive result was used to
select assets.

## Quality gate

Status: **PARTIAL**. Lineage, deduplication, missingness and descriptive bias
checks pass locally. A final scientific sample remains blocked by provider
semantics, daily continuity and the absence of a frozen temporal evaluation.
