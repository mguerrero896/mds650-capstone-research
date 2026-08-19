# Block 10 — the inference that was still missing

**Status:** `EXECUTED — 2026-08-19` · label `EXPLORATORY_MECHANISM_DISCOVERY`
**Artifact:** `artifacts/rp2_block10_inference/inference.json`
(`inference_sha256 = 078a1f59a3dae920e37dfad3ae4212d64d73288df39eef0fc5be43a45729e104`)
**Code:** `src/mds650/rp2/inference.py`, `scripts/rp2_block10_inference.py`
**Tests:** `tests/unit/test_rp2_inference.py` (11 tests)

---

## 1. The comparison the tree families were never entitled to

Clark–West adjusts a nested comparison for the estimation noise the larger model carries
under the null: `f_t = e₀ₜ² − [e₁ₜ² − (ŷ₀ₜ − ŷ₁ₜ)²]`. **That derivation assumes the restricted
model is a parameter restriction of the unrestricted one.** A gradient-boosted tree fitted on a
larger feature set is a different function class, not a nested restriction, so the adjustment has
no derivation there and inflates the statistic toward significance.

Every Clark–West figure this document previously reported for `gamma_glm` and `lightgbm` is
**withdrawn** (decision 68). `clark_west_terms` now requires an explicit `nested_linear`
assertion and refuses otherwise, and the tree families are compared with a session-blocked
bootstrap instead — resampling whole blocks of sessions, which respects the serial dependence
that an origin-level resample destroys.

Results are aggregated to session means before testing. The panel carries 66 origins per
session-asset; treating them as independent draws overstates the effective sample by roughly the
number of origins per session.

### Discovery (154 sessions)

| Model | contrast | CW t | GW p | session ΔQLIKE | blocked p |
|---|---|---|---|---|---|
| log-OLS | B1 over B0 | +8.14 | <10⁻⁴ | **+0.00422** | 0.0060 |
| log-OLS | B2 over B1 | +3.06 | <10⁻⁴ | **+0.00147** | 0.0130 |
| log-OLS | B2 over B0 | −0.94 | <10⁻⁴ | **+0.00294** | 0.0020 |
| log-OLS | total over B0 | +9.12 | <10⁻⁴ | **+0.00569** | 0.0020 |
| Gamma GLM | B1 over B0 | n/a | <10⁻⁴ | +0.00366 | 0.0230 |
| Gamma GLM | B2 over B1 | n/a | <10⁻⁴ | +0.00129 | 0.0450 |
| Gamma GLM | total over B0 | n/a | <10⁻⁴ | +0.00495 | 0.0050 |
| LightGBM | B1 over B0 | n/a | 0.558 | +0.00217 | 0.298 |
| LightGBM | B2 over B1 | n/a | 0.0017 | +0.00209 | 0.0140 |
| LightGBM | B2 over B0 | n/a | 0.0004 | +0.00217 | 0.0020 |
| LightGBM | total over B0 | n/a | 0.085 | +0.00426 | 0.0090 |

### Validation (32 sessions)

| Model | contrast | CW t | GW p | session ΔQLIKE | blocked p |
|---|---|---|---|---|---|
| log-OLS | B1 over B0 | +3.63 | 0.389 | −0.00219 | 0.519 |
| log-OLS | B2 over B1 | +4.10 | 0.433 | −0.00005 | 0.881 |
| log-OLS | total over B0 | +4.56 | 0.480 | −0.00224 | 0.381 |
| Gamma GLM | B1 over B0 | n/a | 0.436 | −0.00376 | 0.462 |
| Gamma GLM | B2 over B1 | n/a | 0.497 | +0.00080 | 0.807 |
| LightGBM | B1 over B0 | n/a | 0.245 | −0.00576 | 0.497 |
| LightGBM | B2 over B1 | n/a | 0.132 | +0.00584 | 0.402 |
| LightGBM | total over B0 | n/a | 0.596 | +0.00008 | 0.974 |

**The finding is the gap between the two panels, and it is not the gap this document used to
report.** On the rebuilt data every discovery increment is positive and most are significant
under the blocked bootstrap; in validation not one increment is distinguishable from zero, and
the signs are mostly negative.

Two things make that contrast harder to explain away than a simple sample-size story, and both
cut against the effect being real:

* **Validation's baseline is weaker, not stronger.** SPY and QQQ minute bars exist for the
  discovery sessions only, so B0 in validation carries no market-wide state at all
  (`market_control_rows` = 71,192 in D, 0 in V; decision 75). A weaker baseline should make B1
  and B2 increments *easier* to find. They are absent anyway.
* **Neither sample is confirmatory.** V was read for the specification comparisons, the family
  choice, the recalibration decision and the 36-target battery, and each fed back into what is
  reported (decision 67). Agreement between D and V would have been evidence against a
  single-era accident; disagreement is not evidence of anything beyond itself.

Where Clark–West still applies — the two linear families — it remains significant while the
matching out-of-sample change is not always positive (`log_ols B2 over B0`: CW t = −0.94 while
the session ΔQLIKE is +0.00294). Clark–West asks whether the *population* coefficients are
non-zero; QLIKE asks whether the *estimated* model forecasts better. The gap between them is
the cost of estimating those coefficients, and it is the sharpest statement this project can
make about why a real mechanism produces no reliable forecast improvement.

## 2. Giacomini–White: the advantage is state dependent in discovery

Conditioning on ex-ante observables (trailing 30-minute realized variance, minute of session,
trailing dollar volume), `E[dₜ | Zₜ] = 0` is rejected at p < 10⁻⁴ for most discovery
contrasts and is generally not rejected in validation.

So in discovery the loss differential *does* depend on observable state — consistent with
Block 9's finding that the effect concentrates near the close and in expiration weeks. In
validation the conditional structure is gone too, not merely the unconditional mean.

## 3. Superior Predictive Ability — discovery clears the budget, validation does not

Every model × information-set combination against the plain `log_ols|B0` benchmark,
stationary bootstrap (mean block 5, 1,000 replications):

| Universe | best candidate | mean ΔQLIKE | Hansen SPA p | White Reality Check p |
|---|---|---|---|---|
| D | `lightgbm\|B0+B1+B2` | +0.01179 | **0.0010** | 0.0010 |
| V | `gamma_glm\|B0+B2` | +0.00156 | 0.723 | 0.832 |

**This reverses what this section previously said, and the reversal is a consequence of the
data corrections, not of a different test.** On the previous panels the discovery SPA stood at
0.0070 and failed the budget; on the rebuilt panels it is 0.0010 and clears it. The panels
changed because early-close sessions had been discarded by a quality gate reading a fabricated
390-minute grid, because two acquisitions overlapped on 24 session-assets, and because B1 is now
built against a measured forward and an exact tenor rather than against the spot and a
day-rounded one.

Three caveats, all material, and together they are why this is not a positive result:

1. **The SPA family mixes model changes with information changes.** The best D candidate beats
   the benchmark partly because LightGBM beats log-OLS, not only because B1+B2 beats B0.
   The information-only comparison is Block 8's contrast table, which remains null.
2. **Validation rejects nothing.** SPA p = 0.723 and Reality Check p = 0.832 with the best
   candidate at +0.00156. A result that clears a multiplicity budget in one sample and sits at
   p = 0.72 in another is a description of one sample, not of the mechanism.
3. **Neither sample is confirmatory** (decision 67). D and V are both exploratory: V was read
   for specification, family and target choices that fed back into what is reported. Clearing
   an alpha budget inside an exploratory sample does not convert it into a confirmation, and
   the budget itself was written for a confirmatory sequence.

## 4. E-values and alpha spending

The sequential machinery required by §10 already exists in the project
(`src/mds650/sequential.py`, decision 64) and is not re-implemented here. What this block adds
is the arithmetic that binds it: at look 3 the budget is **α₃ = 0.00417**. The discovery SPA
now sits below it at 0.0010; the validation SPA sits at 0.723. **No test in this program
produces a p-value below the budget in the validation universe**, which is the universe the
budget was written to govern.

## 5. Advance rule

**"Survives multiplicity": FAIL, and that is still the result.** In discovery the SPA best
candidate now clears the alpha budget (0.0010 against 0.00417) and the session-blocked
increments are positive and significant. In validation nothing is distinguishable from zero:
SPA 0.723, Reality Check 0.832, every blocked increment p > 0.29 — against a *weaker* baseline
that should have made an increment easier to find (decision 75).

Neither sample is confirmatory (decision 67), so the discovery result cannot be promoted by
pointing at the second sample, and the second sample declines to agree in any case. Nothing in
this program is eligible to be called a confirmed predictive improvement.
