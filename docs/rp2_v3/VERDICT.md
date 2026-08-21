# The section 21 gate: Result C

Measured on `rp2-v3-20260821-134741`, published to Supabase, scientific hash
`fdce125264082af5` at commit `08a4a06448c9`. D 389 sessions, V 80. Every number here is read
from `artifacts/rp2_v3/rp2-v3-20260821-134741/scorecard.json` and from
`api.current_rp2_contrasts`; none is carried over from an earlier run.

## The twelve contrasts

A positive delta is an improvement in QLIKE: the smaller information set's loss minus the
larger one's.

| Family | Role | Contrast | Δ | 95% CI | Contains 0 |
| --- | --- | --- | ---: | ---: | :---: |
| `gamma_glm` | D | ΔB1 | +0.00408 | [+0.00231, +0.00584] | no |
| `gamma_glm` | D | ΔB2\|B1 | −0.02549 | [−0.07571, +0.00057] | yes |
| `gamma_glm` | V | ΔB1 | −0.00111 | [−0.00408, +0.00202] | yes |
| `gamma_glm` | V | ΔB2\|B1 | −0.00222 | [−0.00458, −0.00032] | **no** |
| `ridge_log` | D | ΔB1 | +0.00424 | [+0.00259, +0.00606] | no |
| `ridge_log` | D | ΔB2\|B1 | −0.15509 | [−0.45513, +0.00116] | yes |
| `ridge_log` | V | ΔB1 | −0.00084 | [−0.00283, +0.00128] | yes |
| `ridge_log` | V | ΔB2\|B1 | −0.00195 | [−0.00507, +0.00020] | yes |
| `lightgbm_qlike` | D | ΔB1 | +0.00381 | [+0.00126, +0.00690] | no |
| `lightgbm_qlike` | D | ΔB2\|B1 | +0.00065 | [−0.00051, +0.00190] | yes |
| `lightgbm_qlike` | V | ΔB1 | +0.00092 | [−0.01081, +0.01292] | yes |
| `lightgbm_qlike` | V | ΔB2\|B1 | −0.00051 | [−0.00619, +0.00491] | yes |

Five of twelve deltas are positive. Eight of twelve intervals contain zero.

## Why this is Result C and not A, B or D

**Not A.** A requires ΔB1 > 0 *and* ΔB2\|B1 > 0, in D *and* in V. ΔB1 is negative in V for
`gamma_glm` and `ridge_log`, and ΔB2\|B1 is negative in four of the six family-role pairs.

**Not B.** B requires ΔB1 > 0 with ΔB2\|B1 ≈ 0. ΔB1 is not positive in validation for two of
the three families, so the premise fails before the B2 question is reached.

**Not D.** D is for effects that are positive with intervals containing zero — an
underpowered sample rather than an absent effect. The effects are not positive: `gamma_glm`
in V has ΔB2\|B1 = −0.00222 with the interval **[−0.00458, −0.00032] excluding zero**. That is
a measured deterioration, not a null.

**C.** The plan's Result C is *ΔB1 < 0 even with a contemporaneous B1 and high coverage*. That
is what validation shows: ΔB1 is −0.00111 for `gamma_glm` and −0.00084 for `ridge_log`, and
the B1 those numbers were measured on is contemporaneous with a core coverage of **0.9934**, a
median quote age of **579 s**, a 95th percentile of **1724 s** against a 1800 s cutoff, and
**zero** post-cutoff observations. The representation is not the explanation.

> **Interpretation, as the plan words it:** B1 does not contribute contemporaneous
> forecastability for RV30 under this representation.

`lightgbm_qlike` is the exception worth stating rather than burying: its ΔB1 is positive in
both roles, +0.00381 in D and +0.00092 in V, though the validation interval spans zero. One
family of three, on 32 evaluation sessions, is not a result — it is where a future
prospective test would aim.

## What was corrected on the way here, and what it did not change

The rebuild replaced a reported latency tail that was a median across windows of each
window's own 95th percentile — not a quantile of any population. Measured over all
580,549,989 trades, the record lag is `p50 0.067 s, p90 0.137 s, p95 0.280 s, p99 4.877 s`.
Against the previous run, **5 of 162 scorecard fields moved**: that tail, the commit, and the
three digests that depend on the new column. Every scientific number is identical, which is
the determinism the runner exists to provide.

## What this verdict does not claim

- No sealed cohort was read. C, Phase 8 and Phase 9 stay closed; `sealed_cohorts_read = 0`.
- No confirmation claim is made. This is development and validation, not the sealed cohort.
- No economic claim is made. Block 11 is frozen and was not rebuilt.
- The study window is the frozen partition, by recorded configuration change (decision 84).
