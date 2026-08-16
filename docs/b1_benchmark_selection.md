# B1 benchmark selection after forensic validation

## Decision

`REVISE_B1_AGAIN` remains the current decision. B1Q Massive is the only route
eligible to become the primary ordinary-option-state benchmark because it is
independent of trade occurrence, but its corrected nested B1a coverage is
46.55%, below the 70% gate. B1T reaches 100% in the pilot but shares Full Tape
provenance with B2 and remains diagnostic-only.

## Corrected definitions

- `atm_iv_available`: ATM IV component exists at the origin.
- `skew_available`: the comparable OTM put/call skew component exists.
- `term_structure_available`: at least two valid DTE buckets exist.
- `b1a_complete = atm_iv_available`.
- `b1b_complete = atm_iv_available AND skew_available`.
- `b1c_complete = atm_iv_available AND skew_available AND term_structure_available`.

## Corrected B1Q coverage

| component/benchmark | coverage |
|---|---:|
| ATM IV component | 46.55% |
| skew component | 22.85% |
| term-structure component | 44.01% |
| nested B1a | 46.55% |
| nested B1b | 22.85% |
| nested B1c | 21.69% |

The previous 44.01% B1c value was an aggregation defect: it counted term
structure without requiring ATM IV and skew. The corrected nested values are
monotone and are validated globally, by asset, date, session segment and route.

No component is imputed to force coverage, and no predictive result is used in
this decision.
