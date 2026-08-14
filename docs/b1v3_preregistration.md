# B1v3 preregistration

This document freezes the independent B1v3 confirmation before any RV30, QLIKE, prediction, loss or result payload is opened.

- Preregistration SHA-256: `e538ad0052190fc502b0441fed9d5b17f27b0db40d6061860a57e83e6a55f99d`
- Common predictor panel SHA-256: `a95d905602f7782679fc7e22025bd4aa828224cb84b86048ec8e3a23c0467a31`
- Training sessions: 60
- Confirmation sessions: 30
- SAFE_TO_EVALUATE_B1V3: NO
- Confirmation reads: 0
- Registered signs retained: positive, null and negative

## Frozen information sets

- B0: 12 underlying/market controls.
- B1v3a: B0 plus the three frozen ATM-variance features.
- B2: B1v3a plus the exact nine frozen trade-derived activity features.

Primary contrasts are `QLIKE(B0)-QLIKE(B1v3a)` and `QLIKE(B1v3a)-QLIKE(B2)`. Gamma GLM is confirmatory; fixed Gamma-objective LightGBM is robustness. QLIKE is primary, MAE/RMSE descriptive, uncertainty is 10,000 paired whole-day bootstrap draws, and Holm covers exactly both global contrasts.

## Exact development sessions (60)

```text
2024-08-02
2024-08-05
2024-08-06
2024-08-07
2024-08-08
2024-08-09
2024-08-12
2024-08-13
2024-08-14
2024-08-15
2024-08-16
2024-08-19
2024-08-20
2024-08-21
2024-08-22
2024-08-23
2024-08-26
2024-08-27
2024-08-28
2024-08-29
2024-08-30
2024-09-03
2024-09-04
2024-09-05
2024-09-06
2024-09-09
2024-09-10
2024-09-11
2024-09-12
2024-09-13
2024-09-16
2024-09-17
2024-09-18
2024-09-19
2024-09-20
2024-09-23
2024-09-24
2024-09-25
2024-09-26
2024-09-27
2024-09-30
2024-10-01
2024-10-02
2024-10-03
2024-10-04
2024-10-07
2024-10-08
2024-10-09
2024-10-10
2024-10-11
2024-10-14
2024-10-15
2024-10-16
2024-10-17
2024-10-18
2024-10-21
2024-10-22
2024-10-23
2024-10-24
2024-10-25
```

## Exact one-read confirmation sessions (30)

```text
2024-10-28
2024-10-29
2024-10-30
2024-10-31
2024-11-01
2024-11-04
2024-11-05
2024-11-06
2024-11-07
2024-11-08
2024-11-11
2024-11-12
2024-11-13
2024-11-14
2024-11-15
2024-11-18
2024-11-19
2024-11-20
2024-11-21
2024-11-22
2024-11-25
2024-11-26
2024-11-27
2024-11-29
2024-12-02
2024-12-03
2024-12-04
2024-12-05
2024-12-06
2024-12-09
```

The separate access ledger may transition to YES only after the source-bound panel, tests, Ruff, Mypy, coverage, JSON Schema, leakage and disk gates all pass. This preregistration itself is immutable.
