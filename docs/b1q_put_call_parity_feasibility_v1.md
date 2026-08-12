# B1Q Put-Call-Parity Feasibility Diagnostic v1

## Purpose

This is a target-free data-geometry diagnostic. It asks whether the existing
Massive B1Q quote-attempt cache has enough same-expiry put-call pairs to
estimate the discount-factor slope implied by put-call parity. It is not an IV
surface, model, performance result, rate/dividend substitute, or method change.

## Input boundary

The diagnostic reads only the following fields from
`D:\MDS650\data\b1q\phase5_missing_55\b1_iv_attempts_20d.parquet`:

`asset`, `session_date`, `origin_id`, `forecast_origin_utc`,
`forecast_origin_ns`, `expiry`, `strike`, `option_type`, `contract`,
`sip_timestamp`, `bid`, `ask`, `quote_age_seconds`, and `relative_spread`.

It does not read RV30, QLIKE, a prediction, an IV inversion result, a rate, a
dividend, a target, a metric, or any holdout input. The report binds the input
by source-file SHA-256 and does not disclose a personal path.

## Rule

For every origin and expiry, a valid quote must satisfy:

- `sip_timestamp <= forecast_origin`;
- `bid > 0` and `ask > bid`;
- `0 <= quote_age_seconds <= 60`;
- `0 <= relative_spread <= 25%`; and
- expiry strictly after the session date.

Identical contract/quote identities repeated by the target grid are removed
once, without changing a quote. A same-strike call/put pair gives
`C(K) - P(K)`, but cannot identify the discount factor alone. Two distinct
strikes at the same expiry are required; the diagnostic then checks whether

`D = ((C(K_low)-P(K_low)) - (C(K_high)-P(K_high))) / (K_high-K_low)`

is finite and within `(0, 1.1]`. This is only a feasibility signal, not an
approved production estimator.

## Recorded result

The immutable report is
`artifacts/corrected_development_v1/b1q_put_call_parity_feasibility_v1.json`.
Its semantic hash is
`sha256:a801672670218ae54fe805cdaed977820d4230bc5896f5fd2764ec0174215661`
and its byte hash is
`d31e5a74df9d9176dbd786b6cb3380f8df79bf03440ffd1e2cfe96b969fc07a2`.
The writer validates its Draft 2020-12 schema, semantic self-hash and
secret/personal-path hygiene before both the initial write and an identical
replay; a different valid report at the same path fails closed.

It reports 249,920 source rows and 31,240 origins. Of 207,064 valid quote
rows before deterministic deduplication, 104 duplicated contract/quote records
were dropped, leaving 206,960. There were 72,813 same-strike call/put pairs and
27,199 origins (87.06%) with at least one pair. There were zero origin-expiry
groups with two paired strikes and hence zero valid discount estimates.

The status is `INFEASIBLE_WITH_CURRENT_CONTRACT_GRID`.

## Consequence

The diagnostic cannot resolve
`B1Q_EXOGENOUS_INPUT_PROVENANCE_UNRESOLVED`. It leaves
`SAFE_TO_RECONCILE_EXISTING_RESULTS=NO` and
`SAFE_TO_OPEN_OR_EVALUATE_OOS=NO`. The correct path remains reviewable,
timestamped, raw-payload evidence for FMP Treasury/dividend inputs, not an
undocumented mathematical proxy.
