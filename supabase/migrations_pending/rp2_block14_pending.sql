-- Research Program v2, Block 14 — migrations that are NOT applied.
--
-- These require the owner's signature. Each one either rewrites a multi-million-row
-- table, or changes who can read the catalogue. Applied fixes live in the Supabase
-- migration `rp2_block14_evidence_hygiene`; see docs/rp2/block14_supabase_v1.md.

-- =====================================================================
-- 1. Weak types. Trade counts are stored as text; a text column silently
--    sorts '10' before '9' and cannot be summed. Rewrites 84,013 rows.
-- =====================================================================
alter table public.dev_training_all_origins
  alter column option_trade_count_5m   type bigint using nullif(option_trade_count_5m, '')::bigint,
  alter column unique_contract_count_5m type bigint using nullif(unique_contract_count_5m, '')::bigint;

alter table public.dev_training_common
  alter column option_trade_count_5m   type bigint using nullif(option_trade_count_5m, '')::bigint,
  alter column unique_contract_count_5m type bigint using nullif(unique_contract_count_5m, '')::bigint;

-- b1v3_features stores the forecast origin as text, so it cannot be compared to the
-- timestamptz origins in every other table without a cast on each query.
alter table public.b1v3_features
  alter column forecast_origin_utc type timestamptz using forecast_origin_utc::timestamptz;

-- =====================================================================
-- 2. Fact tables without robust keys. Six tables have no primary key, so a
--    double load cannot be detected and PostgREST cannot address a row.
--    b2_mechanism_forecasts is 1.55M rows: check for duplicates FIRST.
-- =====================================================================
-- Verify uniqueness before adding any constraint, e.g.
--   select count(*) - count(distinct (origin_id, model_role, information_set))
--   from public.c1_development_forecasts;
alter table public.c1_development_forecasts
  add constraint c1_development_forecasts_pkey
  primary key (origin_id, model_role, information_set);

alter table public.c5_frozen_evaluation_forecasts
  add constraint c5_frozen_evaluation_forecasts_pkey
  primary key (origin_id, model_name, information_set);

alter table public.b2_mechanism_forecasts
  add constraint b2_mechanism_forecasts_pkey
  primary key (origin_id, model_name, information_set, mechanism_id, b2_variant);

alter table public.b1v3_features add constraint b1v3_features_pkey primary key (origin_id);
alter table public.dev_training_all_origins
  add constraint dev_training_all_origins_pkey primary key (origin_id);
alter table public.dev_training_common
  add constraint dev_training_common_pkey primary key (origin_id);

-- =====================================================================
-- 3. Evidence chain. campaigns carries only input_sha256. The program requires
--    six provenance fields per campaign. They are added NOT NULL-less here
--    because the VALUES must come from the owner's frozen registry, not from
--    a guess — populate them in the same transaction or leave the block out.
-- =====================================================================
alter table public.campaigns
  add column if not exists source_commit          text,
  add column if not exists protocol_sha256        text,
  add column if not exists input_manifest_sha256  text,
  add column if not exists result_artifact_sha256 text,
  add column if not exists schema_version         text,
  add column if not exists generated_at           timestamptz;

-- C3 (Phase 6 mechanism-aware, 100 OOS sessions) is absent from the register
-- entirely; the reconciliation document lists C1-C6 and this table holds five rows.

-- =====================================================================
-- 4. Public read model. RLS is enabled on all 11 tables with ZERO policies, so
--    nothing is readable by anon or authenticated — the catalogue is inert.
--    The program's target shape: private base tables, whitelisted public views.
-- =====================================================================
create schema if not exists api;

create or replace view api.campaign_register
with (security_invoker = true) as
select campaign_id, sessions, row_count, input_sha256
from public.campaigns;

create or replace view api.contrast_summary
with (security_invoker = true) as
select campaign_id, block_id, model_role, contrast,
       estimate, cluster_t, p_cluster, p_newey_west, p_wild, p_wild_status
from public.contrast_results;

grant usage on schema api to anon, authenticated;
grant select on api.campaign_register, api.contrast_summary to anon, authenticated;

-- Aggregate-only tables may be read directly; the row-level panels never may.
create policy campaigns_public_read on public.campaigns
  for select to anon, authenticated using (true);
create policy contrast_results_public_read on public.contrast_results
  for select to anon, authenticated using (true);
create policy mcs_cells_public_read on public.mcs_cells
  for select to anon, authenticated using (true);
-- gated_files, access_grants and every origin-level panel stay policy-free
-- (service role only): they are licensed-derived data.

-- =====================================================================
-- 5. Index hygiene. Three indexes have never been used. Drop only after the
--    public read model above is live, since it may start using them.
-- =====================================================================
-- drop index if exists public.contrast_results_campaign_id_idx;
-- drop index if exists public.mcs_cells_campaign_id_block_id_idx;
-- drop index if exists public.access_grants_bucket_object_idx;
