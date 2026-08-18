# Block 12 — the definitive prospective protocol

**Status:** `DESIGNED — 2026-08-19` · label `PROSPECTIVE_DESIGN`
**Artifact:** `artifacts/rp2_block12_prospective/design.json`
**Code:** `scripts/rp2_block12_prospective_design.py`
**Sealed cohorts read while producing this: 0.** The design is sized on D and V only.

---

## 1. The headline, before the protocol

The program asks for "at least 60–120 sessions". Sized against the **measured** session-level
dispersion of each contrast, that is not enough by a wide margin.

| Universe | family | contrast | observed effect | session σ | **sessions required** |
|---|---|---|---|---|---|
| D | LightGBM | Δ_B2\|B1 | **+0.00322** | 0.02043 | **537** |
| D | Gamma GLM | Δ_B1 | +0.00118 | 0.01829 | 3,209 |
| V | Gamma GLM | Δ_B2\|B1 | +0.00027 | 0.00888 | 14,753 |
| D | Gamma GLM | Δ_B2\|B1 | −0.00115 | 0.01251 | unreachable |
| D | LightGBM | Δ_B1 | −0.00178 | 0.01916 | unreachable |
| V | LightGBM | Δ_B2\|B1 | −0.00495 | 0.02935 | unreachable |
| V | LightGBM | Δ_B1 | −0.00179 | 0.02457 | unreachable |
| V | Gamma GLM | Δ_B1 | −0.00225 | 0.01003 | unreachable |

*One-sided α = 0.00250 (decision-64 spending at look 4), power 0.80, sessions as the
independent unit. "Unreachable" means the observed effect is zero or adverse: no sample size
detects it.*

### Minimum detectable effects at feasible sample sizes

| family / contrast | n = 60 | n = 90 | n = 120 | n = 180 |
|---|---|---|---|---|
| D LightGBM Δ_B2\|B1 | 0.00962 | 0.00786 | 0.00681 | 0.00556 |
| D Gamma Δ_B2\|B1 | 0.00589 | 0.00481 | 0.00417 | 0.00340 |
| V Gamma Δ_B2\|B1 | 0.00418 | 0.00342 | 0.00296 | 0.00242 |
| V LightGBM Δ_B2\|B1 | 0.01382 | 0.01129 | 0.00977 | 0.00798 |

**Every MDE at every feasible n exceeds the largest effect ever observed (+0.0032), except
the Gamma GLM in validation — whose own observed effect is +0.00027, an order of magnitude
below its own MDE.**

> **Design conclusion.** A 60–120 session prospective test of Δ_B2|B1 is not a test. It is
> underpowered by a factor of roughly 4.5 to 9 against the effect sizes this program actually
> measured, and it would return a null whether or not the effect is real. Running it and
> reporting "no evidence" would be a foregone conclusion dressed as a finding.

## 2. Protocol, if the owner elects to run it anyway

### 2.1 Primary hypotheses

$$H_{0,1}: \mathbb{E}[\Delta \text{QLIKE}_{B1}] \le \delta_1 \qquad
H_{0,2}: \mathbb{E}[\Delta \text{QLIKE}_{B2\mid B1}] \le \delta_2$$

with the decision-65 four-contrast set plus the interaction reported alongside, as a single
Holm family of five per campaign.

`δ₁ = δ₂ = 0`, and the frozen MDE is the n = 180 row of the table above for the family
concerned. A result below its own MDE is reported as *inconclusive*, never as a null.

### 2.2 Frozen elements

| Element | Value |
|---|---|
| Target | RV30, unchanged (owner decision; see the RV60 escalation in Block 3) |
| Sessions | ≥ 180, ideally ≥ 537 for a properly powered Δ_B2\|B1 |
| First session | strictly after the freeze date of this protocol |
| Assets | the six frozen equities |
| Families | Gamma GLM **and** LightGBM — ridge and log-OLS do not count as independent |
| Baseline | the Block 4 B0, which beats persistence / intraday mean / EWMA / simple HAR / intraday GARCH in both universes |
| Features | immutable, hashed at freeze; the Block 5 surface and Block 6 flow definitions verbatim |
| PIT cutoff | **120 s**, with the Block 2 per-session admissibility rule (P95 ≤ 120 s and backfill ≤ 1 %) |
| α | decision-64 spending, one-sided |
| Reads | exactly one |
| Model changes after the read | forbidden |
| Economics | reported separately from the predictive result |

### 2.3 Success rule for B2

`Δ_B2|B1 > δ₂` with: lower interval bound > 0; multiplicity controlled; both families
positive in sign; at least one family above its own MDE; no adverse interaction between
families; no dominant asset or session; and net economic improvement or positive utility.

On the evidence of Blocks 8–11, **none of these six conditions currently holds in the
validation universe**, and the last one fails in both.

### 2.4 Replication

A single positive window does not demonstrate generalization. A second independent
prospective window is required before any claim leaves the "exploratory" tier.

## 3. What this protocol does *not* do

It does not modify Phase 8 or Phase 9. Those cohorts are sealed, were collected under their
own frozen protocols, and are untouched by this program — `sealed_cohorts_read = 0` is
recorded in the artifact. Block 12 defines a **future** campaign; it does not reinterpret a
past one.

## 4. Recommendation to the owner

Three options, in decreasing order of scientific value:

1. **Do not run a 60–120 session prospective test of Δ_B2|B1.** It is underpowered by
   construction. Publish the null that already exists, with the mechanism finding from
   Block 7 and the Clark-West/QLIKE decomposition from Block 10 as the contribution.
2. **Run a ≥ 537-session campaign** if the question is worth roughly two years of forward
   collection. This is the only design that could detect the effect actually measured.
3. **Change the estimand** to something with a larger measured effect: the Block 9 evidence
   says the discovery effect is ~15× larger near the close and ~3× larger in expiration
   weeks. A protocol restricted to closing-period origins in expiration weeks would need far
   fewer sessions — but that restriction must be pre-registered *before* any new data is
   seen, and it is a different scientific claim from the current one.

**This is a decision requiring the owner's signature.** Nothing is run until it is given.

## 5. Advance rule

"Binding result": **NOT_APPLICABLE — no read performed.** The block's deliverable is the
protocol and its power analysis, both produced. The protocol is `READY_TO_RUN` and
**deliberately not launched**, because the power analysis says the launch would be
uninformative.
