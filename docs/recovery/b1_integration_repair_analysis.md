# B1Q integration repair analysis

Status: `REPAIR_ACCEPTED_FOR_DATA_ENGINEERING; TWENTY_SESSION_DOWNLOAD_BLOCKED`

Spec Kit rerun: `clarify PASS`, `plan PASS`, `checklist PASS`, `tasks PASS`,
`analyze PASS_WITH_RESEARCH_GATE`; 57 FR identifiers, 24 SC identifiers and
115 task items are structurally present. No constitution conflict was found.

## Root cause

The broad Massive contract request was paginated by the provider's near-term
ordering. The bounded page budget therefore returned short-dated contracts for
some assets but did not reach medium/long expiries. The previous matrix then
reported `INVALID_DTE` for exactly 1,420 of 2,840 origins. The controlled trace
used direct near-ATM contracts and therefore did not exercise the same contract
selection path. A second independent defect computed `b1c_complete` as ATM IV
AND term structure, omitting skew.

## Repair

Contract resolution is now bucket-scoped (7–21, 30–60 and 90–180 DTE), uses the
historical `as_of` date, bounded moneyness filters, pagination per bucket and
explicit cache identities. The full matrix was recomputed for all 2,840 origins.

## Evidence

- `INVALID_DTE` rows after repair: 0.
- B1Q global coverage: B1a 90.25%, B1b 52.36%, B1c 49.19%.
- All nested invariants pass globally and by asset/date/session segment.
- Controlled/full reconciliation is retained in
  `artifacts/b1_repair/controlled_vs_pipeline_diff.csv`; the four selected
  controlled contracts now reconcile exactly with the full matrix (`none` as
  first divergent stage).
- Active cache keys are unique; 199 legacy cache files lack the new explicit
  key and are retained as historical evidence.

## Gate

The repaired B1a coverage and first/middle/last session coverage satisfy the
provisional numeric gates for seven assets. Literature rows without captured
page/section/table coordinates are explicitly restricted to
`EXCLUDE_FROM_ARGUMENT`, so they cannot support strong claims. The 20-session
download remains blocked pending human approval.
