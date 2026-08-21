# The section 21 gate: Result C

Measured on `rp2-v3-20260822-054000`, scientific hash `07456efcd4bce4ec` at commit
`7225fdfaa7d7`. D 389 sessions, V 80. Every number here is read from
`artifacts/rp2_v3/rp2-v3-20260822-054000/scorecard.json` and from that run's
`rp2_block10_inference/inference.json`; none is carried over from an earlier run. The tables
below are emitted by `scripts/rp2_verdict_tables.py` rather than transcribed, and
`tests/contract/test_verdict_matches_artifact.py` checks every figure on this page against
the run it names.

This run supersedes `rp2-v3-20260821-134741`, which measured a baseline built on a
fabricated range and volume. **The refutation that page claimed is withdrawn.** What changed
and why is in the last two sections; `docs/rp2_v3/SUPERSEDED_RESULTS.md` carries the record.

## The twelve contrasts

A positive delta is an improvement in QLIKE: the smaller information set's loss minus the
larger one's.

| Family | Role | Contrast | Δ | 95% CI | Contains 0 |
| --- | --- | --- | ---: | ---: | :---: |
| `gamma_glm` | D | ΔB1 | +0.00234 | [+0.00113, +0.00358] | no |
| `gamma_glm` | D | ΔB2\|B1 | −0.00506 | [−0.01508, +0.00026] | yes |
| `gamma_glm` | V | ΔB1 | −0.00111 | [−0.00408, +0.00202] | yes |
| `gamma_glm` | V | ΔB2\|B1 | −0.00222 | [−0.00458, −0.00032] | **no** |
| `ridge_log` | D | ΔB1 | +0.00250 | [+0.00144, +0.00372] | no |
| `ridge_log` | D | ΔB2\|B1 | −0.01451 | [−0.04327, +0.00036] | yes |
| `ridge_log` | V | ΔB1 | −0.00084 | [−0.00283, +0.00128] | yes |
| `ridge_log` | V | ΔB2\|B1 | −0.00195 | [−0.00507, +0.00020] | yes |
| `lightgbm_qlike` | D | ΔB1 | +0.00314 | [+0.00071, +0.00606] | no |
| `lightgbm_qlike` | D | ΔB2\|B1 | +0.00113 | [+0.00042, +0.00188] | no |
| `lightgbm_qlike` | V | ΔB1 | +0.00092 | [−0.01081, +0.01292] | yes |
| `lightgbm_qlike` | V | ΔB2\|B1 | −0.00051 | [−0.00619, +0.00491] | yes |

Five of twelve deltas are positive. Seven of twelve intervals contain zero.

## Why this is Result C and not A, B or D

**Not A.** A requires ΔB1 > 0 *and* ΔB2\|B1 > 0, in D *and* in V. ΔB1 is negative in V for
`gamma_glm` and `ridge_log`, and ΔB2\|B1 is negative in five of the six family-role pairs.

**Not B.** B requires ΔB1 > 0 with ΔB2\|B1 ≈ 0. ΔB1 is not positive in validation for two of
the three families, so the premise fails before the B2 question is reached.

**Not D, on one ground rather than two.** D is for effects that are positive with intervals
containing zero — an underpowered sample rather than an absent effect. In validation the
effects are not positive: `gamma_glm` has ΔB2\|B1 = −0.00222 with the interval **[−0.00458,
−0.00032] excluding zero**, a measured deterioration rather than a null. That ground stands,
and it is now the only one: the previous version of this page also argued that `ridge_log`
refuted on adequate power, and it does not — see the power section below.

That interval carries a caveat this page should state rather than let a reader assume. Its
empirical coverage, measured by resampling blocks from the centred series and running the
production bootstrap, is **0.784** against a nominal 0.95, so it excludes zero more readily
than 95 % suggests. The finding survives in sign; its confidence does not read as stated.

**C.** The plan's Result C is *ΔB1 < 0 even with a contemporaneous B1 and high coverage*. That
is what validation measures: ΔB1 is −0.00111 for `gamma_glm` and −0.00084 for `ridge_log`, and
the B1 those numbers were measured on is contemporaneous with a core coverage of **0.9934**, a
pooled median quote age of **450 s**, a pooled 95th percentile of **1350 s** against a 1800 s
cutoff, and **zero** post-cutoff observations. The representation is not the explanation.

> **Interpretation.** The plan words Result C as *B1 does not contribute contemporaneous
> forecastability for RV30 under this representation*. The measurements support only the
> weaker statement: **the development-sample B1 effect is not reproduced out of sample.**
> They do not support the stronger one this page previously made. No family was powered to
> detect a development-sized effect in validation, so every validation null here is absence
> of evidence, not evidence of absence.

`lightgbm_qlike` is the exception worth stating rather than burying: its ΔB1 is positive in
both roles, +0.00314 in D and +0.00092 in V, though the validation interval spans zero. Its
development ΔB2\|B1 is now **+0.00113 [+0.00042, +0.00188], excluding zero** — the only
positive B2 increment in the twelve that does. One family of three, on 32 evaluation
sessions, is not a result; it is where a future prospective test would aim.

## What the intervals could have detected, family by family

Seven of twelve intervals contain zero, and that alone does not distinguish "there is no
effect" from "this design could not have seen one". The minimum detectable effect separates
them. The question worth asking is whether validation could have detected an effect the size
of the one development measured:

| Family | Effect in D | MDE in V | Could V have detected it? |
| --- | ---: | ---: | --- |
| `gamma_glm` | +0.00234 | 0.00413 | No — roughly 100 sessions would be needed |
| `ridge_log` | +0.00250 | 0.00268 | Marginally not: ~37 sessions needed, 32 available |
| `lightgbm_qlike` | +0.00314 | 0.01770 | No — roughly 1019 sessions would be needed |

**No family refutes.** All three answer the same question the same way: validation could not
have seen an effect of the size development measured, so its silence carries no information
about that effect.

- **`ridge_log` is the closest and still short.** Its MDE is 1.07 times the effect it would be
  testing. Thirty-seven sessions would decide it; the design has thirty-two.
- **`gamma_glm` needs three times the sample.** MDE 1.77 times the effect.
- **`lightgbm_qlike` was not measurable in validation.** MDE 5.64 times the effect; the
  interval [−0.01081, +0.01292] is wide enough to contain almost any conclusion.

Nine of the twelve contrasts sit below their own minimum detectable effect. Reporting those as
nulls without saying so would state a finding the design could not support.

## What the rebuild corrected, and what it moved

Two of the six bar stores held only `(asset, bar_start_utc, close)`, and both supply
development. The session grid repaired their missing range and volume unconditionally —
`high` and `low` from the close, `volume` from zero — which is right for a minute in which
nothing traded and wrong for a minute that traded and whose range was never recorded. Three
B0 features were therefore exactly zero on **22,967 of 152,954 development origins and on 0
of 31,678 validation origins**; being `log` features, zero became −27.631, and being finite it
recorded no missing indicator. The published ladder showed it in its own standardisation
scales: `dollar_volume_30` at 20.762 in development against 0.692 in validation, where no
honest feature differed between roles by as much as a factor of two.

Repaired by acquiring the data rather than imputing around its absence: the same 360
asset-sessions re-fetched with full OHLCV, 138,239 bars against 138,239, no bar missing, no
bar added, every close identical to the byte. Of those minutes 0.07 % genuinely had no volume
and 0.02 % genuinely had no range, against the 100 % the fabrication asserted.

With a baseline built on real range and volume, the development B1 increment falls by about
two fifths and validation does not move at all — there were no deficient stores there, which
is the control:

| Family | ΔB1 in D, before → after | ΔB1 in V |
| --- | ---: | ---: |
| `gamma_glm` | +0.00408 → **+0.00234** | −0.00111, unchanged |
| `ridge_log` | +0.00424 → **+0.00250** | −0.00084, unchanged |
| `lightgbm_qlike` | +0.00381 → **+0.00314** | +0.00092, unchanged |

Three further corrections landed in the same rebuild. The published loss levels averaged
every evaluated row while the contrasts beside them aggregated to the session, so
`qlike[B0] − qlike[B0+B1]` did not reproduce `delta_b1`; both are session-weighted now. The
B1 quote-age median and tail were a median across origins of each origin's own quantile,
which is not a quantile of any population — they are read off summed histogram bins, which is
why they move from 578.75 s and 1723.92 s to **450 s and 1350 s**. `b2_multileg_share` was an
unweighted mean of per-origin premium shares whose denominators span a factor of fourteen; the
pooled share is 0.23694, not 0.23057.

`b2_p95_provider_latency_s` reads 0.3555 s against the previous 0.2802 s, and that is a
reporting artefact rather than a change in the tape: the two are **adjacent edges of the same
log-spaced bin**, which is 26.9 % wide. A 0.195 % shift in the counted trades crossed the
boundary and the reported figure moved by a full bin. The value is the bin's lower edge, so
the tail is at least 0.3555 s and below 0.4511 s; it is not resolved more finely than that,
and no claim on this page depends on it.

Seventy-four of 162 comparable scorecard fields moved against `rp2-v3-20260821-134741`, which
is what a rebuild carrying four corrections to the science should do. Reproducible here:

```text
uv run python scripts/rp2_v3_scorecard_diff.py \
    --before artifacts/rp2_v3/rp2-v3-20260821-134741/scorecard.json \
    --after  artifacts/rp2_v3/rp2-v3-20260822-054000/scorecard.json --only-moved
```

## What this verdict does not claim

- No sealed cohort was read. C, Phase 8 and Phase 9 stay closed; `sealed_cohorts_read = 0`.
- No confirmation claim is made. This is development and validation, not the sealed cohort.
- No economic claim is made. Block 11 is frozen and was not rebuilt.
- The study window is the frozen partition, by recorded configuration change (decision 84).
- **No family refuted the development effect.** The design could not decide it in validation,
  and a design that cannot decide has not decided.
