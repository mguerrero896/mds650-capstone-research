# Publishing the mirror would destroy the RP2-v3 cascade

`scripts/publish_mirror.sh` ends with

```bash
git -C "$MIRROR" push --force "$REMOTE" main
```

and `$REMOTE` is `mguerrero896/mds650-capstone-research` — the same repository the twelve
RP2-v3 pull requests were opened against and merged into. The script builds the mirror from
the canonical checkout's `HEAD`, strips the gated paths, and force-pushes the result over
`main`.

## Measured

```text
canonical local HEAD   3e86f77  (branch rp2-v2-remediation)
origin/main            e2ca054  (Every published number carries the run that produced it, #13)
git merge-base         -        no common ancestor
commits on origin/main not in the local branch   392
commits in the local branch not on origin/main   308
```

The two lineages are disjoint. Running the script as it stands would replace 392 commits —
every RP2-v3 gate from the contract through the versioned Supabase results — with a history
that has never contained them, and `--force` means the remote would not refuse it.

## Why the script is not wrong

It was written when the canonical tree was the only source and the public repository was a
stripped copy of it. That stopped being true when the RP2-v3 work started landing through
pull requests opened against the public repository directly: the public repository became a
lineage of its own, and the mirror script still assumes it is a projection.

## What alignment requires

One of these, and it is a decision about the repository rather than a code change:

1. **The canonical tree adopts the public lineage.** The RP2-v3 history on `origin/main`
   becomes the canonical history, the local branch is reconciled onto it, and the mirror
   script continues to work as a projection afterwards.
2. **The mirror publishes to a branch, not over `main`.** The script pushes the stripped
   canonical history somewhere that is not the branch the pull requests merged into, and
   what `main` means is stated.

Until one is chosen, do not run `scripts/publish_mirror.sh`. Nothing in the RP2-v3 gates
needs it: the gates publish through pull requests, and the gated-data stripping they rely on
is enforced by `.gitignore` and by the pointer register rather than by the mirror filter.
