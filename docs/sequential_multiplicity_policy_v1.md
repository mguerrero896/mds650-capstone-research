# Sequential multiplicity policy (v1, 2026-08-18 — decision 64)

Reviewer correction accepted: after the prospective null (C2), several
retrospective campaigns were launched, each informed by the previous result.
Decisions 52/53/56 already downgrade those results (moratorium, exploratory
labels, reporting hierarchy) — but no within-campaign Holm correction removes
the bias of *starting* campaign k+1 after seeing campaign k. Retrospective
results therefore stay capped at EXPLORATORY_DESCRIPTIVE **permanently**; this
policy binds every FUTURE campaign instead.

## Binding rules for future campaigns

1. **Alpha spending over an open sequence.** The remaining confirmatory budget
   is α_total = 0.05, spent as α_k = 0.05 / (k (k + 1)) for the k-th future
   confirmatory campaign (Σ_k α_k = 0.05 over an unbounded sequence):

   | k | campaign | α_k |
   |---|---|---|
   | 1 | Phase 8 one-shot (frozen protocol, authorization 2026-08-29) | 0.025 |
   | 2 | Phase 9 total-contribution evaluation (~Nov 2026) | 0.008333… |
   | 3+ | any later confirmatory campaign | 0.05 / (k (k + 1)) |

   Machinery: `mds650.sequential.alpha_spending_schedule` (tested in
   `tests/unit/test_sequential.py`). The frozen Phase 8/9 protocol documents are
   immutable (decision 62) and are NOT edited; this policy composes with them —
   where a frozen protocol names a less strict within-campaign α, the binding
   threshold is the SMALLER of the two.

2. **E-values alongside p-values.** Each future campaign reports, next to its
   registered test, the e-value of its pre-registered alternative
   (`e_value_from_likelihood_ratio`), the running test martingale across
   campaigns (`test_martingale`), and the always-valid p-value
   (`always_valid_p_value`, Ville's inequality). These remain valid under
   optional stopping AND optional continuation — exactly the "we might run
   another campaign after seeing this one" regime this project lives in.

3. **Pre-registered maximum.** At most **3** further confirmatory campaigns
   (k = 1, 2, 3) are registered for this thesis cycle. Launching a fourth
   requires a new decision entry that says explicitly it re-opens the sequence
   and inherits α_4 = 0.0025.

4. **Retrospective results stay retrospective.** Nothing in this policy
   upgrades any existing exploratory result; the citation hierarchy of
   decision 53 is unchanged.
