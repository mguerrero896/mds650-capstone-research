## Study window rule (binding)

The default study-window rule remains the maximum common provider overlap
verified by the authenticated audit. A recorded configuration change for this
run freezes `2025-07-21` through `2026-07-21` (end exclusive), because the
window probe established sufficient FMP/UW/Massive coverage. Future widening or
shortening requires another recorded configuration change; never retry blocked
ranges or silently substitute a different window.

**Amendment, 2026-08-21 (recorded configuration change; methodology decision
84).** For RP2 and RP2-v3 the study window is the frozen partition:
`2024-08-02` through `2026-07-17`, D `2024-08-02..2026-03-23` (389 sessions) and
V `2026-03-24..2026-07-17` (80). Every RP2 artifact was built on it, and the
twelve-month freeze above is retained for the acquisition programme it was
written for. Measured before deciding: 170 of the 389 development sessions fall
inside the twelve-month window, so adopting it would have discarded 219 of them.
Publication reads the adopted window from
`configs/rp2_v3_study_window.json` and refuses a run that does not match it.

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
  - The project hooks run Graphify after commits/branch switches and synchronize the isolated GBrain source after the same events. For an immediate refresh, run `scripts/sync_project_knowledge.ps1`.
  - `scripts/phase8_watchdog_health.py` audits whether the Phase 8 watchdog's body actually ran on a given date, out of band. It exists but is **not armed**: nothing schedules or calls it, so run it by hand — `uv run python scripts/phase8_watchdog_health.py --date YYYY-MM-DD` — until an owner wires it into a task. It reads only `phase8_watch.log`; no evaluator, no holdout.
  - **GBrain autosync is NOT running, as of 2026-08-21.** `MDS650_Knowledge_AutoSync` is Disabled (last result `0x00000040`), and the isolated database it needs — `gbrain_mds650` on `127.0.0.1:5433`, per `%USERPROFILE%\.mds650\.gbrain\config.json` — has nothing listening on that port. `query_project_knowledge.ps1` therefore exits non-zero with `ECONNREFUSED`; it does **not** fall back to a global corpus, which is the behaviour the isolation requires. Graphify alone is unavailable through that script too: it seeds its query from GBrain before running, so a down database blocks both engines. Until the database is up, use `graphify query` directly against the repository-local `graphify-out/`. Starting the database and re-enabling the task are owner actions.

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

**That instruction is currently blocked, and deliberately so.** The canonical
tree stopped projecting the public repository when the RP2-v3 gates landed there
as pull requests: the two histories are disjoint, and the script's closing
`git push --force` would drop every published commit
(`docs/rp2_v3/MIRROR_HAZARD.md` measures 392). `publish_mirror.sh` therefore runs
`scripts/publish_ancestry_guard.py` as check 4 and refuses unless the branch it
would overwrite is contained in what replaces it. Verified against the live
remote: the guard refuses with `ancestry violation … would drop 392 published
commit(s)`. Unblocking it is an owner decision — adopt the public lineage, or
publish somewhere other than `main` — not a code change, and not something to
work around. `SKIP_TIER2=1` skips the local gates only; it does not and must not
bypass check 4.

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

## RP2-v3: plan maestro vinculante

Antes de tocar nada de RP2-v3, lee `docs/rp2_v3/RP2_V3_MASTER_PLAN.md`. Es el plan
del propietario, íntegro y por gates, y manda sobre cualquier atajo. Su regla
central: cada gate es un PR separado, con tests que fallan antes de la corrección,
métricas antes/después y un criterio objetivo de aprobación. El orden de los doce
PRs de su §24 no se altera.

### La línea base local no es la que el plan supone

El plan fija como punto de partida `8c01b0a0fb329013e5c335f5f9af6b516ffaf6a0` y
manda `git switch main; git pull --ff-only origin main`. **Eso falla aquí**, y no
por un error del plan: este repositorio local y el espejo público tienen
historias injertadas y disjuntas.

Verificado el 2026-08-20:

- `main` local está en `dbd571d`; el `main` del espejo está en `8c01b0a`.
- `8c01b0a` sí existe en el object store local (viene de `origin`) y sí contiene
  todo el trabajo de RP2-v2.
- Ninguno de los dos es ancestro del otro, así que `--ff-only` aborta con
  "Not possible to fast-forward".

Arranca desde `origin/main` directamente:

```powershell
git fetch origin --prune
git rev-parse origin/main          # el tip remoto actual, sea cual sea
git worktree add ".worktrees/<gate>" -b "<rama>" origin/main
```

`8c01b0a` queda como la procedencia de la línea base RP2-v2, no como una
precondición. En cuanto se fusionó el primer gate, `origin/main` dejó de valer
`8c01b0a`, y cada gate posterior arranca del tip remoto del momento — que es
precisamente el gate anterior ya fusionado, como manda la cascada del §24.

No fuerces el `main` local a coincidir ni reescribas su historia sin decisión
explícita del propietario: el injerto es deliberado y la evidencia congelada
depende de él.

### Cohortes selladas

`sealed_cohorts_read = 0` en todo el programa. Ninguna cohorte de confirmación —
C, Phase 8, Phase 9 — se lee durante el desarrollo de RP2-v3, ni siquiera para
mirar su tamaño. Cualquier lectura exige autorización escrita del propietario.
