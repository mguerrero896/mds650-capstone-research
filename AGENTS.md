## Study window rule (binding)

The default study-window rule remains the maximum common provider overlap
verified by the authenticated audit. A recorded configuration change for this
run freezes `2025-07-21` through `2026-07-21` (end exclusive), because the
window probe established sufficient FMP/UW/Massive coverage. Future widening or
shortening requires another recorded configuration change; never retry blocked
ranges or silently substitute a different window.

Measured evidence (2026-07-21, `scripts/window_probe_v1.py`, artifacts under
`artifacts/api_audit/window_probe_20260720/`): UW flow-alerts entitled back to
2023-08-18 (oldest non-empty events ~2024-08-02); FMP 1-min bars verified to
≥730 days; Massive options history deep (stock aggregates NOT entitled). A
12-month study window is therefore feasible with the current subscriptions.

## Provider HTTP calls (FMP / Unusual Whales / Massive)

Before writing or debugging any provider HTTP call, read
`docs/reference/provider_http_reference.md`. It contains the verified auth
scheme per provider, endpoint syntax, pagination, and error triage. A 403 from
Unusual Whales may be a subscription limit, but only after auth and parameter
names have been validated against the current OpenAPI contract.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

When the user types `/graphify`, invoke the `skill` tool with `skill: "graphify"` before doing anything else.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- Dirty graphify-out/ files are expected after hooks or incremental updates; dirty graph files are not a reason to skip graphify. Only skip graphify if the task is about stale or incorrect graph output, or the user explicitly says not to use it.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
  - MDS650 knowledge MUST remain isolated from Earnings, GenIA and global transcripts. Use the dedicated GBrain profile `%USERPROFILE%\.mds650`, database `gbrain_mds650`, and the project-only sources `mds650-research` and `mds650-code`; never use the global GBrain corpus to answer an MDS650 question.
  - For natural-language project search, run `scripts/query_project_knowledge.ps1`. It queries the isolated GBrain corpus and the repository-local Graphify graph.
  - The project hooks run Graphify after commits/branch switches and synchronize the isolated GBrain source after the same events. `MDS650_Knowledge_AutoSync` also refreshes both engines every fifteen minutes and at logon. For an immediate refresh, run `scripts/sync_project_knowledge.ps1`.

## Gated data relocation (2026-08-18) — READ BEFORE PUBLISHING OR TOUCHING PARQUETS

The GitHub remote is a PUBLIC filtered mirror. The 15 licensed-derived granular
files — 14 parquets plus one quote-level diagnostic CSV —
(list: `scripts/_gated_exclude_list.txt`) exist ONLY in the local canonical
repo and in the private Supabase Storage bucket (project `eqpyjikcewqaegnbaemf`,
bucket `research-data`); `scripts/publish_mirror.sh` strips them from the entire
published history on every publish and `tests/test_gated_publish_contract.py` fails
the suite if a new granular parquet is committed without registering it in the
exclude list. NEVER push to the remote directly; ALWAYS publish via
`bash scripts/publish_mirror.sh`. Pointers + access policy:
`data/GATED_DATA_POINTERS.json`, `data/DATA_ACCESS.md`.

## Supabase research catalog (2026-08-18)

The same Supabase project also hosts Postgres catalog tables (`campaigns`,
`contrast_results`, `mcs_cells`, `gated_files`, `access_grants`) — aggregates and
registry only, RLS locked (service-role only). After changing
`artifacts/gate1_inference/results.json`, `artifacts/mcs_block_sensitivity/results.json`
or `data/GATED_DATA_POINTERS.json`, re-run
`uv run python scripts/sync_supabase_catalog.py` (idempotent upserts; needs
`SUPABASE_SERVICE_KEY` from the User environment). Never write to these tables by
hand: repo artifacts are the source of truth. When a signed URL is issued from the
gated bucket, log it in `access_grants`.

Second wave (same date): the six core gated datasets are also loaded as private
RLS-locked tables (`dev_training_all_origins`, `dev_training_common`,
`c1_development_forecasts`, `c5_frozen_evaluation_forecasts`, `b1v3_features`,
`b2_mechanism_forecasts`) via `scripts/load_supabase_datasets.py` (idempotent by row
count). If a frozen parquet ever changes (it should not — immutability), rerun the
loader; never edit rows server-side.

## Internal-only documents (2026-08-18)

`scripts/_mirror_internal_exclude_list.txt` lists working documents that stay in
the local canonical repo but are stripped from the entire public history by
`publish_mirror.sh` (same pass as the gated data, no Supabase pointers). Current:
`ROADMAP_CODEX_20260816.md`. Add internal-only docs there BEFORE committing them;
never reference them from public docs, tests, or the INDEX.
