#!/usr/bin/env bash
# Republish the GitHub mirror from the canonical (shallow) repo.
# As of 2026-08-18 the mirror is prepared for PUBLIC visibility: every path in
# scripts/_gated_exclude_list.txt (licensed-derived granular datasets) is stripped
# from the ENTIRE published history via git-filter-repo. Public material carries
# their SHA-256 pointers in data/GATED_DATA_POINTERS.json instead.
# See docs/consolidation_record_20260817.md for the graft rationale.
set -euo pipefail
# Tier-2 preflight (decision 63): a publish is REFUSED unless the full local
# gates pass, including the exact replica of the hosted hermetic job (ci-sim).
# This is what keeps red runs — and their failure emails — off GitHub.
# Escape hatch for emergencies only: SKIP_TIER2=1 (leaves a loud trace).
if [ "${SKIP_TIER2:-0}" != "1" ]; then
    echo "[publish] running tier-2 gates (set SKIP_TIER2=1 only in an emergency)"
    uv run python scripts/run_local_evidence_gates.py || {
        echo "PUBLISH REFUSED: tier-2 gates failed — nothing was pushed" >&2; exit 1; }
else
    echo "[publish] WARNING: SKIP_TIER2=1 — publishing without local gates" >&2
fi
ROOT_COMMIT=2bcd0ca47a5205ebfb49bea88233353e32d66ef4
REMOTE=git@github-mds650:mguerrero896/mds650-capstone-research.git
CANON=$(pwd)
EXCLUDES="$CANON/scripts/_gated_exclude_list.txt"
MIRROR=$(mktemp -d)/mirror
git replace --graft "$ROOT_COMMIT"
trap 'git replace -d "$ROOT_COMMIT" 2>/dev/null || true' EXIT
git init -q -b main "$MIRROR"
git fast-export --all --reencode=yes | git -C "$MIRROR" fast-import --quiet
# Strip gated data from every commit of the published lineage.
(cd "$MIRROR" && uvx git-filter-repo --force --invert-paths --paths-from-file "$EXCLUDES" >/dev/null)
# Check 1: no gated path may survive anywhere in the published history.
if (cd "$MIRROR" && git log --all --name-only --pretty=format: | sort -u | grep -Fxf "$EXCLUDES" | head -1) ; then
    echo "GATED PATH LEAKED INTO PUBLISHED HISTORY" >&2; exit 1
fi
# Check 2: every non-gated file at canonical HEAD must match blob-for-blob.
DIFF=$(comm -3 \
    <(git ls-tree -r HEAD | awk '{print $3" "$4}' | grep -vFf <(awk '{print $0}' "$EXCLUDES") | sort) \
    <(git -C "$MIRROR" ls-tree -r main | awk '{print $3" "$4}' | sort) | head -3)
if [ -n "$DIFF" ]; then
    echo "TREE MISMATCH (excluding gated paths):" >&2; echo "$DIFF" >&2; exit 1
fi
git -C "$MIRROR" push --force "$REMOTE" main
git -C "$MIRROR" push --force "$REMOTE" --tags
echo "mirror published: canonical $(git rev-parse --short HEAD) -> mirror $(git -C "$MIRROR" rev-parse --short main) (gated data stripped)"
