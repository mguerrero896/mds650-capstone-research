# Byte-bound evidence line-ending recovery — 2026-08-15

## Incident

A new Windows worktree inherited `core.autocrlf=true`. Git materialized several
historical JSON evidence files with a different line ending from the bytes used
when their SHA-256 bindings were frozen. Nine global tests failed closed before
the independent replication target was read.

## Root cause and correction

The JSON semantics and self-hashes were unchanged; only CRLF versus LF bytes
differed. Normalizing the affected inputs to their originally registered line
ending reproduced the existing hashes exactly. No hash constant, scientific
claim, target, prediction, loss, or result was rebaselined.

`.gitattributes` now records the byte-level EOL contract. Most JSON evidence is
LF. A small set of inherited manifests remains CRLF because downstream frozen
artifacts explicitly bind those original byte identities.

## Verification

- historical readiness and provider-timing policy tests: 11 passed;
- B1Q panel eligibility tests: 7 passed;
- full suite: 994 collected, 982 passed, 12 skipped, 0 failed;
- global coverage: 81.56%, above the 80% gate;
- Ruff: passed;
- strict Mypy: 206 source files, 0 errors.

The repair is operational only. It does not change whether B1 improves B0 or
whether B2 replicates; those conclusions remain governed by the frozen
independent-replication protocol.
