# B1Q zero-coverage forensic diagnosis

Status: `B1Q_ZERO_COVERAGE_REQUIRES_REVIEW`. This document does not authorize
asset removal, models or the twenty-session download.

## Verified evidence

The full B1Q matrix reports zero nested B1a coverage for SPY, QQQ, META and
TSLA. A separate controlled trace used 12 origins (opening, midday and closing
on 2026-07-13) and 72 near-ATM contract cases. Requests used `as_of`, OCC-style
tickers and local `sip_timestamp <= origin` selection. No future quote was
accepted. The trace is preserved in
`artifacts/b1_forensic/zero_coverage_controlled.json`.

| asset | observed controlled result | current interpretation |
|---|---|---|
| SPY | concentrated `NO_QUOTE_BEFORE_ORIGIN` cases | historical contract/quote coverage issue remains unresolved; ETF root and distributions require review |
| QQQ | zero B1Q in the full matrix; diagnostic trace retained | ETF root, weekly/monthly expiry and distribution handling require review |
| META | controlled quotes and IV attempts observed, but full matrix B1Q remains zero | inconsistent contract-day selection/caching or historical quote coverage requires review; not attributable to missing dividends alone |
| TSLA | controlled quotes/IV attempts observed with one no-quote case, but full matrix B1Q remains zero | contract selection or matrix integration defect is more plausible than dividend absence alone |

## Required follow-up

1. Compare the controlled contract set with the full-matrix contract-day
   selection for the same asset-date.
2. Check weekly/monthly expiry, root symbol, strike scaling and `as_of`
   pagination separately for ETFs.
3. Keep q=0 only as a documented sensitivity for META/TSLA when no prior
   dividend is known; missing dividend data MUST NOT zero an asset.
4. Re-run the matrix only after the controlled/full-selection discrepancy is
   resolved and covered by a regression test.
