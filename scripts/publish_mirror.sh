#!/usr/bin/env bash
# Republish the GitHub publication mirror from the canonical (shallow) repo.
# See docs/consolidation_record_20260817.md, addendum. Run from the repo root.
set -euo pipefail
ROOT_COMMIT=2bcd0ca47a5205ebfb49bea88233353e32d66ef4
REMOTE=git@github-mds650:mguerrero896/mds650-capstone-research.git
MIRROR=$(mktemp -d)/mirror
git replace --graft "$ROOT_COMMIT"
trap 'git replace -d "$ROOT_COMMIT" 2>/dev/null || true' EXIT
git init -q -b main "$MIRROR"
git fast-export --all --reencode=yes | git -C "$MIRROR" fast-import --quiet
# ponytail: non-commit refs (phase6-frozen blobs, checkpoints) intentionally skip the
# mirror; they travel in the release bundle instead.
CANON_TREE=$(git rev-parse main^{tree})
MIRROR_TREE=$(git -C "$MIRROR" rev-parse main^{tree})
[ "$CANON_TREE" = "$MIRROR_TREE" ] || { echo "TREE MISMATCH: $CANON_TREE vs $MIRROR_TREE" >&2; exit 1; }
git -C "$MIRROR" push --force "$REMOTE" --all
git -C "$MIRROR" push --force "$REMOTE" --tags
echo "mirror published: canonical $(git rev-parse --short main) -> mirror $(git -C "$MIRROR" rev-parse --short main)"
