# Point-in-time options information for forecasting next-30-minute realised variance

**Final capstone report — DRAFT v2, full prose (2026-08-18)**

> Status: `PROSE_COMPLETE_PENDING_D003_AND_PHASE8`. Supersedes the v1 skeleton. Open
> slots: [D003] institutional formatting/ethics wording; [PHASE8] the 2026-08-29 read;
> [PHASE9-NOTE] optional status line at submission. All claims bounded by decision 53;
> exploratory findings carry their labels and the `positive_findings_v1.md` citation
> rule. Numbers are drawn only from the frozen artifacts cited in each section.

## Title page — [D003]

## Abstract

This project asks whether option-market information improves out-of-sample prediction
of the realised variance of large US equities over the next thirty minutes (RV30). At
five-minute origins during the regular New York session, three nested information sets
are compared on identical origins: underlying and market state (B0); B0 plus
conventional option state such as at-the-money implied variance (B1); and B1 plus
point-in-time option-trade activity (B2). Six liquid equities form the outcome universe.
Under preregistered, hash-sealed, one-read evaluation gates, the prospective holdout
returned null for both nested contrasts. Retrospective evaluations show a recurring
positive B2 increment that is specific to a miscalibrated confirmatory model family and
is rejected by every usability probe; by contrast, the total option-information
contribution is positive across independent model families through most of the sample
period, is concentrated in option state, survives HAR-augmented baselines, and decays
measurably to zero by 2026. Both foundational point-in-time assumptions were converted
from registered assumptions into measurements. A second prospective, equivalence-armed
read closes the study. The contribution is a rigorously bounded answer — where, when,
and for whom option information mattered — together with reusable point-in-time
research infrastructure. No causal, directional, or profitability claim is made.

## 1. Introduction

Short-horizon realised-variance forecasting sits at the intersection of two mature
literatures: autoregressive realised-variance modelling, in which heterogeneous
lag structures (HAR-type models) set a demanding baseline, and options-based
volatility forecasting, in which option prices are treated as forward-looking
information. Between them lies a specific and surprisingly under-tested question:
does option-trade *activity* — what was just traded, over and above what option
*prices* already say — add incremental predictive information at intraday horizons,
when the forecaster is restricted to information that was operationally available at
the moment of the forecast?

That restriction is the heart of this project. Most existing evidence on
options-based volatility prediction is daily-or-longer horizon and is silent about
operational availability: whether the researcher's data existed, in the form used, at
the moment the forecast pretends to have been made. This project builds a
point-in-time (PIT) panel from three commercial providers under explicit,
registered availability rules; freezes every estimand, model, and stop rule before
outcomes are read; and treats a preregistered null as a publishable answer rather
than a failure. The research question is strictly predictive-informational: does the
expanded information set reduce out-of-sample QLIKE loss for RV30 on identical
forecast origins? No claim about trader intent, direction, causality, or
profitability is in scope.

The study's arc, stated up front: the only prospective preregistered test returned
null; a statistically strong retrospective increment turned out to be a property of a
miscalibrated model family rather than of the information; and the honest positive —
model-robust, exploratory, and era-bound — is that option *state* carried real
incremental information for intraday variance through 2024 and 2025 and measurably
stopped doing so. The report defends each leg of that sentence in turn.

## 2. Literature review

[D003 note: reference list frozen only after Corsi (2009) and the two remaining
full texts are retained; ledger-verified sources only.]

Four strands frame the design and, importantly, made predictions that the data could
contradict. First, the HAR tradition following Corsi (2009) holds that realised
variance is dominated by its own multi-horizon history; any candidate predictor must
beat a heterogeneous autoregressive baseline, not merely a naive one. This project's
results agree completely: its HARQ implementation is the best baseline in its ladder,
and the candidate activity block adds nothing to it on development data (§5.4).

Second, the implied-volatility informativeness literature (Christensen and Prabhala
1998; Blair, Poon and Taylor 2001; Busch, Christensen and Nielsen 2011) documents that
option prices predict future realised volatility at daily and longer horizons. This
project refines the scope of that result rather than contradicting it: at a
thirty-minute horizon with rich lagged-intraday-RV controls, the ATM-implied-variance
level adds no reliable value under the frozen campaign designs — while the same
option-state block is precisely where the model-robust exploratory gains concentrate
under a uniform ladder (§5.5). The reconciliation is horizon and baseline richness,
and it is one of the report's clearest findings.

Third, the options-activity and informed-trading strand (Easley, O'Hara and
Srinivas 1998; Pan and Poteshman 2006) motivates B2: if some option trades carry
private information, recent activity should predict near-term variance, plausibly
concentrated around information events. The data reject the economically motivated
version of this hypothesis in the current era: the activity increment is invisible to
calibrated models, anti-concentrated around earnings, and flat across horizons (§5.3,
§6).

Fourth, Patton (2011) and Patton and Sheppard establish that QLIKE-based forecast
rankings are trustworthy only for conditionally unbiased proxies and well-calibrated
forecasts. This strand turned out to be the report's interpretive key: the headline
"model-family-dependent" complication is not an anomaly but an anticipated
consequence of comparing a miscalibrated family with a calibrated one under QLIKE
(§5.3). Recent intraday work (Caporin et al. 2024; Puke and Schweikert 2026; Michael
et al. 2025) completes the positioning: options-driven machine-learning gains reported
at daily horizons do not automatically transfer intraday under strict PIT rules.

## 3. Data and point-in-time discipline

Three commercial providers feed the panel. FMP supplies one-minute underlying bars,
from which both the target and the lagged realised-variance features are built.
Massive (a Polygon-compatible service) supplies historical option quotes for the
option-state block. Unusual Whales supplies the option-trade tape for the activity
block. Raw licensed data live outside the repository; the committed evidence consists
of code, schemas, preregistration manifests, SHA-256 hashes, access ledgers, and
aggregate artifacts — controlled auditability rather than raw redistribution.

The target is unannualised RV30: the sum of thirty squared one-minute log returns
from thirty-one consecutive closes following each forecast origin. Origins lie on a
five-minute grid inside the regular XNYS session. The outcome universe is six liquid
mega-cap equities (AAPL, AMZN, META, MSFT, NVDA, TSLA) with SPY and QQQ as market
controls — a deliberate, stated scope limitation (§7).

Two availability assumptions underpinned the original design, and both have been
moved from assumption to measurement. Bar-label semantics (A001): whether a bar
labelled 09:35 is available at 09:35 or 09:36 governs every feature and target
window. A cross-provider reconciliation downloaded the same one-minute bars from FMP
and Massive for ten stratified sessions spanning 2024–2026: under identical labels the
providers agree with a median relative close difference of 3.1e−06 — two orders of
magnitude tighter than the shifted alternative — and the reconstructed thirty-minute
lagged RV matches the frozen panel column with log-correlation 1.0000. A001 is
retired, and a standing tripwire test fails the suite if a future acquisition breaks
the agreement. Trade-record availability (A002): the tape's `created_at` field is
used as an availability proxy with a registered sixty-second cutoff. A live
measurement campaign now polls the flow channel intraday, records local receipt
timestamps, and reconciles them against the historical tape seven days later, under
thresholds fixed before the first reconciliation existed (decision 57): live-era P95
latency versus the sixty-second cutoff, a five-percent backfill upper bound, and a
one-percent revision rate. [Update at submission with the accumulated reconciliation
statistics.] The historical 2024–2025 tapes remain assumption-based; that residual is
permanent and is carried in the threats matrix rather than hidden.

Evaluation samples span four eras with frozen feature panels: 2024-08 to 2024-12
(ninety sessions), 2025-03 to 2025-07 (ninety), 2025-08 to 2026-03 (one hundred and
sixty), and 2026-03 to 2026-07 (eighty development sessions), plus the ten-session
prospective holdout of July 2026 and the thirty-session prospective Phase 8 window of
July–August 2026.

## 4. Methodology

The design compares nested information sets on identical origins, so every contrast
is a paired comparison free of sample-composition differences. The primary loss is
QLIKE, standard for variance forecasts and sensitive to calibration — a property that
becomes substantive in §5.3. The confirmatory lineage fixed a regularised Gamma GLM
with a fixed LightGBM challenger; the report's later analyses add the field-standard
baselines the original ladder lacked: an intraday HAR at the thirty-minute horizon
(lagged thirty-minute, session-to-date, daily and weekly RV components with intraday
periodicity terms) and HARQ (realised-quarticity attenuation), fitted by log-OLS with
lognormal smearing, validated on development data only.

Governance is the methodological core. Every campaign froze its question, estimands,
universe, session lists, models, and stop rules in hash-sealed preregistration
manifests before outcomes were read; sealed holdouts are read exactly once under
access-ledger control; a binding claims hierarchy (decision 53) orders every report:
the prospective null first, retrospective evidence labelled by its exposure history,
and the bare word "confirmed" forbidden while the confirmatory arrays are empty.

Inference was hardened after an audit found the original sign-bootstrap p-values
saturated at their resolution floor. Every registered contrast now carries: a cluster
t on daily loss differentials, a Newey–West (Diebold–Mariano) statistic with
automatic lag, a wild cluster bootstrap-t (Rademacher and Webb weights, 9,999
replications), serial-dependence diagnostics with moving-block alternatives where
lag-one autocorrelation is material (it reaches +0.62 exactly where the headline
lives), per-campaign Hansen–Lunde–Nason Model Confidence Sets, a formal test of the
model-family interaction, Gelman–Carlin design analysis for the challenger, and a
single global Holm correction across all thirty-six registered post-null contrasts —
stated as a conservative bound, since no retrospective correction is exact for a
data-dependent sequence.

## 5. Results

The order below is binding (decision 53).

### 5.1 The prospective preregistered test is null

The July 2026 holdout — sealed before collection, read once — returned null for both
nested contrasts under both families: Gamma B1−B0 = −0.0071 (Holm p 0.76), B2−B1 =
+0.0006 (p 0.87); LightGBM B1−B0 = −0.0114 (p 0.012, adverse), B2−B1 = −0.0005
(p 0.52). Under the studentized machinery the conclusion is unchanged. With ten
session clusters the achieved detectable effect is reported beside the null: the test
was honest, not decisive, which is why a second prospective read exists.

### 5.2 [PHASE8] The second prospective read

[Insert 2026-08-29 outcome under the frozen decision rules and the pre-read TOST
amendment: equivalence bound 0.005035, ex-ante predictions ≈ +0.005 for both family
proxies, adequately powered for the tree-family primary. A positive above the MDE in
both families supports the first global prospective claim; a null is affirmative
evidence of absence and, by precommitment, confirms the measured decay.]

### 5.3 The retrospective Gamma increment is real as a statistic and rejected as information

Across the retrospective campaigns the confirmatory Gamma family shows a recurring
positive B2-over-B1 increment: +0.034 on the corrected 2025 replication, +0.053 on
the late-2024 confirmation, +0.035 to +0.078 on the exploratory 2024 blocks — each
surviving Newey–West correction, the wild bootstrap, and the global Holm family
(adjusted p 0.0036 for the binding sample). The increment also survives five
registered timing sensitivities, event-week removal, an AC(1) noise-robust target,
and inverse-probability selection reweighting (inclusion is 97.4 percent on the
binding sample; weights move the fourth decimal).

Every probe of usability, however, points the same way. The fixed LightGBM challenger
is null or significantly reversed on the same origins — and Gelman–Carlin analysis
shows this is not a power artifact. The model-family interaction, tested formally for
the first time, is significant in every retrospective sample and null in the
prospective holdout. The Gamma family never enters any Model Confidence Set; on the
binding sample the best cell is LightGBM with no option information at all. Under
out-of-evaluation Mincer–Zarnowitz recalibration the increment collapses and reverses
on one binding sample (calibration repair) and survives on the other while its daily
magnitude tracks baseline bias with R² 0.66. Against HAR and HARQ baselines the
increment is null-to-negative. Economically, in calibrated families it is worth two
to nine cents per thirty-minute window per hundred thousand dollars of toy notional;
the only spectacular numbers in the project are the miscalibrated family's baseline
explosion expressed in dollars. Patton (2011) predicted exactly this failure mode:
QLIKE rewards calibration, so features that repair a biased baseline masquerade as
information. The registered verdict — model-family-dependent, no global claim —
stands, now with its mechanism quantified.

### 5.4 Field-standard baselines and the activity block

On development data the HARQ implementation is the strongest baseline of the ladder
(pooled out-of-sample QLIKE 0.18338), and adding the nine activity features to HAR or
HARQ makes forecasts marginally worse (−0.0010 and −0.0009, both ns). Combined with
the challenger's nulls and the localization probes below, the conclusion is blunt:
option-trade activity, as engineered here, is not incremental information in the
current era.

### 5.5 The exploratory, model-robust positive: option information in total

(Label: EXPLORATORY_DESCRIPTIVE, decision 56; citation rule applies.) When the
estimand is the *total* option-information contribution — B0 to B2, dominated by
option state — the picture inverts. On the 2024 blocks the total is significantly
positive in five of five model families (up to +0.086 for B0→B1a under HAR-RV) and
four of five on the second block. Under one uniform ladder run identically over the
four era panels, the total is positive in both genuinely independent families
(smooth-linear and gradient-boosted tree; a same-day review recorded that the ridge
variant duplicates the smooth family and does not count separately) in both 2025 eras:
+0.015/+0.013 in 2025H1 and +0.010/+0.021 in 2025H2–2026Q1 (wild p down to 4e−10, one
hundred and sixty sessions), surviving HAR-augmented baselines in both families
(+0.057/+0.017 and +0.020/+0.009). The stated counter-sign: the late-2024 era under
the redesigned B1v3 feature set, where the option-state block subtracted value for
smooth families. By the 2026 development era the total fades to null-to-borderline,
and in the prospective holdout it is null.

### 5.6 The decay is measured, not narrated

Pooled daily differentials across all campaigns decline at −0.0277 per year for the
Gamma-specific increment (wild p 1e−04) while the tree-family series rises from
adverse toward zero at +0.0097 per year: the families converge to approximately
+0.005 at the Phase 8 window. The decay is not explained by regime composition (the
calmest window carries the largest effect; event-week removal strengthens two of
three contrasts), microstructure (AC(1) is at most |0.033| and the noise-robust
target changes nothing), selection, earnings proximity (the effect anti-concentrates
around earnings), any single feature group, or horizon structure (flat across
RV15/RV30/RV60). Market-change versus provider-change remains honestly open.

## 6. Discussion

Three statements survive every probe. First, option-market information was real for
intraday variance prediction: model-robust in total, concentrated in option state,
economically modest, and present across two years of samples from three independent
acquisition paths. Second, it was never the activity edge the project set out to
find: the B2 increment fails every usability test, and its statistically strongest
appearances are exactly where Patton's calibration critique predicts mirages. Third,
whatever produced the 2024–2025 informativeness faded on a measured trajectory to
zero by 2026 — a finding with its own value, since time-varying informativeness is
invisible to single-window studies and is precisely what strict PIT discipline
exists to detect honestly.

The two-sided design of the closing read deserves emphasis. Because the equivalence
bound, ex-ante predictions, and the precommitment for the underpowered branch were
recorded before the data exist, the [PHASE8] outcome is informative whatever its
sign — the study cannot end in "inconclusive". A successor protocol (Phase 9,
decision 58, frozen and collecting) points the same machinery at the total-contribution
estimand where the exploratory evidence is strongest. [PHASE9-NOTE at submission.]

## 7. Threats to validity

Fourteen named threats, each with evidence, mitigation, and residual, are maintained
in the threats matrix; the report inherits them wholesale rather than curating the
comfortable ones. Retired: bar-label semantics (measured, two providers, tripwire);
microstructure proxy error (bounded at an order of magnitude below the effects);
saturated inference (replaced throughout). Bounded: forking paths (enumerated,
moratorium, global Holm as a conservative bound — with the honest caveat that no
retrospective correction is exact); calibration attribution (sample-dependent, with
the bias-covariance channel quantified); selection (negligible on the binding sample,
one deferred replication). Permanent and stated: the historical tapes'
availability assumption; the six-asset mega-cap universe; the era-boundedness with
uncharacterised cause; and the single-machine custody of the prospective stores, an
accepted risk recorded by owner decision.

## 8. Conclusion and contribution

Does point-in-time options information improve out-of-sample RV30 forecasts? For the
activity increment the answer is no — prospectively null, family-dependent in
retrospect, and rejected by every usability probe. For option information in total
the answer is: it did, robustly across model families, through 2024 and 2025; it
faded measurably to zero; and the closing prospective read adjudicates the endpoint
under rules fixed in advance. Four contributions: (1) a preregistered prospective
null, and a second equivalence-armed read, at an intraday horizon under strict PIT
discipline; (2) a scope refinement of implied-volatility informativeness at the
thirty-minute horizon under rich intraday controls; (3) a field demonstration,
quantified, of Patton's calibration critique — a robust-looking edge living inside a
miscalibrated family; and (4) reusable infrastructure: measured availability
semantics with standing tripwires, hash-sealed one-read governance, and studentized
day-clustered inference for paired forecast evaluation.

## 9. Ethics and reproducibility — [D003 wording]

No human participants. Licensed raw data and credentials are never redistributed or
committed. Reproducibility for unlicensed examiners is provided as controlled
auditability: code, schemas, sanitised fixtures, SHA-256 manifests, access ledgers,
and aggregate outputs, under a locked Python 3.12 environment and a
thousand-test suite. Vendor labels are treated as observed events, never as trader
intent; no informed-trading, causal, or profitability claim is made anywhere in the
report.

## Appendices

A. Campaign register and contrast tables (`docs/results_reconciliation_v2.md`).
B. Studentized inference tables (`artifacts/gate1_inference/`).
C. Gate reports 1–12 (`docs/INDEX.md`).
D. Economic-significance tables (`artifacts/economic_significance/`).
E. Preregistration and freeze hashes (artifact manifests; Phase 9 freeze
   `artifacts/phase9/protocol_freeze.json`).
F. Supervisor feedback mapping [D004: confirmed, or labelled "unverified paraphrase"].
