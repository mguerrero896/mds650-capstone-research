# Defense deck v2 (2026-08-18) — decision-53 ordering

One slide per heading. Numbers only from `docs/results_reconciliation_v2.md`, the gate
docs, and the decision-56 artifacts. [PHASE8] slide updates after 2026-08-29.

## 1. The question

Does what just happened in the options market help predict the next 30 minutes of
realized variance — beyond what the stock already tells you? Three nested views on
identical origins: B0 (underlying+market), B1 (+option state), B2 (+trade activity).
Six mega-caps, QLIKE loss, preregistered one-read gates.

## 2. Headline, in the binding order

1. The only prospective, preregistered test (July 2026): **null** for both contrasts.
2. Retrospective evidence: a recurring Gamma-specific B2 increment — real as a
   statistic, **not** usable information (next slides).
3. Exploratory but model-robust: the **total** option-information contribution was
   positive across families through most of the sample, fading to zero by 2026.
4. [PHASE8] Second prospective read (2026-08-29, TOST-armed): —

## 3. The inference is hardened

Cluster-t, Newey-West/DM, wild cluster bootstrap replace saturated sign-bootstrap
p-values; C6 Gamma B2 survives at wild p ≈ 1e−04 and global-Holm adjusted p 0.0036
across all 36 post-null registered contrasts. Serial dependence handled (ρ₁ up to
+0.62; moving-block CIs). The family difference is a formal test now: significant in
every retrospective sample, **null in the prospective holdout**.

## 4. Why the Gamma increment is not usable information

The Gamma family never enters any Model Confidence Set (C6's best cell: LightGBM with
NO option data). On C4c the increment collapses and reverses under out-of-evaluation
recalibration (calibration repair); on C6 it survives but its daily size tracks
baseline bias (R² 0.66). Against HAR/HARQ baselines the B2 increment is null-to-negative.
Economically: $0.02–0.09 per window per $100k toy notional in calibrated families —
and the spectacular numbers are miscalibration expressed in dollars.

## 5. The positive that is real (exploratory, labeled)

Total B0→B2: significantly positive in **5/5 families** (2024-A; 4/5 in 2024-B) and in
**both independent families in both 2025 eras** (+0.009..+0.057), surviving
HAR-augmented baselines (Gate 12). Channel: option state. Counter-sign stated: the
B1v3 feature redesign era. Fades to null by 2026 — decay measured at −0.0277/yr
(wild p 1e−04), families converging to ≈ +0.005.

## 6. Mechanism probes all point the same way

Not event weeks (effect survives their removal; calmest window has the largest effect).
Not microstructure (AC(1)-corrected target changes nothing). Not selection (97.4%
inclusion; IPW moves the 4th decimal). Not earnings (anti-concentrated). Not one
feature (no group carries it). Flat horizon term structure. Conclusion: era-bound
informativeness, cause (market vs provider) honestly uncharacterised.

## 7. PIT assumptions are measured, not assumed

Bar-label semantics (A001): FMP = Massive exactly under identical labels across three
eras — retired, with a standing tripwire test. Trade-tape availability (A002): live
latency campaign running nightly with pre-stated thresholds (decision 57: P95 vs 60s,
5% backfill bound, 1% revision); historical tapes carry a permanent stated residual.

## 8. [PHASE8] The prospective endpoint

30/30 sessions complete 2026-08-29; frozen method hash 87c818be; ex-ante predictions on
record (+0.005 both families, CIs crossing zero); TOST bound 0.005035 adequately powered
for the primary. Positive above MDE in both families → first global prospective claim.
Null → affirmative evidence of absence, confirming the measured decay by precommitment.

## 9. Contribution

(1) A preregistered prospective null (and a second, TOST-armed read) at an intraday
horizon under strict PIT discipline. (2) A scope refinement of IV-informativeness at 30
minutes. (3) Patton (2011) demonstrated in the field: a robust-looking increment living
inside a miscalibrated family, quantified. (4) The reusable fail-closed PIT /
preregistration / studentized-inference infrastructure.

## 10. One sentence

Option-market information was real and model-robust in 2024–2025, was never an
exploitable activity edge, and is measurably gone by 2026 — and every step of that
sentence is preregistered, hashed, or replicated.

---

# Q&A pack v2 (10 answers, current as of 2026-08-18)

**Q1 Forking paths — five campaigns after a null?** Enumerated, moratorium imposed
(decision 52), and now globally Holm-corrected: 21/36 registered contrasts survive at
5%. The clean answer is the second prospective read; its interpretation was fixed
before the data exist.

**Q2 Isn't the Gamma effect just calibration repair?** On C4c, yes — it reverses under
recalibration. On C6 it survives both fitting methods but tracks daily baseline bias
(R² 0.66). That sample-dependence is reported as-is; it is why no global claim rests on
the increment.

**Q3 Does anything beat a proper HAR?** The B2 increment does not (null-to-negative).
The *total* option-information contribution does, in both independent families, in both
2025 eras (Gate 12) — exploratory label, stated counter-sign.

**Q4 Why did the effect disappear?** Measured decay −0.0277/yr; not regime composition
(Gate 6), not microstructure (7), not selection (8), not earnings or any single feature
(9). Market-change vs provider-change is honestly open; the live latency campaign
narrows the provider side going forward.

**Q5 Your PIT assumptions are just assumptions.** A001 is measured (exact
cross-provider agreement, tripwire). A002 is being measured live with pre-stated
thresholds (decision 57); historical tapes carry a permanent, stated residual.

**Q6 n=30 sessions — power?** Achieved MDEs are reported next to every null (tree
family 0.0048 at n=30; TOST at 0.005035 adequately powered). Gelman-Carlin analysis
shows the LightGBM reversals are not low-power artifacts.

**Q7 Why QLIKE?** Standard for variance forecasts; but per Patton (2011) it rewards
calibration — which is exactly what our family-dependence demonstrates, and why
Mincer-Zarnowitz recalibration and a noise-robust target are part of the evidence.

**Q8 Economic significance?** Minuscule in calibrated families ($0.02–0.09 per window
per $100k toy notional). We claim information content, never profitability; the toy
numbers exist to give "positive" a magnitude.

**Q9 What if Phase 8 is positive? / null?** Positive above MDE in both families: the
first global prospective claim, reported under the frozen decision rules. Null: TOST
makes it affirmative evidence of absence and confirms the decay — precommitted before
the read. Both endpoints are written down already.

**Q10 What's the single biggest limitation?** Era-boundedness with uncharacterised
cause, on a six-asset mega-cap universe — stated in the threats matrix (row 13–14) and
in the conclusion; Phase 9 (total-contribution prospective design) is the registered
future work.
