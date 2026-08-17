# Positive findings under decision 56 (v1, 2026-08-18)

Label: `EXPLORATORY_DESCRIPTIVE`. Code: `scripts/run_gate10_positive_findings.py`,
`scripts/run_gate11_era_map.py`; artifacts `artifacts/gate10_positive_findings/` and
`artifacts/gate11_era_map/` (+ sha256; every input hash recorded). Re-analysis of
already-read frozen artifacts and panels only; no sealed reads; the decision-53
hierarchy and decision-52 moratorium are untouched. Signs reported exactly as computed.

## Finding 1 — In 2024, option information was positive across every model family

From the frozen C5 forecasts (five families), studentized:

| Block | Contrast | Families significantly positive (p < 0.05) |
|---|---|---|
| 2024-A | B0→B1a | **5 / 5** (Gamma +0.084, LightGBM +0.077, HAR-RV +0.086, Ridge +0.086, Elastic Net +0.028) |
| 2024-A | **B0→B2 total** | **5 / 5** |
| 2024-B | B0→B1a | 4 / 5 (Elastic Net ns) |
| 2024-B | **B0→B2 total** | **4 / 5** |

Model-family-independence is this project's own definition of a "global" effect, and on
these blocks the *total* option-information contribution meets it. The famous
family-dependence applies to the B2-over-B1 *increment*, not to the total contribution.
Caveat, stated plainly: the same-era C6 panel under the B1v3 feature *redesign* shows the
opposite sign for the option-state block under smooth families — the positive is
B1a/B1v2-definition-specific, and both facts appear together wherever this is cited.

## Finding 2 — The uniform era map shows cross-family positives through 2026Q1

One fixed ladder (three families × nested B0/B1/B2, identical design in every era, no
tuning) over the four frozen panels:

| Era | Sessions | B0→B2 total: log-OLS | Ridge | LightGBM | Cross-family verdict |
|---|---|---|---|---|---|
| 2024H2 (B1v3 features) | 90 | −0.0020 ns | −0.0020 ns | +0.0004 ns | null (redesign era) |
| 2025H1 | 69 | **+0.0154 (p 6e−04)** | **+0.0154** | **+0.0125 (p 0.019)** | **3/3 positive** |
| 2025H2–2026Q1 | 160 | **+0.0101 (p 4e−07)** | **+0.0101** | **+0.0213 (p 4e−10)** | **3/3 positive** |
| 2026H1 (dev) | 80 | +0.0051 ns | +0.0051 ns | +0.0102 (p 0.059) | fading toward null |

Two independent panels covering 2025-03..2026-03 — 229 sessions — show a
**model-robust, wild-bootstrap-significant total option-information gain** under a
uniform design. The channel is mostly option *state* (B0→B1); the trade-activity
increment (B1→B2) stays small/null here, consistent with every earlier gate.

## What this changes (and what it does not)

- The thesis gains a genuinely positive, cross-family, era-spanning exploratory result:
  **option-market information improves out-of-sample RV30 forecasts across model
  families through most of the sample period under a uniform evaluation design**, with
  the effect concentrated in option state, weakening into 2026 and null in the
  prospective 2026 holdout. The earlier "family-dependent" headline is revealed to be
  partly a property of the frozen campaign designs (Gamma confirmatory + the B1v3
  feature redesign), not of option information per se.
- Nothing confirmatory changes: `confirmed_contrasts` stays empty; the prospective C2
  null is still reported first; Phase 8 remains the only path to a confirmatory global
  claim. These findings are the *exploratory* centerpiece, and they are labeled as such
  everywhere.

## Citation rule

Any use of Finding 1/2 must carry the `EXPLORATORY_DESCRIPTIVE` label, must cite the
C6-redesign counter-sign alongside Finding 1, and must appear after the prospective-null
statement per decision 53.
