# Level 4, preregistered before anything is fitted

RP2-v3 closed with Result C: the development-sample B1 effect does not survive out of sample
where the design could test it. This document is written **before** any level-4 model is
trained, because a sequence family introduced after seeing that result and evaluated on the
same data is a search, not a test.

## What is being asked

`lightgbm_qlike` is the only family whose ΔB1 is positive in both roles (+0.00381 in D,
+0.00092 in V), while the two linear families lose it in validation. If the option-state
signal exists and is non-linear, a model that reads the trade sequence directly should
recover more of it than one reading the tabular summary of that sequence.

**The question:** does a DeepSets encoder over the raw trade sequence improve QLIKE over the
identical network without the sequence branch?

## What is frozen before fitting

| Item | Value |
| --- | --- |
| Role evaluated | **D only**. V is not touched |
| Sealed cohorts | not read; `sealed_cohorts_read = 0` |
| Sequence | the last 48 trades before the availability cutoff |
| Control | the same network, sequence branch removed, same seed, schedule, batches and data |
| Loss | QLIKE, the same the ladder decides on |
| Split | the frozen chronological train share, no re-tuning |
| Seed | 20260819 |
| Epochs | 30, fixed |
| Inference | session-level, circular block bootstrap, block 5, as `mds650.rp2.inference` |
| Success | ΔQLIKE > 0 against **both** references below, each with a 95 % session-level interval excluding zero |

### Two references, not one

The control must be beaten *and* the model already in production must be beaten. The reason
is measured rather than hypothetical: the level-4 run of 2026-08-18 reported
`delta_sequence_over_tabular = +0.634, p = 0.004` in development, and the numbers behind it
were

```text
control MLP tabular      QLIKE 0.7834
DeepSets sequence        QLIKE 0.1496
lightgbm_qlike reference QLIKE 0.1374   <- better than the sequence model
```

The control was five times worse than the tabular LightGBM fitted on the same features, so
beating it measured the control's weakness. The sequence model lost to the model already in
the ladder, and the reported improvement was significant at p = 0.004 regardless.

A single reference cannot distinguish "the sequence helps" from "our control is bad". Two
can:

| Reference | What it isolates |
| --- | --- |
| The same network with the sequence branch removed | whether the sequence contributes, holding architecture fixed |
| `lightgbm_qlike` from the frozen ladder | whether the whole approach beats what already exists |

Failing the second is a result and is reported as one: a sequence model that loses to a
gradient-boosted tree on the same information has not found a non-linear signal, it has found
a harder optimisation problem.

## Why validation is not used

V holds 80 sessions, 32 of them evaluated. Its minimum detectable effect for ΔB1 is 0.0027
to 0.0177 depending on family, against effects of about 0.004. It is the only untouched
comparison the programme has left, and spending it on an exploratory family would leave
nothing to confirm a hypothesis with.

If level 4 finds something in D, V is still available to test it. If level 4 is evaluated in
V now, whatever it finds cannot be confirmed by anything.

## What this result may and may not be called

- It **may** be called exploratory evidence about representation.
- It **may not** be called confirmation, and no artifact it produces carries a confirmatory
  label.
- A positive result is a hypothesis for the prospective cohort of section 22, not a finding.
- A negative result is reported exactly as measured, with its minimum detectable effect
  beside it.

## What would make this preregistration void

Changing any frozen item above after seeing a fitted number. If a change is necessary, it is
recorded as a new preregistration with its reason, and the superseded one stays.
