# Gated research data — access policy

The granular derived datasets of this project (15 files: 14 parquets plus one
quote-level diagnostic CSV, ~135 MB — per-origin
feature panels, row-level frozen forecasts, and quote-derived IV attempts) are built
from commercially licensed market-data feeds (FMP, Unusual Whales, Massive) and
**cannot be redistributed publicly** under the provider agreements. They are therefore
not in this repository. This is the project's registered *controlled auditability*
model, implemented literally.

## What IS public

Everything else: all source code, all tests, every methodology document, every
preregistration, and every **aggregate** result (QLIKE deltas, confidence intervals,
p-values, stability tables) in the `artifacts/**/results.json` files.

## How to verify integrity without the data

Every gated file's SHA-256 and byte size is committed in
[`GATED_DATA_POINTERS.json`](GATED_DATA_POINTERS.json). Any result JSON that consumed
a gated file records the same hash in its `inputs` block — the chain of custody is
fully checkable from public material alone.

## How to request the data (reviewers, examiners, replicators)

1. Open a GitHub issue on this repository titled `Data access request`, stating your
   affiliation and purpose, or contact the author directly.
2. The author verifies the purpose is research/review (not redistribution) and issues
   **time-limited signed URLs** for the requested files from private storage.
3. Verify each downloaded file against its SHA-256 in `GATED_DATA_POINTERS.json`, then
   run `scripts/fetch_gated_data.py --manifest <file-with-signed-urls>` (or download
   manually) and place files at their recorded `path`.
4. By requesting access you agree to use the data solely for verification/research and
   not to redistribute it.

Raw provider payloads (hundreds of GB) are never shared; full reproduction from
scratch requires live provider entitlements, as documented in the README.

## Research catalog database (Supabase Postgres, 2026-08-18)

Beyond Storage, the project's Pro Supabase instance (project `eqpyjikcewqaegnbaemf`)
now hosts a queryable research catalog — **aggregates and registry only, never
licensed provider values**:

| Table | Content | Source of truth in repo |
|---|---|---|
| `campaigns` | Frozen campaigns C1–C6 with input SHA-256 | `artifacts/gate1_inference/results.json` |
| `contrast_results` | Studentized statistics per contrast (estimate, cluster-t, Newey-West, wild bootstrap, ρ₁, Ljung-Box) | same |
| `mcs_cells` | Model Confidence Set membership per campaign × block length L | `artifacts/mcs_block_sensitivity/results.json` |
| `gated_files` | Registry of the 15 gated files (path, SHA-256, bytes, bucket object) | `data/GATED_DATA_POINTERS.json` |
| `access_grants` | Log of signed-URL grants (per-request discipline) | — (operational log) |

All tables have Row Level Security enabled with **no policies**: anonymous and
authenticated keys read nothing; access is service-role only (owner and owner's
agents). Sync is one-way, repo → database, idempotent:
`uv run python scripts/sync_supabase_catalog.py` (requires `SUPABASE_SERVICE_KEY`).
The repo artifacts remain the single source of truth; the database is a queryable
view of them, never an editing surface.
