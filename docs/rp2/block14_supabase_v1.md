# Block 14 — Supabase evaluation

**Status:** `EXECUTED — 2026-08-19` · project `mds650-research-data` (`eqpyjikcewqaegnbaemf`,
Postgres 17.6.1.155, ap-southeast-2, ACTIVE_HEALTHY)
**Applied:** Supabase migration `rp2_block14_evidence_hygiene`
**Withheld, pending owner signature:** `supabase/migrations_pending/rp2_block14_pending.sql`

---

## 1. The program's premise about security is out of date — in the opposite direction

Block 14 states: *"Public `USING (true)` policies on base tables are too broad."*

**That is no longer the state.** Row-level security is enabled on **all 11 tables and there
are zero policies anywhere in the `public` schema.** Supabase's own linter reports
`rls_enabled_no_policy` eleven times. The consequence is not over-exposure but the reverse:

> The catalogue is **inert**. Neither `anon` nor `authenticated` can read a single row of any
> table. There is no public read model at all, so Supabase currently cannot serve the "public
> layer / results catalogue / query API" role the program assigns it.

The earlier over-broad policies were removed at some point and never replaced with the
whitelisted-view layer that should have taken their place. That is the real defect, and it is
a design decision (what should be public) rather than a bug, so the fix is proposed, not
applied.

## 2. Inventory

| Table | Rows | PK | RLS | Policies |
|---|---|---|---|---|
| `campaigns` | 5 | ✅ | on | **0** |
| `contrast_results` | 36 | ✅ | on | **0** |
| `mcs_cells` | 264 | ✅ | on | **0** |
| `gated_files` | 15 | ✅ | on | **0** |
| `access_grants` | 0 | ✅ | on | **0** |
| `dev_training_all_origins` | 45,440 | ❌ | on | 0 |
| `dev_training_common` | 38,573 | ❌ | on | 0 |
| `c1_development_forecasts` | 93,288 | ❌ | on | 0 |
| `c5_frozen_evaluation_forecasts` | 356,400 | ❌ | on | 0 |
| `b1v3_features` | 77,328 | ❌ | on | 0 |
| `b2_mechanism_forecasts` | 1,543,080 | ❌ | on | 0 |

## 3. Findings, each verified against the live database

**3.1 Weak types — confirmed.** `option_trade_count_5m` and `unique_contract_count_5m` are
`text` in both `dev_training_*` tables, exactly as the program predicted. A text count sorts
`'10'` before `'9'` and cannot be summed without a cast. `b1v3_features.forecast_origin_utc`
is also `text`, while every other table stores the origin as `timestamptz` — so joining them
requires a cast on every query.

**3.2 Fact tables without robust keys — confirmed.** Six tables have no primary key,
including the 1.55 M-row `b2_mechanism_forecasts`. A duplicate load cannot be detected and
PostgREST cannot address an individual row.

**3.3 Incorrect evidence chain — confirmed, and worse than described.** All five campaign
rows carried the **identical** `note`:

> *"C6 chain lists (B1v3a, B0) because decision 48 registered the adverse
> B0-better-than-B1v3a direction; positive values favor the second set."*

That sentence is true of C6 and **false of C1, C2, C4c and C5** — a C6-specific sign
convention asserted about four campaigns it does not describe. The `campaigns` table also
carries only `input_sha256`, not the six provenance fields the program requires
(`source_commit`, `protocol_sha256`, `input_manifest_sha256`, `result_artifact_sha256`,
`schema_version`, `generated_at`).

**Also found, not in the program's list: C3 is missing entirely.** The reconciliation document
registers C1–C6; the table holds five rows and Phase 6 (C3, 100 OOS sessions) is absent.

**3.4 Incomplete statistical results — confirmed.** `p_wild` is `NULL` in **all 36 rows** of
`contrast_results`, while the frozen artifact `artifacts/gate1_inference/results.json` does
contain wild-bootstrap p-values. This is precisely the ambiguous NULL the program forbids.

**3.5 Optimisation.** Three indexes have never been used
(`contrast_results_campaign_id_idx`, `mcs_cells_campaign_id_block_id_idx`,
`access_grants_bucket_object_idx`). No foreign key lacks an index and no duplicate indexes
exist. No RLS policy re-evaluates `auth.role()` per row, because there are no policies. Auth
uses an absolute rather than percentage connection allocation.

## 4. What was applied

Migration `rp2_block14_evidence_hygiene`, two corrections, both reversible:

1. **The false note was removed** from the four campaigns it does not describe (`note` set to
   `null`; C6 keeps it). Removing a false statement is the honest fix — inventing four
   plausible per-campaign notes would have been worse than the defect.
2. **`contrast_results.p_wild_status`** added, `check`-constrained to
   `SYNCED / NOT_SYNCED / NOT_APPLICABLE / AVAILABLE_IN_ARTIFACT_ONLY`, and set to
   `AVAILABLE_IN_ARTIFACT_ONLY` for all 36 rows, with a column comment saying so. The p-value
   is **not** invented; the ambiguity is labelled, which is what the program asks for.

Verified after applying: 1 of 5 campaigns retains a note; 36 of 36 contrast rows are labelled.

## 5. What was withheld, and why

`supabase/migrations_pending/rp2_block14_pending.sql` contains, ready to run but **not run**:

| # | Change | Why it needs a signature |
|---|---|---|
| 1 | text → `bigint` / `timestamptz` casts | rewrites 84,013 + 77,328 rows; a single unparseable value aborts the migration |
| 2 | primary keys on six tables | requires a duplicate check first on up to 1.55 M rows; failure mode is a half-migrated catalogue |
| 3 | six provenance columns on `campaigns` | the columns are trivial; the **values** must come from the owner's frozen registry, and adding NULL columns would move the ambiguity rather than remove it |
| 4 | `api` schema with whitelisted views + read policies on the three aggregate tables only | this decides **what becomes public**. Licensed-derived origin-level panels must stay service-role only (`docs/provider_license_review_v1.md`); that judgement is the owner's |
| 5 | dropping three unused indexes | commented out — they may start being used the moment the read model in (4) exists |

## 6. Verdict on Supabase's role

The program's position — Supabase is a public layer, results catalogue, audit data mart,
dashboard and query API, and **must not become the primary scientific source** — is correct
and is currently satisfied in the strongest possible way: the authority chain
(`raw evidence → manifests → protocol hash → code commit → derived artifacts → public read
model`) is intact because Supabase serves *nothing* today.

Making it useful means deliberately opening the aggregate tier while keeping the
origin-level licensed-derived panels closed. That is migration (4), and it is a decision
requiring the owner's signature.
