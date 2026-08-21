# RP2-v3 implementation status

One row per gate of the master plan's section 24, in its binding order. A gate is `merged`
only when its own PR carried failing-first tests, the minimal fix, measured before/after
metrics, green `quality` and `hermetic` checks, the local evidence gates, and a review on
its final commit.

| # | Branch | Gate | Status |
| ---: | --- | --- | --- |
| 1 | `docs/rp2-v3-contract` | Freeze the research contract | merged |
| 2 | `fix/rp2-v3-panel-contracts` | Information sets fail closed | merged |
| 3 | `fix/rp2-v3-causal-b0` | Causal, asset-local EWMA baseline | merged |
| 4 | `feat/rp2-v3-contemporaneous-b1` | B1 as contemporaneous option state | merged |
| 5 | `fix/rp2-v3-exact-clock-b2` | B2 dual clocks, exact expiry, 0DTE | merged |
| 6 | `feat/rp2-v3-core-feature-registry` | Core versus rich feature sets | merged |
| 7 | `feat/rp2-v3-fold-local-preprocessing` | Fold-local imputation, common mask | merged |
| 8 | `feat/rp2-v3-qlike-models` | LightGBM aligned to QLIKE | merged |
| 9 | `fix/rp2-v3-session-inference` | Session-level, family-matched inference | merged |
| 10 | `feat/rp2-v3-pipeline-runner` | One reproducible runner | merged |
| 11 | `db/rp2-v3-versioned-results` | Versioned Supabase results | merged |
| 12 | `results/rp2-v3-rebuild` | Rebuild, scorecard, publication | rebuilt and published |

## The result

`rp2-v3-20260821-134741`, thirteen steps, every exit code zero, scientific hash
`fdce125264082af5` at commit `08a4a06448c9`, published to Supabase and readable through
`api.current_rp2_contrasts`. The section 21 gate returns **Result C**; the reasoning and the
twelve contrasts are in [`VERDICT.md`](VERDICT.md).

## Settled decision

The two study windows the repository stated are reconciled. Methodology decision 84, dated
2026-08-21, is the recorded configuration change `AGENTS.md` required: the RP2 study window
is the frozen partition, D `2024-08-02..2026-03-23` (389 sessions) and V
`2026-03-24..2026-07-17` (80). The twelve-month freeze is retained for the acquisition
programme it was written for. Measured before deciding: 170 of the 389 development sessions
fall inside the twelve-month window, so adopting it would have discarded 219 of them.
[`STUDY_WINDOW.md`](STUDY_WINDOW.md) carries the reasoning; publication reads the adopted
window from `configs/rp2_v3_study_window.json` and refuses any run that does not match it.

## No longer carried

`role_for` in `src/mds650/rp2/partition.py` has no lower bound, which would have blocked a
twelve-month rebuild: Block 1 enumerates from the start of the tape and labels every
pre-validation session `D`. Decision 84 adopts the partition, which is the window `role_for`
already produces, so the change is not needed and the frozen partition stands. It is recorded
here because it becomes a prerequisite again the moment a narrower window is adopted.

## Standing constraints

- Sealed cohort reads: 0. C, Phase 8 and Phase 9 stay closed for the whole programme.
- Frozen artifacts are never overwritten. A superseded result is recorded in
  [`SUPERSEDED_RESULTS.md`](SUPERSEDED_RESULTS.md), not deleted.
- No test is weakened to pass. A red test means the cause is fixed.
- Every reported number comes from a real run over the local evidence, never an estimate
  carried over from an earlier run.
