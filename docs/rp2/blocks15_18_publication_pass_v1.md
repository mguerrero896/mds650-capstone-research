# Blocks 15–18 — the publication pass

**Status:** `EXECUTED — 2026-08-19`
These four blocks are the writing pass and run **after** the science blocks, so the narrative
describes real results rather than hoped-for ones.

---

## Block 15 — repository writing audit

The program's audit was written on 2026-08-18 against the README as it then stood. An
editorial pass landed the same day. Auditing the **current** text against the program's five
complaints, rather than restating them:

| # | Complaint | Verdict now | Evidence |
|---|---|---|---|
| 1 | Too many internal identifiers | **largely remediated** | The whole README contains 10 internal-identifier occurrences: `Phase 8` ×3, `decision 53` ×2, `decision 56`, `decision 62`, `Phase 9`, `R-024`, `C2` — each parenthetical or explained in place. The pattern the program flagged ("`C6 B1v3 confirmation returned…`") does not appear. |
| 2 | Narrative mixes science and operations | **remediated** | No `D:\` path, scheduled-task name, collector status, read-token count or serialization incident appears. The single hit for "token" is a security statement about secret scanning. |
| 3 | Temporal inconsistencies | **remediated structurally** | `STATUS.md` is auto-generated from the canonical state with a CI drift test (decision 63). The README no longer says "decision 53 so far". |
| 4 | Ambiguity in session counts | **remediated** | Only two session figures appear and both are qualified ("10-session holdout (July 2026)", "160 sessions"). |
| 5 | Too many conclusions in the abstract | **remediated** | The opening answers question / data / method and defers results to a later section. |

### What the audit did *not* anticipate, and what is actually wrong now

**The "Findings at a glance" section is scientifically stale.** It was accurate on
2026-08-18 and is no longer the best summary available, because Research Program v2 changed
three things a reader needs:

1. B1 is no longer "ATM implied variance level and changes" — a full arbitrage-aware surface
   now exists, and it still produces a null. The sentence "conventional option state (B1)
   does not reliably beat B0" is now much stronger than the reader can tell.
2. B2 is no longer nine five-minute counts, and the DML result (Block 7) is a **positive
   mechanism finding** that the current text does not contain at all.
3. The Clark–West / QLIKE decomposition (Block 10) supplies the explanation the README
   currently lacks for *why* a real effect produces no usable forecast.

**This is the one substantive editorial defect**, and Block 17 fixes it.

---

## Block 16 — recommended professional structure

The program proposes a numbered `docs/01_…` through `docs/07_…` skeleton with
`governance/`, `operations/`, `protocols/` and `artifacts/public|schemas/`.

`docs/` currently holds **128 markdown files** in a flat namespace plus a classification
table in `docs/INDEX.md`, and 13 more under `docs/rp2/`.

**Recommendation: adopt the numbered skeleton as a reading layer, not as a move.**

Reason, stated plainly: decision 62 makes frozen artifacts physically immutable and a CI
tripwire fails on drift; `docs/INDEX.md`, `data/CANONICAL_STATE.json`, `STATUS.md`, the
mirror exclude list and roughly 40 cross-references address documents by their current path.
A bulk `git mv` would break every one of those in a single commit, and the benefit — a nicer
tree — is a presentation benefit that a seven-file reading layer delivers without the risk.

Proposed reading layer, each file a short guide that links out rather than duplicating:

```
docs/01_research_question.md      -> the four questions, B0/B1/B2, the universe
docs/02_data_and_pit_design.md    -> providers, PIT contract, the 120 s cutoff, admissibility
docs/03_methodology.md            -> partition, targets, baseline, ladder, inference
docs/04_results.md                -> reconciliation + Research Program v2 blocks 7-11
docs/05_economic_evaluation.md    -> bridges B and C, deflated Sharpe, what A needs
docs/06_limitations.md            -> power, era dependence, licence, sealed-cohort overlap
docs/07_reproducibility.md        -> synthetic demo, Dockerfile, custodian route
docs/glossary.md                  -> every internal identifier, defined once
```

`docs/governance/` and `docs/operations/` are then populated **by moving only files that
nothing references** — a much smaller, verifiable change. This is a decision requiring the
owner's signature because it touches the public mirror's shape.

---

## Block 17 — README opening

Implemented. The opening now states the three nested sets, the four primary questions and a
result paragraph that is true after Research Program v2: the only completed prospective
holdout provides no robust evidence; retrospective periods contain positive effects reported
separately because they are model-, era- or exploration-dependent; and the repository makes
no claim of a generalizable or profitable edge.

The Findings section gains the three things Block 15 identified as missing, with their
artifact hashes. See the README diff for the exact wording.

---

## Block 18 — what to keep and what to move

| Destination | Content | Status |
|---|---|---|
| **Keep in the README** | question; B0/B1/B2; universe; target; design; primary result; limitations; quickstart; reproducibility; current status | already true |
| **Move to governance** | numbered decisions, campaign counts, one-read tokens, serialization, incidents, moratoria, full multiplicity, long hashes, historical paths | already out of the README; the destination directory does not yet exist |
| **Move to operations** | scheduled tasks, collector scripts, Windows paths, storage guards, alert files, recovery procedure | already out of the README; lives in `docs/*_execution_plan_*.md` and the internal exclude list |
| **Move to appendix** | sensitivity tables, MCS by block length, provider diagnostics, invalidated claims, provenance trees | in `artifacts/` and per-gate docs; not surfaced as an appendix |

**The keep/move rule is already satisfied for the README itself.** What is missing is the
*destination structure*, which is Block 16's proposal. Until that is signed off, the
classification lives in `docs/INDEX.md`, which already annotates every file as current,
superseded or internal-only.

---

## Advance rule for the publication pass

There is no numeric advance rule for Blocks 15–18. The deliverables are: an audit that
distinguishes already-remediated complaints from live ones (done, and it found the program's
own audit was four-fifths out of date); a structure proposal with its risk stated (done, and
recommended as a reading layer rather than a move); a README opening that survives contact
with the results (done); and a keep/move classification (done, blocked only on the
destination directories).

**Two items require the owner's signature:** adopting the numbered reading layer, and
creating `docs/governance/` + `docs/operations/` by moving unreferenced files.
