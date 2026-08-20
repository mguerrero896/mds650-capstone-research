# RP2-v3 research contract

Frozen before any RP2-v3 code moved. Everything below is decided in advance and is not
revisable by a later gate; a gate that wants a different target, loss, model family or
comparison direction is a different research programme and needs its own contract.

## Frozen specification

```text
Primary target: RV30
Primary comparisons:
    B0 vs B0+B1
    B0+B1 vs B0+B1+B2
Primary loss:
    QLIKE
Primary models:
    gamma_glm
    ridge_log
    lightgbm_qlike
Inference unit:
    Trading session
Primary B1:
    Contemporaneous option-state snapshot
Primary B2:
    Point-in-time option-flow activity
No sealed confirmation cohort may be read during development.
```

## Sign convention

The two quantities the programme reports are differences in loss, so a positive value
means the larger information set predicted better:

```text
delta_B1 = L(B0) - L(B0+B1)
delta_B2|B1 = L(B0+B1) - L(B0+B1+B2)
```

The stated objective, fixed here and not after the numbers arrive, is:

```text
delta_B1 > 0   and   delta_B2|B1 > 0
```

A null or a negative delta is reported as measured. No model family, feature, horizon or
threshold may be added to move a delta toward the expected sign; the four outcomes of the
master plan's section 21 (A, B, C, D) are all publishable results.

## Comparison discipline

Comparisons are *family-matched* and *nested*: a model family is compared against itself
across information sets, never against a different family across information sets.

```text
gamma_glm      B0    vs gamma_glm      B0+B1    gamma_glm      B0+B1 vs gamma_glm      B0+B1+B2
ridge_log      B0    vs ridge_log      B0+B1    ridge_log      B0+B1 vs ridge_log      B0+B1+B2
lightgbm_qlike B0    vs lightgbm_qlike B0+B1    lightgbm_qlike B0+B1 vs lightgbm_qlike B0+B1+B2

The identifiers are the registry keys of `mds650.rp2.ladder.PRIMARY_MODELS`; the producer
refuses to write a ladder artifact that omits one of them. `lightgbm` (log-MSE) remains in
the ladder as robustness and is not a deciding family: it and `lightgbm_qlike` are the same
independent family, so they are never counted as two pieces of evidence.
```

Every nested pair is evaluated on exactly one common row mask, recorded as
`common_mask_sha256`. A base model may not be scored on rows the expanded model dropped.

## Inference unit

Inference is performed on one observation per trading session: losses are averaged within
a session first, and the session series is what the bootstrap, the Newey–West estimator and
the SPA test see. An early-close session carries the same weight as a full one.

## Sealed cohorts

`sealed_cohorts_read = 0`. Cohort C, Phase 8 and Phase 9 are not read during RP2-v3
development — not for a result, not for a diagnostic, not to inspect their size. The
prospective confirmation described in the master plan's section 22 begins only after this
contract, the feature registry, the models, the preprocessing, the cutoff, the universe,
the inference and the MDE are all frozen and hashed.

## Related documents

- [`RP2_V3_MASTER_PLAN.md`](RP2_V3_MASTER_PLAN.md) — the binding plan this contract serves.
- [`IMPLEMENTATION_STATUS.md`](IMPLEMENTATION_STATUS.md) — per-gate progress.
- [`SCORECARD_SCHEMA.md`](SCORECARD_SCHEMA.md) — what every rebuild must report.
- [`SUPERSEDED_RESULTS.md`](SUPERSEDED_RESULTS.md) — what RP2-v3 supersedes, and how.
