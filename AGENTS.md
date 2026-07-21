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
  - The project hooks run Graphify after commits/branch switches and synchronize the isolated GBrain source after the same events. For an immediate uncommitted refresh, run `graphify update .` and `scripts/gbrain_sync.ps1` manually (both local-only, without embeddings).
