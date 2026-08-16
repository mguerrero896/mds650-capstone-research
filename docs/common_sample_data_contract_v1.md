# Common-sample data contract v1

## Canonical row

Primary key:

```text
origin_id = asset | session_date | forecast_origin_utc
```

The 25-session local evidence contains 14,200 nominal rows: 11,360
`CALIBRATION` (20 sessions) and 2,840 `PILOT` (5 sessions), eight assets and
five-minute origins. After B0/RV30 structural validation, 10,400 calibration
rows and all 2,840 pilot rows remain availability-aware; 960 calibration rows
are excluded for missing lag/target structure. All rows are regular XNYS session
rows with UTC and New York timestamps. The target is RV30 with 31 prices and 30
future log returns.

## Required artifacts

- `common_matrix_strict_25d.parquet`: B0, B1Q and B2 all valid and non-missing.
- `common_matrix_available_25d.parquet`: valid B0/RV30 rows with explicit
  provider missingness for B1Q/B2.
- `common_matrix_targets_25d.parquet`: target-only view.
- `common_matrix_exclusions_v1.parquet`: one reason code per excluded row.
- `feature_lineage_v1.csv`: field-level source and availability lineage.

The strict view has 9,589 rows. The availability-aware view has 13,240 rows;
960 nominal rows fail the B0 lag/target structural requirements. Strict rows
are sorted by `origin_id`, unique, and preserve `sample_role`.

## Information-set contracts

### B0

Lagged one-minute FMP close/volume/return features and session controls. A raw
bar is eligible only under the conservative `raw + 1 minute` convention. No
target close or future bar is a predictor. Missing lag features are explicit and
are not replaced with zero.

### B1Q

Massive historical contracts and quotes. Required quote conditions are
`sip_timestamp <= forecast_origin`, positive bid, ask greater than bid, approved
quote age and relative spread. The as-of join is performed locally after a
contract-day extraction. ATM IV, skew and term-structure completeness are
component flags; no component is imputed to force a benchmark.

### B2

Continuous Full Tape aggregates are built from rows whose
`max(executed_at, created_at) <= origin - 60 seconds`. Cutoffs of 120 and 300
seconds are sensitivity views. Provider cumulative fields are not trusted as
point-in-time accumulators. All sums, counts, shares and concentration measures
are recomputed from eligible rows. `unusual_event` is not calibrated in this
phase and `option_activity_present` is not an unusualness label.

## Missingness and exclusions

`common_matrix_exclusions_v1.parquet` uses explicit codes including
`B0_INVALID_OR_TARGET_INVALID`,
`B1Q_PRIMARY_QUOTE_OR_IV_QUALITY_FAILURE` and
`B2_PRIMARY_PIT_RECHECK_FAILURE`. Structural absence, quote failure, stale quote,
calculation failure and PIT failure remain distinguishable in source columns.
No interpolation, statistical imputation, artificial balancing or nearest-
neighbour join is allowed. Rolling features reset at each session boundary.

## Calibration/pilot separation

Calibration rows may supply future trailing parameters. Pilot rows only receive
parameters fitted on calibration rows. The rebuild records
`pilot_transformations_fitted_on_calibration_only=true`; no unusualness score is
used as a primary predictor in this gate.

## Acceptance checks

The contract is checked by `tests/unit/test_phase4a_common.py`, the existing
provider/pilot contract tests, and the Phase 4A artifact tests. Any duplicate
ID, post-origin predictor, target/predictor overlap or non-deterministic row
ordering fails the gate.
