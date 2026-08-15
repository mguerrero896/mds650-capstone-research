# B1 Diagnostic and Independent Replication Contract

## Scope

This contract governs a development-only diagnosis of the B1v3 information set and one new
sign-agnostic temporal replication of the incremental B2 contrast. It does not alter sealed
results, change RV30, add a model family, or authorize a trading/P&L claim.

## Frozen samples

- Training/diagnostic block: exactly 60 ordered XNYS sessions from `2024-09-16` through
  `2024-12-09`.
- Replication block: exactly the 30 ordered XNYS sessions listed in FR-103, from `2024-12-10`
  through `2025-01-24`.
- The replication block must be disjoint from training and every date appearing in a prior
  prediction, loss, OOS read or reported scientific result.
- This is an explicit replication-only amendment to the default study window because no pristine
  30-session interval remains inside the earlier window. Provider preflight must pass the exact
  amended dates; silent substitution is forbidden.

## Diagnostic boundary

The B1 diagnostic may read registered rolling-training outcomes and pre-existing exposed
development evidence. It must not read any replication RV30, QLIKE, prediction or loss. It must
retain all seven registered diagnostic families, bind inputs/code/design by SHA-256, emit a
reason-code waterfall whose terminal counts equal the eligible origins, and use non-causal
language.

## Target-blind predictor boundary

The predictor panel may contain only identity/timing columns and the frozen B0, B1v3 and B2
predictor fields. It must reject target/result-like fields, duplicate origins, post-origin
timestamps, unbound source hashes and unavailable B2 windows encoded as genuine zeroes. FMP,
UW and Massive semantics remain the registered research assumptions in FR-104.

## Preregistration boundary

Before the first replication-target read, self-hashed artifacts must bind:

1. exact 60/30 session arrays and exposure inventory;
2. exact six-asset common-origin universe;
3. B0, B1v3a and B2 column lists;
4. Gamma GLM confirmatory and fixed LightGBM robustness contracts;
5. QLIKE, descriptive MAE/RMSE, signed B1v3/B2 contrasts;
6. 10,000 whole-session paired bootstrap draws, Holm adjustment and seed 650;
7. training-only MDE and all timing/stability variants;
8. code, schema, panel and target identities;
9. an access ledger with `replication_target_reads=0`.

## One-read transition

The access token may transition from zero to one only after schema, hash, PIT, leakage,
common-origin, coverage, deterministic-replay, storage and quality gates pass. A pre-read failure
does not consume the token. After consumption, a second analytical target read, refit, method
change or sign-based retry is forbidden.

## Result contract

Both models and both registered contrasts must be reported with estimate, interval, raw and
Holm-adjusted p-value, training-only MDE comparison and stability/timing ledgers. The terminal
status is exactly one of:

- `REPLICATED_MODEL_INDEPENDENT`;
- `REPLICATED_GAMMA_ONLY`;
- `NOT_REPLICATED`;
- `INVALID_REPLICATION`.

All signs are retained. Gamma-only support cannot be called model-independent. No result implies
causality, informed trader intention, executable profitability or trading readiness.
