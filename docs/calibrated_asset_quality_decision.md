# Calibrated asset-quality decision

Status: `PROVISIONAL_20_SESSION_EVIDENCE_COMPLETE_FINAL_FREEZE_BLOCKED`

This document will be populated after the authorized twenty-session B1Q/B2 run. Roles are
chosen only from data-quality and point-in-time evidence:

- target candidates: AAPL, AMZN, META, MSFT and TSLA;
- market controls: SPY and QQQ;
- diagnostic candidate: NVDA unless it meets every target-quality gate.

The target-quality gate used here requires B1a coverage of at least 70%, at least 40% in every
session tercile, IV inversion success of at least 80%, complete FMP and Full Tape coverage,
valid Massive PIT quotes, no integration discrepancy and stable missingness. The twenty-session
run produced the following data-only evidence (B1Q, primary quote age <=60 seconds and relative
spread <=25%):

| asset | B1a | B1b | B1c | IV success | minimum B1a tercile | provisional role |
|---|---:|---:|---:|---:|---:|---|
| AAPL | 100.00% | 64.08% | 22.61% | 98.00% | 100.00% | target candidate |
| AMZN | 99.93% | 68.80% | 24.01% | 97.37% | 99.75% | target candidate |
| META | 100.00% | 75.85% | 18.73% | 98.57% | 100.00% | target candidate |
| MSFT | 99.86% | 72.04% | 25.77% | 94.55% | 99.62% | target candidate |
| NVDA | 99.51% | 54.86% | 16.55% | 93.67% | 98.60% | eligible target candidate; formerly diagnostic |
| TSLA | 100.00% | 50.63% | 12.68% | 95.21% | 100.00% | target candidate |
| QQQ | 76.34% | 59.30% | 17.32% | 59.17% | 49.60% | market control, B0 only |
| SPY | 53.45% | 34.01% | 12.82% | 44.50% | 11.40% | market control, B0 only |

FMP returned 390 exact-session bars for all 160 asset-session requests; local filtering isolated
the requested date even when the provider over-returned adjacent dates. Full Tape and Massive
routes completed without a schema or PIT assertion failure. QQQ and SPY remain valid B0 controls,
but their B1 coverage is not sufficient for an options-state benchmark under this gate. NVDA
meets the numerical gates and may be promoted from diagnostic status in a later recorded freeze.

No RV30, QLIKE, correlation, feature importance or predictive result changes a role in this
phase. This is a provisional quality recommendation only; the final universe remains unfrozen
and a method-freeze decision is still required.
