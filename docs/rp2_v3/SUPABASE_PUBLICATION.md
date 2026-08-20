# Publishing RP2-v3 results

Every published number carries the run that produced it. The tables the RP2-v2 numbers live
in are left exactly where they are: a reader who followed a citation to one of them must
still find it.

## What the migration adds

`supabase/migrations/20260820170000_rp2_v3_versioned_results.sql`:

- six columns on `public.ingestion_runs` — `spec_version`, `branch_name`,
  `feature_registry_sha256`, `model_config_sha256`, `inference_config_sha256`,
  `common_mask_sha256`;
- `public.rp2_block_results`, `public.rp2_extension_results`, `public.rp2_power_results`
  and `public.rp2_contrast_results`, each keyed by `run_id` with a partial unique index
  admitting exactly one `is_current` row per subject;
- `api.current_rp2_block_results`, `api.current_rp2_contrasts`,
  `api.current_rp2_extension_results` and `api.current_rp2_power_results`, granted to
  `anon` and `authenticated`, over base tables that keep row-level security enabled and no
  policies of their own;
- `public.publish_rp2_v3(jsonb)` and `public.record_rp2_v3_failure(text, text)`, revoked
  from `anon` and `authenticated`.

The contrast table's columns are not nullable and are checked: `p_value` within `[0, 1]`,
`sessions`, `block_length`, `mde` and `equivalence_bound` strictly positive,
`common_mask_sha256` a 64-character hexadecimal digest, and `ci_low <= estimate <= ci_high`.
An estimate whose evaluation rows are unidentified cannot be checked by anyone, and a
nullable column is how that happens quietly.

## Publication is one transaction

`scripts/publish_rp2_v3_supabase.py` makes a single call to `public.publish_rp2_v3`, because
a function body is a transaction. Eight REST calls from a script can leave a run marked
`RUNNING` with half its results published and the previous run already stood down, and
nothing in the database would say which half is missing.

Inside the function, in order: the run row is inserted or reset to `RUNNING`; its inputs are
recorded; the previous current rows for the subjects being published are stood down; the new
rows are inserted as current; `rows_published` is set; the run is marked `PUBLISHED`. Any
failure raises, the transaction rolls back, and the script records the failure through a
separate call — a rollback leaves no trace by construction, so a rebuild that failed would
otherwise be indistinguishable from one that was never attempted.

Standing the previous rows down happens *before* the new ones claim to be current. The
partial unique index permits exactly one current row per subject, so the other order is a
constraint violation rather than a silent overwrite. That is the intent.

## What is published

Only the families the research contract decides on — `gamma_glm`, `ridge_log`,
`lightgbm_qlike` — and only aggregates: the run's identity, the digests of its inputs, one
row per block outcome and one row per nested contrast. No origin-level forecast, no raw
quote, no trade. A contrast without its `common_mask_sha256` is refused rather than
published.

## The dry run

The plan calls for `supabase db push --dry-run` before applying. The CLI needs a personal
access token or the database password, and neither is available in this environment; only
`SUPABASE_SERVICE_KEY` is. The equivalent was performed instead, and it is stronger in one
respect: the migration was executed against the live schema inside a transaction that was
then rolled back, so the real DDL met the real database.

Executed, with the section 17 acceptance queries inside the same transaction:

```text
new_run_columns:        6      the six columns on ingestion_runs
contrast_rows_total:    2      two publications of the same contrast
contrast_rows_current:  1      the partial index holds
current_run_id:         dryrun-b    estimate 0.005
superseded_run_id:      dryrun-a    the is_current flip works
rows_without_run_id:    0
orphan_lineage:         0
```

Afterwards, production was confirmed untouched:

```text
contrast_table        null
block_table           null
dryrun_runs_left      0
publish_function_left 0
```
