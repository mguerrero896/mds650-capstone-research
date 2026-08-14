# B1v3 implementation and one-read confirmation handoff

**Date:** 2026-08-14

**Branch:** `codex/b2-defense-readiness-20260811`

**Implementation commit:** `1fc19dd`

**Research-only status:** no trading, P&L, deployment, email or external publication

## 1. Executive decision

The approved B1v3 specification was implemented end to end and evaluated once on the frozen
30-session confirmation block after a 60-session development freeze.

The binding result is **`POSITIVE_BUT_NOT_GLOBALLY_CONFIRMED`**:

- **B1v3a versus B0:** the ordinary ATM option-state variables did **not** improve RV30 forecasts.
  Both Gamma and LightGBM produced worse QLIKE than B0.
- **B2 versus B1v3a:** the nine trade-derived features produced a large, statistically significant
  and timing-stable improvement under the confirmatory Gamma model, but fixed LightGBM produced
  the opposite sign. B2 therefore has strong model-specific evidence, not a universal edge.
- The study is technically complete and scientifically informative. It does not establish a
  production trading advantage or model-independent economic value.

## 2. Frozen scientific design

| Item | Frozen contract |
|---|---|
| Target | RV30: origin close plus 30 consecutive future one-minute closes, producing 30 log returns |
| Development | 60 XNYS sessions, 2024-08-02 through 2024-10-25 |
| Confirmation | 30 previously frozen sessions, 2024-10-28 through 2024-12-09 |
| Outcome assets | AAPL, AMZN, META, MSFT, NVDA, TSLA |
| Market controls | SPY and QQQ |
| B0 | 12 point-in-time underlying/market features |
| B1v3a | B0 plus 30-day ATM log implied variance and exact 5/30-minute changes |
| B2 | B1v3a plus the nine preregistered trade-derived features |
| Confirmatory model | GammaRegressor; alpha selected using development only |
| Robustness model | Fixed-grid LightGBM |
| Primary metric | QLIKE |
| Inference | 10,000 paired whole-trading-day bootstrap resamples, seed 650 |
| Multiplicity | Holm correction over exactly two confirmatory contrasts |
| Materiality | MDE estimated from development only |
| Timing | FMP +1 minute primary; +2 minutes sensitivity; Massive 0/60/300 seconds; UW 60/120/300 seconds |

The preregistration is
`artifacts/b1v3_confirmation_preregistration/preregistration.json`, semantic SHA-256
`e538ad0052190fc502b0441fed9d5b17f27b0db40d6061860a57e83e6a55f99d`.

## 3. Data construction and common sample

The target-blind panel contains 38,664 scheduled forecast origins. Model evaluation uses only the
identical B0/B1v3a/B2 complete-case intersection; no feature is imputed to force coverage.

| Role | Scheduled origins | Common-complete origins | Explicitly excluded |
|---|---:|---:|---:|
| Development | 25,920 | 23,320 | 2,600 |
| Confirmation | 12,744 | 11,577 | 1,167 |
| Total | 38,664 | 34,897 | 3,767 |

Of the exclusions, 3,240 are the six early origins per asset-session for which a 30-minute regular-
session predictor history does not yet exist. They remain in the raw evidence with
`B0V2_UNDERLYING_HISTORY_MISSING`; they are not filled with premarket data or shorter windows.
The remaining 527 fail the nested B1v3a/B2 common-completeness gate. All three primary information
sets use exactly the same 34,897 origins.

Key target-blind identities:

- common predictor panel SHA-256:
  `a95d905602f7782679fc7e22025bd4aa828224cb84b86048ec8e3a23c0467a31`;
- Massive raw-payload inventory SHA-256:
  `7f89ec5ad0266a8c44a2a128a468f23954dd53c5c5b474b09979bf8856a30cc1`;
- B1v3 source-bound feature SHA-256:
  `c2576113060e1c994a49933b56cfea96740c00ec763ee02a453e96b499918f5d`;
- method-freeze semantic SHA-256:
  `2011c0a7292d899d2106e77710e95809fc3a7f412c8294bc850995f0e85adb26`.

## 4. Technical coverage and PIT controls

Before outcome access, B1v3 component coverage was:

| Benchmark | Global | Minimum asset | Minimum session tercile | Gate |
|---|---:|---:|---:|---|
| B1v3a: ATM state | 90.26% | 88.89% | 75.67% | PASS |
| B1v3b: ATM + skew | 84.93% | 78.12% | 73.11% | PASS |
| B1v3c: ATM + skew + term structure | 77.71% | 71.91% | 67.38% | PASS |

The nested invariants `B1v3c => B1v3b => B1v3a` pass globally and row by row. Massive processing
used 16,054 contract-day caches and 1,149,408 IV-attempt rows, with zero selected quote after its
registered origin/cutoff. FMP +2-minute and Massive 60/300-second matrices were reconstructed
before any target access. UW sensitivities preserve the registered `created_at` operational proxy;
they do not relabel it publication time.

## 5. One-read confirmation results

Positive contrast means the expanded information set has lower QLIKE.

| Model | Contrast | Estimate | 95% paired-day interval | Holm p | Training MDE | Conclusion |
|---|---|---:|---:|---:|---:|---|
| Gamma confirmatory | QLIKE(B0) − QLIKE(B1v3a) | -0.05030242 | [-0.06532898, -0.03593304] | 0.00039996 | 0.01890532 | B1v3a is worse than B0 |
| Gamma confirmatory | QLIKE(B1v3a) − QLIKE(B2) | +0.05339190 | [0.03857849, 0.06817332] | 0.00039996 | 0.01304182 | Positive, significant and above MDE |
| LightGBM robustness | QLIKE(B0) − QLIKE(B1v3a) | -0.01620932 | [-0.03410386, -0.00510505] | descriptive | 0.01890532 | B1v3a is worse than B0 |
| LightGBM robustness | QLIKE(B1v3a) − QLIKE(B2) | -0.00745281 | [-0.01218466, -0.00355039] | descriptive | 0.01304182 | B2 is worse than B1v3a |

The result manifest is `artifacts/b1v3_confirmation/result.json`, semantic SHA-256
`c80977d6128e403a308f0ad4552050083c3d79a0593af7dc94d97aecab740ced`.

## 6. Stability

Under Gamma, the B2 incremental estimate is positive for all six assets, all three session
terciles and all three volatility regimes. Asset-level intervals are wholly positive for AAPL,
AMZN, NVDA and TSLA; META and MSFT have positive point estimates with intervals crossing zero.
The Gamma B2 interval remains wholly positive under all five registered timing sensitivities.

Under LightGBM, B2 is negative globally, for all six asset point estimates, all three session
terciles, all three volatility regimes and every timing sensitivity. This systematic model
reversal is the sole failed condition preventing global confirmation of B2.

B1v3a is negative globally in both models. Under Gamma, only AAPL is positive by asset; under
LightGBM all six asset point estimates are negative. Its timing views are also wholly negative.

## 7. One-read integrity and recovery incident

The sole access ledger transitioned from zero to one confirmation read before FMP targets were
opened. The scientific run completed and wrote its three derived Parquet outputs, but the final
JSON serializer initially rejected the legitimate provenance field
`consumed_authorization_manifest_sha256` because the secret scanner prohibited the generic word
`authorization`.

No second target read and no second model fit occurred. A TDD recovery path accepted only the exact
consumed ledger and the three sealed derived outputs, revalidated target identity, recomputed the
registered inference, and wrote the missing JSON/report/index. Full evidence is in
`docs/recovery/b1v3_one_read_serialization_incident.md`.

## 8. Verification

Executed after the recovery change:

- focused B1v3 suite: **101 passed**;
- global suite: **931 collected; 919 passed; 12 skipped; 0 failed**;
- statement/branch coverage: **83.06%**, above the 80% gate;
- Ruff over `src scripts tests`: **PASS**;
- Mypy strict over `src scripts`: **181 source files, 0 errors**;
- result Draft 2020-12 JSON Schema: **PASS**;
- result semantic self-hash: **PASS**;
- five evidence-index file hashes: **5/5 PASS**;
- D: free space after execution: approximately **318 GiB**, above the 80-GiB gate.

Commands:

```powershell
uv run pytest -q --cov=mds650 --cov-report=term-missing --cov-fail-under=80
uv run ruff check src scripts tests
uv run mypy --strict src scripts
uv run python scripts/run_b1v3_pre_confirmation_quality.py --execute
uv run python scripts/seal_b1v3_access_ledger.py
uv run python scripts/run_b1v3_confirmation_once.py
uv run python scripts/run_b1v3_confirmation_once.py --finalize-sealed-outputs
```

The last command is incident recovery only; exclusive-create and consumed-ledger checks prohibit
its reuse after successful finalization.

## 9. Artifact map

| Purpose | Repository artifact | Large local artifact |
|---|---|---|
| Preregistration | `artifacts/b1v3_confirmation_preregistration/preregistration.json` | — |
| Method freeze | `artifacts/b1v3_confirmation_method_freeze/method_freeze.json` | `MDS650_B1V3_DATA_ROOT/evaluation/training_evaluation_panel.parquet` |
| Source-bound manifests | `artifacts/b1v3_confirmation_panel/` | `MDS650_B1V3_DATA_ROOT/predictors/` and cache/evidence roots |
| Access/quality | `artifacts/b1v3_confirmation/access_ledger_frozen.json`; `pre_confirmation_quality_gate.json`; `post_confirmation_test_report.txt` | quality logs mirrored in repository |
| One-read output | `artifacts/b1v3_confirmation/result.json`; `result_report.md`; `evidence_index.csv` | evaluation panel, primary forecasts and timing forecasts |
| Incident | `docs/recovery/b1v3_one_read_serialization_incident.md` | outer process logs under the restricted D: log root |

`MDS650_B1V3_DATA_ROOT` denotes `D:/MDS650/b1v3_confirmation`; personal absolute paths are excluded
from publishable artifacts.

## 10. Limitations and institutional wording

Safe wording:

> In the independent 30-session confirmation, ordinary ATM option-state information did not
> improve the underlying-market benchmark. The nine trade-derived activity features added
> statistically and materially significant RV30 forecasting information under the preregistered
> Gamma model and conservative timing sensitivities, but the effect reversed under LightGBM.
> Therefore, the evidence supports a model-dependent incremental B2 signal rather than a universal
> forecasting or trading edge.

Do not claim that B1 beats B0, that B2 is universally positive, that `created_at` is provider-
confirmed publication time, or that this forecasting result proves tradable profitability. A
future investigation may analyze why B2 interacts differently with Gamma and LightGBM, but it
must be labeled post-confirmation mechanism analysis and must not rewrite this result.
