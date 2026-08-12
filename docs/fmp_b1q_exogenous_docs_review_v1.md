# FMP B1Q exogenous-input documentation review v1

## Result

The official FMP pages document a Treasury-rates endpoint described as serving
latest and historical rates, and a dividends endpoint that exposes a
declaration-date field. The FMP cycle-times page labels Treasury Rates as
two-hour data and Dividends Company as one-to-two-hour data.

This is useful endpoint documentation, but it is not point-in-time provenance
for the B1Q inputs. None of the reviewed pages specifies the original
observation-date semantics for a Treasury record, when a historical value first
became visible to an FMP customer, or how later revisions/backfills can be
identified. Likewise, a dividend declaration-date field does not establish the
customer-visible time for that record or its historical revision behavior.

Therefore the immutable review remains:

```text
B1Q_EXOGENOUS_INPUT_PROVENANCE = UNRESOLVED
SAFE_TO_BUILD_B1Q = false
SAFE_TO_RECONCILE_EXISTING_RESULTS = NO
SAFE_TO_OPEN_OR_EVALUATE_OOS = NO
```

## What the review does and does not establish

| Input | Official documentation supports | It does not support |
| --- | --- | --- |
| Treasury rates | Endpoint existence, historical scope, nominal two-hour cycle | Original observation/publication/customer-visible time and revision history |
| Dividends | Symbol endpoint, declaration-date field, nominal one-to-two-hour cycle | Customer-visible time, historical revision/backfill behavior, a pre-origin dividend yield |

The same conservative rule applies to each origin: a future source build needs
a sanitized raw-payload hash and evidence-availability timestamp at or before
that origin. It cannot substitute same-session, carried-forward, or assumed
values merely because the endpoint has historical coverage.

## Sources reviewed

- [FMP Treasury Rates API](https://site.financialmodelingprep.com/developer/docs/stable/treasury-rates)
- [FMP Dividends Company API](https://site.financialmodelingprep.com/developer/docs/historical-stock-dividends-api/)
- [FMP Cycle Times](https://site.financialmodelingprep.com/developer/docs/cycle-times-stable)

## Reproducibility

```powershell
uv run --offline python scripts/build_fmp_b1q_exogenous_docs_review_v1.py
uv run --offline pytest -q tests/unit/test_fmp_b1q_exogenous_docs_review_v1.py
```

The review makes no provider call, reads no target/RV30/metric/prediction/OOS
artifact, and does not replace the independent support-evidence intake.
