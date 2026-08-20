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
| 11 | `db/rp2-v3-versioned-results` | Versioned Supabase results | in review |
| 12 | `results/rp2-v3-rebuild` | Rebuild, scorecard, publication | pending |

## Open decision

The repository states two different study windows and has never reconciled them:
`AGENTS.md` freezes twelve months from 2025-07-21, and the frozen partition every artifact
was built on covers 2024-08-02 to 2026-07-17. [`STUDY_WINDOW.md`](STUDY_WINDOW.md) states
both, records which one produced the evidence, and sets out the decision that is owed. No
sample was widened or narrowed to resolve it.

## Carried into the rebuild gate

`role_for` in `src/mds650/rp2/partition.py` has no lower bound, so Block 1 enumerates from
the start of the tape and labels every pre-validation session `D`. With `twelve_month`
adopted, a rebuild therefore produces 2024-08-02 and publication refuses it. Giving `role_for`
the window's first session changes which sessions are `D`, which changes the frozen partition
and everything built on it — so it is the rebuild gate's first task, done there with the
supersession that implies, rather than smuggled into the publication gate.

## Standing constraints

- Sealed cohort reads: 0. C, Phase 8 and Phase 9 stay closed for the whole programme.
- Frozen artifacts are never overwritten. A superseded result is recorded in
  [`SUPERSEDED_RESULTS.md`](SUPERSEDED_RESULTS.md), not deleted.
- No test is weakened to pass. A red test means the cause is fixed.
- Every reported number comes from a real run over the local evidence, never an estimate
  carried over from an earlier run.
