# Publishing RP2-v3 results

Every published number carries the run that produced it. The tables the RP2-v2 numbers live
in are left exactly where they are: a reader who followed a citation to one of them must
still find it.

## What the migration adds

`supabase/migrations/20260820170000_rp2_v3_versioned_results.sql`:

- seven columns on `public.ingestion_runs` — `spec_version`, `branch_name`,
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

A second transaction exercised the retry paths against the same live schema, because an
idempotent retry and a changed result set are the two things a republish can be:

```text
1 first publish              PUBLISHED
2 identical retry            ALREADY_PUBLISHED
3 retry, contrast removed    RP2_PUBLISH_CONTRAST_SET_CHANGED:dryrun-keyset
4 retry, block removed       RP2_PUBLISH_BLOCK_SET_CHANGED:dryrun-keyset
```

The third and fourth cases change no value the field comparisons can see: every row present
on both sides still agrees. Only comparing the whole key set distinguishes a retry of the
same result set from a submission of a different one.

Afterwards, production was confirmed untouched:

```text
contrast_table        null
block_table           null
dryrun_runs_left      0
publish_function_left 0
new_columns_left      0
```

A third transaction checked the lineage guards and the function's reachability:

```text
0 PUBLIC execute before revoke   true
1 PUBLIC execute after revoke    false
2 anon execute after revoke      false
3 lineage digest missing         RP2_PUBLISH_LINEAGE_INCOMPLETE:dryrun-lineage
4 no input inventory             RP2_PUBLISH_INPUTS_MISSING:dryrun-lineage
5 complete payload               PUBLISHED
6 block id stored                06
```

Line 0 is the reason line 1 is there: PostgreSQL grants `EXECUTE` on a new function to the
`PUBLIC` pseudo-role, so revoking from `anon` and `authenticated` left the inherited grant
in place and any unauthenticated caller could still reach the function, parse a payload and
take its advisory lock.

Line 6 is the block register's own identifier. The research blocks are numbered `03`
through `11`; publishing under pipeline step names would have opened a second namespace, in
which `03` was never superseded, a join on it found nothing, and administrative steps such
as `validate-feature-registry` appeared as research blocks. Blocks `09` and `11` are absent
from a RP2-v3 publication because this pipeline does not rebuild them, so their existing
rows stay current — which is what a run that did not remeasure them should leave behind.

A fourth transaction checked the block guards and what a public reader can actually see:

```text
0 public view columns              estimate,block_length,common_mask_sha256
1 first publish                    PUBLISHED
2 identical retry                  ALREADY_PUBLISHED
3 retry, block status changed      RP2_PUBLISH_BLOCK_IMMUTABLE:dryrun-blockfields
4 retry, block artifact changed    RP2_PUBLISH_BLOCK_IMMUTABLE:dryrun-blockfields
5 public view row                  5 aaaaaaaa
```

The key-set guard notices a block added or removed; these two notice a block that kept its
id and changed what it says. Line 0 and line 5 are the same point from the reader's side:
the base tables carry row-level security with no reader policy, so a field missing from the
view cannot be reached at all, and a contrast whose mask a reader cannot see is a contrast
whose evaluation rows nobody outside can identify.

The input inventory is guarded the same way, because it is the third set this function
writes and the one a reader follows to find the files a number was built from:

```text
1 first publish                  PUBLISHED
2 identical retry                ALREADY_PUBLISHED
3 retry, a bar digest changed    RP2_PUBLISH_INPUT_IMMUTABLE:dryrun-inputs
4 retry, the tape path moved     RP2_PUBLISH_INPUT_IMMUTABLE:dryrun-inputs
5 retry, an input removed        RP2_PUBLISH_INPUT_SET_CHANGED:dryrun-inputs
```

Lines 3 and 4 leave every result identical and change the account of what produced them.

## The version chain builds itself

Nobody is asked to name the predecessor. One identifier cannot describe blocks that belong
to different runs, so an option to supply one could only ever override the right answer with
a single wrong one; the publisher does not offer it and the function ignores a payload that
carries it. Each block's current owner is read inside the transaction, before `is_current`
is cleared. Two runs, the second rebuilding one block and naming a predecessor that never
owned it:

```text
1 spec_version omitted                      RP2_PUBLISH_SPEC_VERSION_MISSING:dryrun-A
2 run A publishes 06 and 08                 PUBLISHED
3 run B, caller names a false predecessor   PUBLISHED
4 chain: 06 run=dryrun-A                    (null)    current=false
4 chain: 06 run=dryrun-B                    dryrun-A  current=true
4 chain: 08 run=dryrun-A                    (null)    current=true
```

Line 3 supplied `supersedes_run_id = a-run-that-never-owned-06`, and line 4 records
`dryrun-A`: the run that actually owned the block. Block 08 stays with run A because run B
did not rebuild it — which one caller-supplied identifier could not have said.

The lineage columns are required rather than merely present:

```text
1 scientific hash omitted    RP2_PUBLISH_LINEAGE_INCOMPLETE:dryrun-sci
2 branch omitted             RP2_PUBLISH_BRANCH_MISSING:dryrun-sci
3 complete payload           PUBLISHED
4 stored scientific hash     bbbbbbbbbbbb
```

`scientific_sha256` is a column rather than only a phrase inside `note`. The publisher
recomputes the manifest's own digest before it reads any provenance out of it, so the run
row can carry the value that assertion was made against — and a reader can check it, or join
on it, instead of searching prose for sixteen characters.

## Who may call the publication functions

The end state, read off the function's own access list inside a rolled-back transaction:

```text
0 acl as created      {=X/postgres,postgres=X/postgres,anon=X/postgres,authenticated=X/postgres,service_role=X/postgres}
1 acl after grants    {postgres=X/postgres,service_role=X/postgres}
2 publish: service_role   true
3 publish: anon           false
4 publish: PUBLIC         false
5 failure: service_role   true
6 failure: anon           false
```

The leading `=X/postgres` on line 0 is the `PUBLIC` grant PostgreSQL attaches to every new
function. The `service_role=X` beside it does not come from `PUBLIC`: this project's
`ALTER DEFAULT PRIVILEGES` grants EXECUTE on new `public` functions to `anon`,
`authenticated` and `service_role` individually, so revoking `PUBLIC` never took the
publisher's own access away and publication would work here without the explicit grant.

It is stated anyway, because that default-privilege setting is ambient configuration this
migration does not own. A database restored or created without it would refuse every
publication with a permission error, and the grant a publisher depends on should be written
down rather than inherited.

## What the publisher checks before it calls

The manifest carries its own `scientific_sha256`, covering the commit, the input digest, the
seeds and every step's content. The publisher recomputes it before reading any provenance
out of the manifest: a file edited after the run finished would otherwise be published as
its own account of itself. The bar stores are re-digested for the same reason, because the
run-time digest paired with today's file size describes neither. When publication fails,
the separate failure record can fail too; its response is checked, and an unrecorded failure
is reported as `RP2_FAILURE_UNRECORDED` beside the original error rather than being
mistaken for an audited one.
