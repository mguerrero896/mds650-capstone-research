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
    add column if not exists common_mask_sha256 text,
    add column if not exists scientific_sha256 text;

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
    equivalence_bound,
    -- The resampling design and the rows the estimate was measured on. A reader who cannot
    -- see the mask cannot tell whether two of these contrasts scored the same rows, which
    -- is the question the digest exists to answer, and the base table has row-level
    -- security with no reader policy, so the view is the only way to see it.
    block_length,
    common_mask_sha256
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
    --: block id -> the run whose row this publication replaces, read before it is replaced.
    superseded jsonb;
begin
    if published_run_id is null or length(published_run_id) = 0 then
        raise exception 'RP2_PUBLISH_RUN_ID_MISSING';
    end if;

    -- Publications of one run id serialise. Without this, two callers submitting the same
    -- previously unseen id with different payloads both pass the immutability checks before
    -- either commits, and the second overwrites the first. The lock is transaction-scoped,
    -- so it is released by the commit or the rollback that ends this function.
    perform pg_advisory_xact_lock(hashtext('rp2_publish:' || published_run_id));
    if block_rows = 0 and contrast_rows = 0 then
        raise exception 'RP2_PUBLISH_NOTHING_TO_PUBLISH';
    end if;
    -- `coalesce` for the same reason as the digests below: a regex against NULL is NULL,
    -- and `if NULL then` does not raise, so an omitted commit would have reached PUBLISHED
    -- through the check written to prevent exactly that.
    if coalesce(run ->> 'code_commit', '') !~ '^[0-9a-f]{40}$' then
        raise exception 'RP2_PUBLISH_CODE_COMMIT_INVALID';
    end if;

    -- And the rest of the lineage, because the columns that carry it are nullable and a
    -- caller that omits them still reaches `PUBLISHED`. A result row nobody can tie to its
    -- inputs, its feature registry, its model configuration, its inference settings or its
    -- evaluation mask is a number without an experiment behind it. `coalesce` first: a
    -- regex against NULL is NULL, and `if NULL then` does not raise.
    if coalesce(run ->> 'inputs_sha256', '') !~ '^[0-9a-f]{64}$'
       or coalesce(run ->> 'feature_registry_sha256', '') !~ '^[0-9a-f]{64}$'
       or coalesce(run ->> 'model_config_sha256', '') !~ '^[0-9a-f]{64}$'
       or coalesce(run ->> 'inference_config_sha256', '') !~ '^[0-9a-f]{64}$'
       or coalesce(run ->> 'common_mask_sha256', '') !~ '^[0-9a-f]{64}$'
       or coalesce(run ->> 'scientific_sha256', '') !~ '^[0-9a-f]{64}$' then
        raise exception 'RP2_PUBLISH_LINEAGE_INCOMPLETE:%', published_run_id;
    end if;

    -- The inputs themselves. `ingestion_inputs` is where a reader goes to find the files a
    -- number was built from, and an empty inventory answers that question with silence.
    if input_rows = 0 then
        raise exception 'RP2_PUBLISH_INPUTS_MISSING:%', published_run_id;
    end if;

    -- The specification the results implement. It is a lineage field like the digests
    -- above and was left outside the guard with them: a run published without it states
    -- what it measured and not what it was measuring against.
    if coalesce(run ->> 'spec_version', '') = '' then
        raise exception 'RP2_PUBLISH_SPEC_VERSION_MISSING:%', published_run_id;
    end if;

    -- The branch the publication came from, for the same reason: it is a lineage column
    -- this migration adds, and a nullable lineage column is a field nobody has to fill in.
    if coalesce(run ->> 'branch_name', '') = '' then
        raise exception 'RP2_PUBLISH_BRANCH_MISSING:%', published_run_id;
    end if;

    -- One run id refers to one experiment. A caller mistake, or a publication from an
    -- altered run directory, would otherwise rewrite a published run's provenance and its
    -- estimates in place and leave nothing saying the number had changed.
    if exists (
        select 1 from public.ingestion_runs r
        where r.run_id = published_run_id
          and r.status = 'PUBLISHED'
          and (
              r.code_commit is distinct from (run ->> 'code_commit')
              or r.inputs_sha256 is distinct from (run ->> 'inputs_sha256')
              or r.feature_registry_sha256 is distinct from (run ->> 'feature_registry_sha256')
              or r.model_config_sha256 is distinct from (run ->> 'model_config_sha256')
              or r.inference_config_sha256 is distinct from (run ->> 'inference_config_sha256')
              or r.common_mask_sha256 is distinct from (run ->> 'common_mask_sha256')
              or r.scientific_sha256 is distinct from (run ->> 'scientific_sha256')
              -- Every remaining field the insert below can overwrite. Comparing a subset
              -- means the fields left out are the ones a retry can change while being
              -- reported as identical - the same reason the contrast comparison lists all
              -- nine of its columns rather than the interesting five.
              or r.spec_version is distinct from (run ->> 'spec_version')
              or r.branch_name is distinct from (run ->> 'branch_name')
              or r.note is distinct from (run ->> 'note')
              or r.input_count is distinct from input_rows
          )
    ) then
        raise exception 'RP2_PUBLISH_RUN_ID_IMMUTABLE:%', published_run_id;
    end if;

    if exists (
        select 1
        from jsonb_array_elements(coalesce(payload -> 'contrasts', '[]'::jsonb)) as item
        join public.rp2_contrast_results c
          on c.run_id = published_run_id
         and c.role = item ->> 'role'
         and c.model_family = item ->> 'model_family'
         and c.base_information_set = item ->> 'base_information_set'
         and c.expanded_information_set = item ->> 'expanded_information_set'
        -- Every field the upsert below can overwrite. Comparing a subset means the fields
        -- left out are the ones a retry can silently change.
        where c.estimate is distinct from (item ->> 'estimate')::double precision
           or c.ci_low is distinct from (item ->> 'ci_low')::double precision
           or c.ci_high is distinct from (item ->> 'ci_high')::double precision
           or c.p_value is distinct from (item ->> 'p_value')::double precision
           or c.sessions is distinct from (item ->> 'sessions')::integer
           or c.block_length is distinct from (item ->> 'block_length')::integer
           or c.mde is distinct from (item ->> 'mde')::double precision
           or c.equivalence_bound is distinct from (item ->> 'equivalence_bound')::double precision
           or c.common_mask_sha256 is distinct from (item ->> 'common_mask_sha256')
    ) then
        raise exception 'RP2_PUBLISH_CONTRAST_IMMUTABLE:%', published_run_id;
    end if;

    -- The same question for the blocks. The key-set check below notices a block added or
    -- removed; without this, a retry that keeps the same block ids and changes what they
    -- say - a status, a verdict, the digest of the artifact behind it - is reported as
    -- already published while the stored row disagrees with the submitted one.
    if exists (
        select 1
        from jsonb_array_elements(coalesce(payload -> 'blocks', '[]'::jsonb)) as item
        join public.rp2_block_results b
          on b.run_id = published_run_id
         and b.block_id = item ->> 'block_id'
        where b.status is distinct from (item ->> 'status')
           or b.verdict is distinct from (item ->> 'verdict')
           or b.document is distinct from (item ->> 'document')
           or b.artifact_sha256 is distinct from (item ->> 'artifact_sha256')
    ) then
        raise exception 'RP2_PUBLISH_BLOCK_IMMUTABLE:%', published_run_id;
    end if;

    -- And the inputs, which are the third set this function writes. The blocks and the
    -- contrasts are guarded above; `ingestion_inputs` is where a reader goes to find the
    -- files a number was built from, so a retry that changes a path, a provider or a digest
    -- changes the answer to that question while every result stays identical.
    if exists (
        select 1
        from jsonb_array_elements(coalesce(payload -> 'inputs', '[]'::jsonb)) as item
        join public.ingestion_inputs i
          on i.run_id = published_run_id
         and i.input_name = item ->> 'input_name'
        where i.path is distinct from (item ->> 'path')
           or i.provider is distinct from (item ->> 'provider')
           or i.sha256 is distinct from (item ->> 'sha256')
           or i.bytes is distinct from (item ->> 'bytes')::bigint
           or i.rows is distinct from nullif(item ->> 'rows', '')::bigint
           or i.schema_sha256 is distinct from (item ->> 'schema_sha256')
           or i.time_min is distinct from (item ->> 'time_min')
           or i.time_max is distinct from (item ->> 'time_max')
    ) then
        raise exception 'RP2_PUBLISH_INPUT_IMMUTABLE:%', published_run_id;
    end if;

    -- The comparisons above join on the keys, so they only ever examine the rows present
    -- on both sides. A retry that drops a contrast, adds one, or renames a family changes
    -- no value the joins can see, and would be reported as already published while the
    -- stored result set is not the submitted one. The whole key set is compared instead.
    if exists (
        select 1 from public.ingestion_runs r
        where r.run_id = published_run_id and r.status = 'PUBLISHED'
    ) and exists (
        (
            select item ->> 'role' as role,
                   item ->> 'model_family' as model_family,
                   item ->> 'base_information_set' as base_information_set,
                   item ->> 'expanded_information_set' as expanded_information_set
            from jsonb_array_elements(coalesce(payload -> 'contrasts', '[]'::jsonb)) as item
            except
            select c.role, c.model_family, c.base_information_set, c.expanded_information_set
            from public.rp2_contrast_results c
            where c.run_id = published_run_id
        )
        union all
        (
            select c.role, c.model_family, c.base_information_set, c.expanded_information_set
            from public.rp2_contrast_results c
            where c.run_id = published_run_id
            except
            select item ->> 'role',
                   item ->> 'model_family',
                   item ->> 'base_information_set',
                   item ->> 'expanded_information_set'
            from jsonb_array_elements(coalesce(payload -> 'contrasts', '[]'::jsonb)) as item
        )
    ) then
        raise exception 'RP2_PUBLISH_CONTRAST_SET_CHANGED:%', published_run_id;
    end if;

    -- The same question for the blocks, which are the other set this function replaces.
    if exists (
        select 1 from public.ingestion_runs r
        where r.run_id = published_run_id and r.status = 'PUBLISHED'
    ) and exists (
        (
            select item ->> 'block_id' as block_id
            from jsonb_array_elements(coalesce(payload -> 'blocks', '[]'::jsonb)) as item
            except
            select b.block_id from public.rp2_block_results b where b.run_id = published_run_id
        )
        union all
        (
            select b.block_id from public.rp2_block_results b where b.run_id = published_run_id
            except
            select item ->> 'block_id'
            from jsonb_array_elements(coalesce(payload -> 'blocks', '[]'::jsonb)) as item
        )
    ) then
        raise exception 'RP2_PUBLISH_BLOCK_SET_CHANGED:%', published_run_id;
    end if;

    -- The same for the input inventory: an input added or removed leaves every field
    -- comparison above with nothing to disagree about.
    if exists (
        select 1 from public.ingestion_runs r
        where r.run_id = published_run_id and r.status = 'PUBLISHED'
    ) and exists (
        (
            select item ->> 'input_name' as input_name
            from jsonb_array_elements(coalesce(payload -> 'inputs', '[]'::jsonb)) as item
            except
            select i.input_name from public.ingestion_inputs i where i.run_id = published_run_id
        )
        union all
        (
            select i.input_name from public.ingestion_inputs i where i.run_id = published_run_id
            except
            select item ->> 'input_name'
            from jsonb_array_elements(coalesce(payload -> 'inputs', '[]'::jsonb)) as item
        )
    ) then
        raise exception 'RP2_PUBLISH_INPUT_SET_CHANGED:%', published_run_id;
    end if;

    -- Nothing left to do, and nothing that may be done. A later run may have superseded
    -- this one; standing its rows down and marking these current again would silently
    -- restore an older answer as the current one.
    if exists (
        select 1 from public.ingestion_runs r
        where r.run_id = published_run_id and r.status = 'PUBLISHED'
    ) then
        return jsonb_build_object(
            'run_id', published_run_id,
            'status', 'ALREADY_PUBLISHED',
            'contrasts', contrast_rows
        );
    end if;

    insert into public.ingestion_runs (
        run_id, started_at, status, code_commit, inputs_sha256, input_count, rows_published,
        note, spec_version, branch_name, feature_registry_sha256, model_config_sha256,
        inference_config_sha256, common_mask_sha256, scientific_sha256
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
        run ->> 'common_mask_sha256',
        run ->> 'scientific_sha256'
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
        common_mask_sha256 = excluded.common_mask_sha256,
        scientific_sha256 = excluded.scientific_sha256;

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
    -- Which run each block currently belongs to, captured before `is_current` is cleared.
    -- The caller's `--supersedes` is one id for the whole run, it is omitted by the
    -- documented rebuild command, and different blocks can belong to different runs, so a
    -- version chain built from it is empty in the normal case and wrong in the interesting
    -- one. The rows themselves know what they are replacing.
    select jsonb_object_agg(b.block_id, b.run_id) into superseded
    from public.rp2_block_results b
    where b.is_current
      and b.run_id is distinct from published_run_id
      and b.block_id in (
          select item ->> 'block_id'
          from jsonb_array_elements(coalesce(payload -> 'blocks', '[]'::jsonb)) as item
      );

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
        coalesce(superseded, '{}'::jsonb) ->> (item ->> 'block_id'),
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

-- `PUBLIC` first: PostgreSQL grants EXECUTE on a new function to that pseudo-role, so
-- revoking from `anon` and `authenticated` alone leaves the inherited grant in place.
revoke all on function public.publish_rp2_v3(jsonb) from public;
revoke all on function public.publish_rp2_v3(jsonb) from anon, authenticated;
-- And then say who may call it. This project's `ALTER DEFAULT PRIVILEGES` happens to grant
-- EXECUTE on new `public` functions to `service_role`, so publication would work here
-- without this line - but that is ambient configuration this migration does not own, and a
-- database restored or created without it would refuse every publication with a permission
-- error. The grant the publisher depends on is stated rather than inherited.
grant execute on function public.publish_rp2_v3(jsonb) to service_role;

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
        -- A published run keeps its own note, which carries its scientific hash. The failed
        -- attempt is appended: replacing it would destroy the provenance of a run that
        -- succeeded in order to record that something else did not.
        note = case
            when public.ingestion_runs.status = 'PUBLISHED'
                then public.ingestion_runs.note || ' | failed retry: ' || excluded.note
            else excluded.note
        end,
        completed_at = case
            when public.ingestion_runs.status = 'PUBLISHED' then public.ingestion_runs.completed_at
            else now()
        end;
$$;

revoke all on function public.record_rp2_v3_failure(text, text) from public;
revoke all on function public.record_rp2_v3_failure(text, text) from anon, authenticated;
grant execute on function public.record_rp2_v3_failure(text, text) to service_role;
