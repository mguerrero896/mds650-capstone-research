# MDS650 — Point-in-Time Options Activity for RV30 Forecasting

[![ci](../../actions/workflows/ci.yml/badge.svg)](../../actions/workflows/ci.yml)
![python](https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white)
![typing](https://img.shields.io/badge/mypy-strict-blue)
![tests](https://img.shields.io/badge/tests-1%2C000%2B-brightgreen)
![status](https://img.shields.io/badge/research-preregistered%20%C2%B7%20hash--sealed-6f42c1)

Does what just happened in the options market help predict how much a stock will move
over the next 30 minutes?

This repository holds the full research pipeline for my MDS650 capstone. It builds a
point-in-time (PIT) panel from three commercial market-data providers, constructs nested
information sets, and tests — under preregistered, one-read evaluation gates — whether
conventional option prices (B1) and recent option-trade activity (B2) add out-of-sample
predictive value for 30-minute realized variance (RV30) beyond what the stock and the
broad market already reveal (B0).

## The question, in plain terms

At every five-minute mark of the New York trading session, freeze everything a forecaster
could legitimately have known at that moment, then predict the realized variance of the
next 30 one-minute returns. Compare three nested views of the world on identical origins:

| Set | What it knows |
|-----|---------------|
| **B0** | Underlying price/volume history and market-wide state |
| **B1** | B0 + conventional option state (ATM implied variance level and changes) |
| **B2** | B1 + point-in-time option-trade activity (what was just traded, target-blind) |

If B2 beats B1 on data neither model has seen, recent option flow carries real
information. If it doesn't, that is worth knowing too — a preregistered null is a valid
result here, and the pipeline is built so that a null cannot be quietly tuned away.

> [!IMPORTANT]
> Every protocol in this repository was **frozen with a cryptographic hash before its
> results were seen**, sealed holdouts are read **exactly once** under access-ledger
> control, and every number below traces to a hashed artifact. Honest nulls outrank
> flattering retrospectives by binding rule (decision 53).

### The story in one picture

![Timeline 2024 to 2026: a strong option-information signal fades toward null, with two sealed prospective reads ahead](docs/figures/story_timeline.svg)

<details>
<summary>Timeline source (mermaid)</summary>

```mermaid
timeline
    title Option-information content for 30-minute variance, 2024 → 2026
    2024 H2 : Total B0→B2 positive in 5 of 5 model families (exploratory)
    2025 H1 : Positive in both independent families (+0.013..+0.015)
    2025 H2 – 2026 Q1 : Positive in both families (+0.010..+0.021, 160 sessions)
    2026 H1 : Fading to null · decay measured at −0.028 per year
    Jul 2026 : Prospective preregistered holdout - NULL (read once)
    29 Aug 2026 : Phase 8 prospective read (TOST-armed, sealed)
    Nov 2026 : Phase 9 prospective read of the TOTAL contribution (frozen, collecting)
```

</details>

## How to read this repository (no specialist background needed)

1. **The question and the answer in plain words** — this page, top to bottom.
2. **The whole story in one document** —
   [`reports/gate_cascade_report_20260817.md`](reports/gate_cascade_report_20260817.md):
   what was tested, how, and what each test found, in reading order.
3. **The thesis itself** —
   [`reports/final_report_draft_v2.md`](reports/final_report_draft_v2.md).
4. **The defense slides and prepared Q&A** —
   [`reports/defense_deck_v2.md`](reports/defense_deck_v2.md).
5. **Deep evidence, when you want proof of any number** — every document in
   [`docs/INDEX.md`](docs/INDEX.md) and every result file under `artifacts/` carries a
   SHA-256 hash so it cannot be silently altered.

**Eight terms cover almost everything:**

| Term | Plain meaning |
|---|---|
| RV30 | How much a stock actually moved over the next 30 minutes (the thing we predict) |
| B0 / B1 / B2 | Three levels of knowledge: stock data only / + option prices / + option trades |
| PIT (point-in-time) | Only using information that truly existed at the moment of each forecast |
| QLIKE | The score used to judge forecasts (lower is better; differences are what matter) |
| Prospective vs retrospective | Tested on data sealed *before* anyone saw it, vs tested on the past |
| Frozen | Locked with a cryptographic hash before results were seen — cannot be tuned after |
| MDE | The smallest effect size the study promised to care about |
| Holm | A correction so that testing many things doesn't manufacture false positives |

## Findings at a glance (as of 2026-08-19)

Honest summary, in the order the evidence deserves:

1. **The only prospective, preregistered test returned null.** A 10-session holdout
   (July 2026), sealed before collection and read exactly once, confirmed neither the B1
   nor the B2 increment.
2. **Retrospective evaluations show a recurring, model-specific B2 signal.** Under the
   confirmatory Gamma GLM, the B2-over-B1 QLIKE improvement is positive and statistically
   supported in several historical blocks (up to +0.053, robust to the five registered
   timing sensitivities in the latest confirmation), **but the fixed LightGBM challenger
   reverses or nulls it in every one of those samples.** The binding label is
   `POSITIVE_BUT_NOT_GLOBALLY_CONFIRMED`.
3. **Conventional option state (B1) does not reliably beat B0** under the frozen
   campaign designs; the contrast flips sign across periods, assets, and model families.
4. **Exploratory, but model-robust: the *total* option-information contribution
   (B0→B2) is positive across families in most eras.** In the 2024 blocks it is
   significantly positive in 5/5 families, and a uniform three-family ladder over the
   frozen panels shows 3/3-family positive totals across 2025-03..2026-03 (229
   sessions, wild p ≤ 2e−4), concentrated in option state and fading toward null in
   2026 (`docs/positive_findings_v1.md`, decision 56). The family-dependence headline
   is partly a property of the frozen confirmatory design, not of option information
   itself.

![Five campaign estimates with 95 percent confidence intervals declining from 2024 to a 2026 null, with the prospective holdout highlighted](docs/figures/signal_decay.png)

*The Gamma-family B2 effect, campaign by campaign (95% CI, canonical numbers from the
Gate-4 artifact). The amber point is the prospective holdout — sealed before collection,
read once, and sitting on zero.*

### What a much richer option representation changed (2026-08-19)

Points 1–4 above were established with a compressed option representation: B1 was a single
at-the-money implied variance, B2 was nine counts in five-minute windows. A natural objection
is that the null simply reflects that compression. That objection has now been tested
directly, and the answer is on the record.

**B1 and B2 were rebuilt from the raw tape.** Every option trade carries the prevailing NBBO
and an implied volatility, so a full surface could be reconstructed at each origin without
buying new data: a median of **724 contracts, 22 expiries and 111 strikes per snapshot**,
against one number before. It reproduces put skew, smile convexity, a negative 25-delta risk
reversal and a positive variance risk premium without any of them being imposed. B2 became
**52 microstructure features** — Greeks-weighted signed flow, Hawkes arrival intensity,
concentration and entropy, trade-to-quote impact — over 125,136 origins and 1,896
session-assets with zero failures.

5. **Recent option flow does carry information that price history and the option surface
   cannot reconstruct.** Under double machine learning, orthogonalising B2 against B0+B1 and
   clustering by session, the joint null is rejected at **p = 3 × 10⁻¹²** in discovery, and
   two features replicate in validation with the same sign: the **Hawkes burst-intensity
   innovation** (t = +4.4 and +2.3) and the **buyer-initiated premium share** (t = +2.0 and
   +2.0). Vega-, gamma- and delta-weighted flow are null in both. *It is the timing and the
   direction of the flow that matter, not its exposure-weighted size.*
6. **That information is smaller than the cost of estimating the parameters needed to use
   it.** Clark–West — which corrects for exactly that estimation cost — is significant almost
   everywhere, while the corresponding out-of-sample QLIKE change is frequently negative
   (t = +6.95 with ΔQLIKE = −0.001 in one case). Across six model families, four contrasts
   and an interaction term, every estimand is null or family-dependent in discovery and
   null-to-negative in validation. Hansen's SPA picks a best candidate at p = 0.0070, above
   the project's own sequential budget of 0.00417; White's Reality Check rejects nothing.
7. **No economic value, at any level of selectivity.** A variance-risk strategy using the
   forecast is *worse* with option information than without it in discovery at every trading
   threshold, and every deflated Sharpe probability is at most 0.19 — 0.000 once the strategy
   is made selective. The one residue is a 15 % lower volatility-targeting tracking error in
   discovery, which does not replicate.
8. **A confirmatory prospective test of this effect is not currently feasible.** Sized on the
   measured session-level dispersion, detecting the largest effect ever observed here needs
   **537 sessions**; the design under discussion proposed 60–120. Running it would return a
   null whether or not the effect is real, so the protocol is frozen and deliberately not
   launched.

The full cascade — eighteen blocks, each with its advance rule and its verdict — is in
[`docs/research_program_v2_progress.md`](docs/research_program_v2_progress.md), with one
document per block under [`docs/rp2/`](docs/rp2/).

The cross-campaign reconciliation — every contrast, every model, every protocol freeze
date — lives in [`docs/results_reconciliation_v2.md`](docs/results_reconciliation_v2.md).
The claim rules that every deliverable must follow are decision 53 in
[`docs/methodology_decisions.md`](docs/methodology_decisions.md).

## How the pipeline works

![Pipeline: three providers feed a sealed point-in-time panel, nested information sets B0, B1, B2, preregistered evaluation, and a sealed verdict](docs/figures/pipeline_diagram.svg)

<details>
<summary>Pipeline source (mermaid)</summary>

```mermaid
flowchart LR
    subgraph Providers
        FMP["FMP<br/>1-min bars, rates"]
        MSV["Massive<br/>option quotes (NBBO)"]
        UW["Unusual Whales<br/>option trade tape"]
    end

    subgraph PIT["PIT panel construction"]
        AUD["Authenticated audits<br/>+ timestamp contracts"]
        ORG["5-minute forecast origins<br/>XNYS calendar"]
        TGT["RV30 targets<br/>30 one-minute log returns"]
    end

    subgraph Sets["Nested information sets"]
        B0["B0: underlying + market"]
        B1["B1: + ATM implied variance"]
        B2["B2: + trade activity (target-blind)"]
    end

    subgraph Eval["Preregistered evaluation"]
        FRZ["Hash-sealed method freeze"]
        MDL["Gamma GLM (confirmatory)<br/>LightGBM (fixed challenger)<br/>persistence / HAR / Ridge"]
        OOS["Chronological folds<br/>30-min purge/embargo"]
        HLD["One-read sealed holdouts<br/>access ledgers"]
    end

    FMP --> AUD
    MSV --> AUD
    UW --> AUD
    AUD --> ORG --> TGT
    ORG --> B0 --> B1 --> B2
    TGT --> FRZ
    B2 --> FRZ
    FRZ --> MDL --> OOS --> HLD
    HLD --> RES["QLIKE contrasts<br/>day-clustered bootstrap + Holm"]
```

</details>

Every result flows through the same discipline: the protocol is frozen and hashed before
outcomes are visible, sealed holdouts are opened exactly once under an access ledger, and
negative results stay in the record with the same weight as positive ones.

## Where things live

```
src/mds650/          Typed library (mypy --strict): providers, PIT panel, targets,
                     features, models, inference, calibration, HAR/HARQ, evaluation
scripts/             Phase runners, gate runners, acquisition, automation
                     -> classified in scripts/README.md (active / frozen-evidence /
                        one-shot-done / archive)
tests/               1,000+ tests: unit, contract (artifact/freeze locks), e2e
specs/001-.../       Spec Kit: requirements, plan, tasks, JSON-schema contracts
docs/                Methodology decisions (binding, numbered), risk register,
                     results reconciliation, gate reports, PIT contracts
                     -> every doc classified in docs/INDEX.md
artifacts/           Committed governance evidence: preregistrations, manifests,
                     hashes, results JSONs, access ledgers (immutable)
reports/             Final report, defense deck, gate-cascade report,
                     canonical validation package, proposal
```

> [!NOTE]
> Licensed commercial data cannot be redistributed. The 14 granular derived datasets
> (~133 MB) live in **gated private storage**: their SHA-256 pointers are committed in
> [`data/GATED_DATA_POINTERS.json`](data/GATED_DATA_POINTERS.json) and access is
> granted per request — see [`data/DATA_ACCESS.md`](data/DATA_ACCESS.md). Everything
> else (all code, docs, aggregate results, sanitized fixtures) is fully public; full
> reproduction from scratch requires live provider entitlements.

Heavy commercial-derived evidence (raw provider payloads, large panels) is **not** in
git — see the next section.

## Getting started

Requirements: Python 3.12, [uv](https://docs.astral.sh/uv/), Windows or Linux.

```bash
uv sync --locked          # reproduce the exact environment from uv.lock
uv run pytest -q          # full suite; evidence tests skip without the mount below
uv run ruff check src scripts tests
uv run mypy src scripts
```

Two environment variables control access to non-versioned research evidence:

| Variable | Meaning |
|----------|---------|
| `MDS650_DATA_ROOT` | Root of bulk licensed data (default `D:\MDS650`) |
| `MDS650_EVIDENCE_ROOT` | Mount point of the byte-faithful evidence tree; when set, ~70 additional contract tests verify frozen artifact hashes against it |

Without the mounts the suite still runs — evidence-bound tests skip transparently with
an explicit reason rather than failing or silently passing.

## Data availability

The study uses licensed commercial data (FMP, Unusual Whales, Massive) that cannot be
redistributed. Reproducibility is handled at two levels, following the registered
controlled-auditability contract:

- **With equivalent licenses:** the frozen pipeline re-runs end to end from raw
  acquisition; every step is manifest- and hash-bound.
- **Without licenses:** code, JSON-schema contracts, sanitized fixtures, frozen session
  and asset registries, SHA-256 evidence indices, missingness reports, and aggregate
  results allow full audit of *process* without access to raw vendor rows.

Raw payloads, credentials, and bulk caches never enter git; the ignore rules and a
contract test enforce that no API key or bearer token appears in tracked files.

## Research governance

The repository treats process integrity as a first-class deliverable:

- **Numbered binding decisions** (53 so far) in `docs/methodology_decisions.md` — every
  methodological choice, window, and claim boundary is written down before it matters.
- **Risk register** (`docs/risk_register.md`, R-001…R-024) — including the uncomfortable
  ones: campaign-level multiplicity, confirmatory-model calibration pathology, and the
  two provider-timing assumptions that remain unproven.
- **Sealed cohorts** (Validation A/B, Phase 8 prospective holdout) — zero scientific
  reads; their disposition is an explicit owner decision
  (`docs/sealed_cohorts_disposition_v1.md`), and new retrospective campaigns are under
  moratorium until it is made.
- **Physically immutable evidence** — frozen artifacts are write-protected on disk and
  hash-verified in CI (decision 62), so a committed result cannot drift silently.

## Status

Active capstone research, single-author. The proposal draft is at
[`reports/proposal_draft_v2.md`](reports/proposal_draft_v2.md).

The eighteen-block research programme that rebuilt both option information sets from the raw
tape is complete; its finding is that recent option flow carries real but economically
negligible incremental information, and that no feasible prospective test could confirm it.
The next scientific step is an owner decision between completing the sealed prospective
holdout or closing it formally — the analysis code is ready either way — and, separately,
whether to fund a ≥537-session campaign or to publish the null as it stands.

**Author:** Miguel Guerrero · MDS650 Capstone · 2026
