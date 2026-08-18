# Block 8 — the model ladder over the four contrasts of decision 65

**Status:** `EXECUTED — 2026-08-19` · label `EXPLORATORY_MECHANISM_DISCOVERY`
**Artifact:** `artifacts/rp2_block8_ladder/ladder.json`
(`ladder_sha256 = 24588460c266054eafa19206542292cea8cce427e5b468f9c5814802904304e4`)
**Code:** `src/mds650/rp2/ladder.py`, `scripts/rp2_block8_ladder.py`
**Tests:** `tests/unit/test_rp2_ladder.py` (16 tests)

---

## 1. Design

Six families × four nested information sets × two universes, all on **identical rows**, with
the five estimands registered by decision 65. Fitted on the first 60 % of each universe's
sessions, scored on the rest, split by session and never by row.

| Universe | Origins | Train | Test | Sessions | Features B0 / B0+B1 / B0+B2 / B0+B1+B2 |
|---|---|---|---|---|---|
| D | 89,889 | 53,810 | 36,079 | 230 | 19 / 38 / 69 / 88 |
| V | 31,131 | 18,688 | 12,443 | 80 | same |

**Level 1** log-OLS, ridge-log, Gamma GLM, Tweedie GLM. **Level 2** additive B-spline (a GAM
in the additive sense — no interactions, which is what makes it a distinct family from a
tree) and LightGBM. **Level 3** empirical-Bayes partial pooling of per-asset offsets.
**Level 4** (DeepSets / temporal convolution / transformer / neural Hawkes) is **NOT_RUN**:
the program gates it behind a demonstrated tabular failure to capture the signal, and no
deep-learning stack is installed. Its absence is reported, not faked.

CatBoost and Explainable Boosting Machine are likewise not installed; LightGBM and the
spline additive model cover the tree and smooth-additive families the program names.

## 2. Primary table — raw ΔQLIKE (positive favours the expanded set)

### Discovery

| Model | Δ_B1 | Δ_B2\|B1 | Δ_B2\|B0 | Δ_Total | Δ_Interaction |
|---|---|---|---|---|---|
| log-OLS | **+0.00303** [+0.0004,+0.0058] p=0.019 | −0.00027 | −0.00096 | +0.00275 | +0.00068 |
| ridge-log | +0.00303 p=0.018 | −0.00026 | −0.00092 | +0.00277 | +0.00066 |
| Gamma GLM | +0.00121 ns | −0.00112 | −0.00115 | +0.00008 | +0.00003 |
| Tweedie GLM | −0.00177 ns | −0.00113 | −0.00200 | −0.00290 | +0.00087 |
| spline additive | +0.00446 ns | **−0.00472** p=0.006 | −0.00075 | −0.00026 | −0.00397 |
| LightGBM | −0.00176 ns | **+0.00323** p=0.039 | −0.00008 | +0.00147 | +0.00331 |

### Validation

| Model | Δ_B1 | Δ_B2\|B1 | Δ_B2\|B0 | Δ_Total | Δ_Interaction |
|---|---|---|---|---|---|
| log-OLS | −0.00161 | +0.00002 | +0.00003 | −0.00159 | −0.00001 |
| ridge-log | −0.00159 | −0.00008 | −0.00003 | −0.00167 | −0.00005 |
| Gamma GLM | −0.00228 | +0.00028 | +0.00017 | −0.00200 | +0.00011 |
| Tweedie GLM | −0.00146 | −0.00072 | +0.00071 | −0.00218 | −0.00143 |
| spline additive | **−0.01841** p=0.001 | **−0.01503** p=0.001 | −0.00561 | **−0.03344** | −0.00942 |
| LightGBM | −0.00180 | −0.00506 | +0.00349 | −0.00685 | −0.00854 |

**Every contrast in validation is null or negative, in every family.** The spline additive
model collapses in V (B0 0.184 → B0+B1+B2 0.217) — 88 features expanded into a spline basis
on 18,688 training rows is simply overfitting, and it is reported rather than dropped.

### The premise correction of §0 was tested and did not rescue the null

Decision 65 was registered precisely because a weak isolated Δ_B1 need not imply the absence
of joint information. That possibility has now been measured: **Δ_B2\|B0 is null everywhere,
Δ_Total is null or negative, and Δ_Interaction is between −0.009 and +0.003 with no
consistent sign.** The interaction channel is not where the signal was hiding.

## 3. Recalibration changes the discovery picture, and only there

Block 4 found the baseline carries an era-dependent level bias whose sign flips between D and
V. Every contrast was therefore also computed after applying the training-period
Mincer-Zarnowitz correction to **both** models in each pair, which removes calibration
differences and leaves pure information differences.

| Δ_B2\|B1 | D raw | D recalibrated | V raw | V recalibrated |
|---|---|---|---|---|
| LightGBM | +0.00323 (p=0.039) | **+0.00511 (p=0.001)** | −0.00506 | −0.00544 |
| ridge-log | −0.00026 | **+0.00291 (p=0.011)** | −0.00008 | +0.00189 (ns) |
| log-OLS | −0.00027 | **+0.00275 (p=0.014)** | +0.00002 | +0.00202 (ns) |
| Gamma GLM | −0.00112 | +0.00194 (ns) | +0.00028 | +0.00224 (ns) |
| Tweedie GLM | −0.00113 | +0.00153 (ns) | −0.00072 | +0.00266 (ns) |
| spline additive | −0.00472 | +0.00159 (ns) | −0.01503 | −0.01690 (p=0.001) |

**In discovery, recalibration turns a null Δ_B2\|B1 positive in five of six families and
significant in three.** The reading is precise: adding B2 buys information *and* costs
calibration, and in the raw comparison the two roughly cancel. This is the mirror image of
the confound Gate 2 was built to catch — there, a gain was really calibration repair; here, a
real gain was being masked by calibration damage. Both directions are now measured.

**In validation the same operation changes nothing** — every recalibrated Δ_B2\|B1 is
insignificant (p ≥ 0.19), and LightGBM stays adverse. So the discovery-era effect is not
recovered out of era, only out of calibration.

Holm adjustment within each model's family of four contrasts leaves almost nothing standing
in raw terms: the only Holm-significant raw entries are the *adverse* spline results
(D 0.024, V 0.004).

## 4. Level 3 — hierarchical partial pooling

| Universe | QLIKE without pooling | with pooling | between-asset variance |
|---|---|---|---|
| D | 0.13773 | 0.13783 | 1.28 × 10⁻⁴ |
| V | 0.18462 | **0.18378** | 1.55 × 10⁻⁴ |

Per-asset heterogeneity is real but tiny, and pooling changes QLIKE in the fourth decimal.
Cross-sectional heterogeneity is **not** a hidden channel for the effect.

## 5. Advance rule

**"Selection only in D/V": PASS** — no sealed cohort was touched, and no specification was
chosen on anything but D and V.

**Substantive verdict: the option information sets do not improve RV30 forecasts out of
sample.** With a full arbitrage-aware surface, 52 microstructure features, six model
families, four contrasts, an interaction term and a calibration correction, the best honest
summary is:

* discovery: a positive Δ_B2\|B1 of about +0.003 to +0.005 QLIKE, visible mainly after
  recalibration, family-dependent in raw terms;
* validation: nothing, in any family, in any contrast, raw or recalibrated.

Taken with Block 7 — where B2 is highly significant under orthogonalisation — the joint
statement is that **B2 carries real but economically negligible incremental information**:
§1 explanation 5 (aggregation destroyed it) is confirmed as a mechanism, and §1 explanation 6
(too small to matter) is confirmed as the consequence.
