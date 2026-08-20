-- RP2-v3 versioned results.
--
-- Every published number gets a run id, and every run id carries the commit, the input
-- manifest, the feature registry, the model configuration and the evaluation mask that
-- produced it. The tables that hold the RP2-v2 numbers are left exactly where they are:
-- a reader who followed a citation to one of them must still find it.
--
-- Publication is a single function call so that it is a single transaction. A partial
-- publish - a run row with no results, or a new result without the previous one being
-- stood down - would be a database that disagrees with itself about which number is
-- current, and no later care recovers which half was written.

-- ---------------------------------------------------------------------------
-- 1. What a run has to declare about itself.
-- ---------------------------------------------------------------------------
alter table public.ingestion_runs
    add column if not exists spec_version text,
    add column if not exists branch_name text,
    add column if not exists feature_registry_sha256 text,
    add column if not exists model_config_sha256 text,
    add column if not exists inference_config_sha256 text,
    add column if not exists common_mask_sha256 text;

comment on column public.ingestion_runs.spec_version is
    'Which frozen specification the run implements, e.g. rp2-v3.';
comment on column public.ingestion_runs.common_mask_sha256 is
    'Digest of the evaluation rows every contrast in this run was scored on.';

-- ---------------------------------------------------------------------------
-- 2. Versioned results. One current row per subject, enforced by the index.
-- ---------------------------------------------------------------------------
create table if not exists public.rp2_block_results (
    block_id text not null,
    run_id text not null
        references public.ingestion_runs(run_id)
        on delete restrict,
    status text not null,
    verdict text not null,
    document text not null,
    artifact_sha256 text not null
        check (artifact_sha256 ~ '^[0-9a-f]{64}$'),
    supersedes_run_id text
        references public.ingestion_runs(run_id)
        on delete restrict,
    is_current boolean not null default false,
    created_at timestamptz not null default now(),
    primary key (block_id, run_id)
);

create unique index if not exists rp2_block_results_one_current_per_block
    on public.rp2_block_results (block_id)
    where is_current;

create table if not exists public.rp2_extension_results (
    extension_id text not null,
    run_id text not null
        references public.ingestion_runs(run_id)
        on delete restrict,
    question text not null,
    result text not null,
    evidence text not null,
    document text not null,
    artifact_sha256 text not null
        check (artifact_sha256 ~ '^[0-9a-f]{64}$'),
    supersedes_run_id text
        references public.ingestion_runs(run_id)
        on delete restrict,
    is_current boolean not null default false,
    created_at timestamptz not null default now(),
    primary key (extension_id, run_id)
);

create unique index if not exists rp2_extension_results_one_current_per_extension
    on public.rp2_extension_results (extension_id)
    where is_current;

create table if not exists public.rp2_power_results (
    contrast text not null,
    role text not null,
    run_id text not null
        references public.ingestion_runs(run_id)
        on delete restrict,
    method text not null,
    detail text not null,
    sessions_for_80pct double precision,
    power_n30 double precision,
    power_n60 double precision,
    power_n120 double precision,
    note text,
    is_current boolean not null default false,
    created_at timestamptz not null default now(),
    primary key (contrast, role, run_id)
);

create unique index if not exists rp2_power_results_one_current_per_contrast
    on public.rp2_power_results (contrast, role)
    where is_current;

-- The contrast table is the one the verdict is read off, so every column the research
-- contract requires a contrast to carry is not nullable, and the mask digest is checked
-- for shape: an estimate whose evaluation rows are unidentified cannot be checked by
-- anyone, and a nullable column is how that happens quietly.
create table if not exists public.rp2_contrast_results (
    run_id text not null
        references public.ingestion_runs(run_id)
        on delete restrict,
    role text not null,
    model_family text not null,
    base_information_set text not null,
    expanded_information_set text not null,
    estimate double precision not null,
    ci_low double precision not null,
    ci_high double precision not null,
    p_value double precision not null
        check (p_value >= 0.0 and p_value <= 1.0),
    sessions integer not null check (sessions > 0),
    block_length integer not null check (block_length > 0),
    mde double precision not null check (mde > 0.0),
    equivalence_bound double precision not null check (equivalence_bound > 0.0),
    common_mask_sha256 text not null
        check (common_mask_sha256 ~ '^[0-9a-f]{64}$'),
    is_current boolean not null default false,
    created_at timestamptz not null default now(),
    primary key (run_id, role, model_family, base_information_set, expanded_information_set),
    check (ci_low <= estimate and estimate <= ci_high)
);

create unique index if not exists rp2_contrast_results_one_current_per_contrast
    on public.rp2_contrast_results (role, model_family, base_information_set, expanded_information_set)
    where is_current;

comment on table public.rp2_block_results is
    'RP2 block outcomes, versioned by run_id. One current row per block.';
comment on table public.rp2_contrast_results is
    'Session-level nested contrasts, versioned by run_id. Every row carries the mask it was measured on and the smallest effect its design could have detected.';

-- ---------------------------------------------------------------------------
-- 3. The base tables stay private. Licensed origin-level values never reach them,
--    and aggregates reach readers only through the api views below.
-- ---------------------------------------------------------------------------
alter table public.rp2_block_results enable row level security;
alter table public.rp2_extension_results enable row level security;
alter table public.rp2_power_results enable row level security;
alter table public.rp2_contrast_results enable row level security;

create or replace view api.current_rp2_block_results as
select block_id, run_id, status, verdict, artifact_sha256, created_at
from public.rp2_block_results
where is_current;

create or replace view api.current_rp2_contrasts as
select
    run_id,
    role,
    model_family,
    base_information_set,
    expanded_information_set,
    estimate,
    ci_low,
    ci_high,
    p_value,
    sessions,
    mde,
    equivalence_bound
from public.rp2_contrast_results
where is_current;

create or replace view api.current_rp2_extension_results as
select extension_id, run_id, question, result, document, artifact_sha256, created_at
from public.rp2_extension_results
where is_current;

create or replace view api.current_rp2_power_results as
select contrast, role, run_id, method, detail, sessions_for_80pct, power_n30, power_n60,
       power_n120, note
from public.rp2_power_results
where is_current;

grant select on api.current_rp2_block_results to anon, authenticated;
grant select on api.current_rp2_contrasts to anon, authenticated;
grant select on api.current_rp2_extension_results to anon, authenticated;
grant select on api.current_rp2_power_results to anon, authenticated;

-- ---------------------------------------------------------------------------
-- 4. Publication, as one transaction.
--
-- A function body is a transaction: either every row below is written or none is. The
-- alternative - eight REST calls from a script - can leave a run marked RUNNING with
-- half its results published and the previous run already stood down, and nothing in
-- the database says which half is missing.
-- ---------------------------------------------------------------------------
create or replace function public.publish_rp2_v3(payload jsonb)
returns jsonb
language plpgsql
security invoker
set search_path = public
as $$
declare
    run jsonb := payload -> 'run';
    published_run_id text := run ->> 'run_id';
    input_rows integer := coalesce(jsonb_array_length(payload -> 'inputs'), 0);
    block_rows integer := coalesce(jsonb_array_length(payload -> 'blocks'), 0);
    contrast_rows integer := coalesce(jsonb_array_length(payload -> 'contrasts'), 0);
begin
    if published_run_id is null or length(published_run_id) = 0 then
        raise exception 'RP2_PUBLISH_RUN_ID_MISSING';
    end if;
    if block_rows = 0 and contrast_rows = 0 then
        raise exception 'RP2_PUBLISH_NOTHING_TO_PUBLISH';
    end if;
    if (run ->> 'code_commit') !~ '^[0-9a-f]{40}$' then
        raise exception 'RP2_PUBLISH_CODE_COMMIT_INVALID';
    end if;

    insert into public.ingestion_runs (
        run_id, started_at, status, code_commit, inputs_sha256, input_count, rows_published,
        note, spec_version, branch_name, feature_registry_sha256, model_config_sha256,
        inference_config_sha256, common_mask_sha256
    )
    values (
        published_run_id,
        now(),
        'RUNNING',
        run ->> 'code_commit',
        run ->> 'inputs_sha256',
        input_rows,
        0,
        run ->> 'note',
        run ->> 'spec_version',
        run ->> 'branch_name',
        run ->> 'feature_registry_sha256',
        run ->> 'model_config_sha256',
        run ->> 'inference_config_sha256',
        run ->> 'common_mask_sha256'
    )
    on conflict (run_id) do update set
        status = 'RUNNING',
        code_commit = excluded.code_commit,
        inputs_sha256 = excluded.inputs_sha256,
        input_count = excluded.input_count,
        note = excluded.note,
        spec_version = excluded.spec_version,
        branch_name = excluded.branch_name,
        feature_registry_sha256 = excluded.feature_registry_sha256,
        model_config_sha256 = excluded.model_config_sha256,
        inference_config_sha256 = excluded.inference_config_sha256,
        common_mask_sha256 = excluded.common_mask_sha256;

    insert into public.ingestion_inputs (
        run_id, input_name, path, provider, sha256, bytes, rows, schema_sha256, time_min, time_max
    )
    select
        published_run_id,
        item ->> 'input_name',
        item ->> 'path',
        item ->> 'provider',
        item ->> 'sha256',
        (item ->> 'bytes')::bigint,
        nullif(item ->> 'rows', '')::bigint,
        item ->> 'schema_sha256',
        item ->> 'time_min',
        item ->> 'time_max'
    from jsonb_array_elements(coalesce(payload -> 'inputs', '[]'::jsonb)) as item
    on conflict (run_id, input_name) do update set
        path = excluded.path,
        provider = excluded.provider,
        sha256 = excluded.sha256,
        bytes = excluded.bytes,
        rows = excluded.rows,
        schema_sha256 = excluded.schema_sha256,
        time_min = excluded.time_min,
        time_max = excluded.time_max;

    -- Stand the previous rows down before the new ones claim to be current: the partial
    -- index permits exactly one current row per subject, so doing it the other way round
    -- is a constraint violation rather than a silent overwrite. That is the intent.
    update public.rp2_block_results r
    set is_current = false
    where r.is_current
      and r.block_id in (
          select item ->> 'block_id'
          from jsonb_array_elements(coalesce(payload -> 'blocks', '[]'::jsonb)) as item
      );

    insert into public.rp2_block_results (
        block_id, run_id, status, verdict, document, artifact_sha256, supersedes_run_id, is_current
    )
    select
        item ->> 'block_id',
        published_run_id,
        item ->> 'status',
        item ->> 'verdict',
        item ->> 'document',
        item ->> 'artifact_sha256',
        nullif(item ->> 'supersedes_run_id', ''),
        true
    from jsonb_array_elements(coalesce(payload -> 'blocks', '[]'::jsonb)) as item
    on conflict (block_id, run_id) do update set
        status = excluded.status,
        verdict = excluded.verdict,
        document = excluded.document,
        artifact_sha256 = excluded.artifact_sha256,
        supersedes_run_id = excluded.supersedes_run_id,
        is_current = true;

    update public.rp2_contrast_results c
    set is_current = false
    where c.is_current
      and (c.role, c.model_family, c.base_information_set, c.expanded_information_set) in (
          select
              item ->> 'role',
              item ->> 'model_family',
              item ->> 'base_information_set',
              item ->> 'expanded_information_set'
          from jsonb_array_elements(coalesce(payload -> 'contrasts', '[]'::jsonb)) as item
      );

    insert into public.rp2_contrast_results (
        run_id, role, model_family, base_information_set, expanded_information_set,
        estimate, ci_low, ci_high, p_value, sessions, block_length, mde, equivalence_bound,
        common_mask_sha256, is_current
    )
    select
        published_run_id,
        item ->> 'role',
        item ->> 'model_family',
        item ->> 'base_information_set',
        item ->> 'expanded_information_set',
        (item ->> 'estimate')::double precision,
        (item ->> 'ci_low')::double precision,
        (item ->> 'ci_high')::double precision,
        (item ->> 'p_value')::double precision,
        (item ->> 'sessions')::integer,
        (item ->> 'block_length')::integer,
        (item ->> 'mde')::double precision,
        (item ->> 'equivalence_bound')::double precision,
        item ->> 'common_mask_sha256',
        true
    from jsonb_array_elements(coalesce(payload -> 'contrasts', '[]'::jsonb)) as item
    on conflict (run_id, role, model_family, base_information_set, expanded_information_set)
    do update set
        estimate = excluded.estimate,
        ci_low = excluded.ci_low,
        ci_high = excluded.ci_high,
        p_value = excluded.p_value,
        sessions = excluded.sessions,
        block_length = excluded.block_length,
        mde = excluded.mde,
        equivalence_bound = excluded.equivalence_bound,
        common_mask_sha256 = excluded.common_mask_sha256,
        is_current = true;

    update public.ingestion_runs
    set rows_published = block_rows + contrast_rows,
        status = 'PUBLISHED',
        completed_at = now()
    where run_id = published_run_id;

    return jsonb_build_object(
        'run_id', published_run_id,
        'inputs', input_rows,
        'blocks', block_rows,
        'contrasts', contrast_rows,
        'status', 'PUBLISHED'
    );
end;
$$;

comment on function public.publish_rp2_v3(jsonb) is
    'Publish one RP2-v3 run atomically: the run, its inputs, its block results and its contrasts, with the previous current rows stood down. Raises rather than half-publishing.';

revoke all on function public.publish_rp2_v3(jsonb) from anon, authenticated;

-- A failed publication is recorded separately, outside the transaction that rolled back:
-- a run that raised leaves no trace by construction, and a rebuild that failed silently
-- is indistinguishable from one that was never attempted.
create or replace function public.record_rp2_v3_failure(failed_run_id text, reason text)
returns void
language sql
security invoker
set search_path = public
as $$
    -- A run that already published keeps its status. Its result rows are committed and
    -- still current, so marking it FAILED would leave the database showing current results
    -- attributed to a run it says did not succeed. A failed attempt to publish over it is a
    -- fact about the attempt, and it is recorded in the note.
    insert into public.ingestion_runs (run_id, started_at, status, input_count, rows_published, note)
    values (failed_run_id, now(), 'FAILED', 0, 0, reason)
    on conflict (run_id) do update set
        status = case when public.ingestion_runs.status = 'PUBLISHED' then 'PUBLISHED' else 'FAILED' end,
        note = excluded.note,
        completed_at = now();
$$;

revoke all on function public.record_rp2_v3_failure(text, text) from anon, authenticated;
