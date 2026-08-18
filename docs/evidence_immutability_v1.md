# Evidence immutability contract (v1, 2026-08-18 — decision 62)

Reviewer correction accepted: `write_immutable_raw()` made evidence *logically*
immutable (the function refuses to replace bytes), but nothing stopped another
script or a direct filesystem write — and the 2026-08-18 frozen-manifest overwrite
incident (delay reruns clobbering `b2_manifest.json` / `panel_manifest.json` /
model card, restored from git) proved the risk is real. This contract adds the
physical layer.

## Layers

| # | Layer | Mechanism | Catches |
|---|---|---|---|
| 1 | Append-only registry | `data/FROZEN_ARTIFACTS.json` — 61 frozen artifacts pinned to SHA-256 at freeze (all gate `results.json`, every method freeze / preregistration, the C5 frozen forecasts + manifests + model card, Phase 8/9 protocols). Managed only by `scripts/freeze_registry.py --add`; a path registers once, digests never change, amendments are NEW paths | Defines the frozen set |
| 2 | Physical tripwire (CI + local) | `tests/contract/test_frozen_artifacts_registry.py` re-hashes every registered file on every hosted CI run and every tier-2 run; sidecars must agree | ANY mutation, by any tool |
| 3 | Writer guard | `mds650.storage.assert_outside_frozen(path)` raises `FROZEN_ARTIFACT_WRITE_REJECTED` before a write can target a registered path; wired into the B2-confirmation builder/evaluator (the incident site). No "update frozen file" operation exists anywhere | In-process overwrites |
| 4 | Content-addressed writes | `mds650.storage.write_content_addressed(payload, root, protocol_id)` → `root/protocol_id/<sha256>.bin`. The filename IS the hash: different bytes = different path, overwrite impossible by construction. Required write path for new frozen evidence | Future evidence |
| 5 | Read-only flags | `scripts/freeze_registry.py --lock` sets the OS read-only bit on all registered files locally | Casual local edits |
| 6 | Release snapshot | GitHub Release `evidence-freeze-2026-08-18` on the public mirror with the registry as asset — an off-machine, timestamped copy of the frozen state | Mirror tampering |

Hash convention: text files are hashed over LF-normalized bytes (equal to the git
blob under `.gitattributes eol=lf`, so identical on Windows and the ubuntu runner);
parquet is hashed raw. A pure EOL flip is checkout smudge, not content mutation.

## Honest limitations

- **WORM/Object Lock**: Supabase Storage has no Object Lock; the service-role key
  can technically delete bucket objects. Compensating controls: hashes pinned in
  `data/GATED_DATA_POINTERS.json` + registry (layer 1–2), upload/fetch scripts
  verify round-trip, and the GitHub Release snapshot is provider-independent. True
  WORM would require an S3 bucket with Object Lock — available if the residual ever
  matters, at extra cost.
- **Signed tags**: the mirror rewrite limitation of `docs/ci_contract_v1.md`
  applies; a "Verified" release tag requires the owner to add an SSH signing key in
  GitHub settings (owner action, offered).
- Layer 5 is advisory on Windows (any admin can clear the bit); layers 2 and 6 are
  the ones that cannot be silently bypassed.

## Rules going forward

1. Freezing an artifact = `freeze_registry.py --add <path>` in the same commit.
2. Never edit a registered file; corrected analysis = new versioned path,
   registered as a new entry.
3. New evidence-producing scripts call `assert_outside_frozen()` before writes and
   use `write_content_addressed()` for primary payloads.
4. After each freeze batch: `--lock` locally and a fresh release snapshot on the
   next publish.
