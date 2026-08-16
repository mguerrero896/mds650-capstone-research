# Target horizon decision

Status: `PASS_RV30_APPROVED_BY_OWNER`

## Decision

The supervisor-approved repository specification is unambiguous: the primary target is
RV30. The frozen contract is the origin close `C(i,t)` plus the next thirty consecutive
one-minute closes, requiring 31 prices and producing exactly 30 one-minute log returns.
The target implementation remains unchanged and RV10 is not introduced.

## Evidence hierarchy

1. `specs/001-pit-options-rv30/spec.md`, FR-011 and the 2026-07-22 clarification, define
   RV30 as the only primary target.
2. `docs/methodology_decisions.md`, decision 1, repeats the same formula and 31-price
   requirement.
3. `specs/001-pit-options-rv30/contracts/pilot-dataset-contract.md` and
   `contracts/benchmark-evaluation-contract.md` require the same RV30 contract.
4. `src/mds650/targets.py` rejects any future-close count other than 30.
5. `tests/unit/test_target.py` and `tests/unit/test_contracts.py` verify 31 prices and
   30 returns.

## Presentation discrepancy and owner decision

The oral presentation reportedly mentioned ten minutes, but the presentation file is
not present in this repository. On 2026-07-22 the project owner explicitly approved
RV30 as the official horizon and did not authorize introducing RV10. That decision is
the controlling human reconciliation for this run; the repository target contract and
implementation remain unchanged.

## Gate result

- `repository_target_contract`: `PASS_RV30_FROZEN`
- `presentation_alignment`: `PASS_HUMAN_APPROVED`
- `target_code_modified`: `false`
- `rv10_introduced`: `false`
- `modeling_or_backfill_authorized`: `false`

The target-horizon gate is closed for RV30. This decision does not authorize model
training, backfill, QLIKE, tuning, final testing, asset freezing or publication; the
remaining provider PIT gates still control those actions.
