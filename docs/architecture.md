# MDS650 pipeline architecture

> **SUPERSEDED (2026-08-18).** This document describes the pre-pilot boundary and is
> kept as historical record only. The current project state is `STATUS.md` (root,
> auto-generated) and the document hierarchy is `docs/INDEX.md`.

## Boundary

The local Python package under `src/mds650` is the source of truth for contracts,
validation, normalization and later pipeline execution. Colab is orchestration and
presentation only: it loads a tagged repository revision, reads Colab Secrets by
presence, calls imported package functions and exports sanitized manifests. It must
not contain duplicated production logic or hidden notebook state.

## Evidence flow

```text
bounded provider request
        |
        v
immutable raw payload (restricted storage, SHA-256)
        |
        v
sanitized provider-audit manifest (Schema 1.1)
        |
        +--> contract/schema/quality gates
        |
        v
six component tables + provenance
        |
        v
five-minute forecast origins --> RV30 target (31 prices)
        |
        v
frozen assets --> B0 / B1 / B2 evaluation
```

The current recovery boundary stops after bounded evidence, contracts, fixtures and
gates. A manifest with `authorized_for_backfill=false`, an unresolved PIT timestamp,
or an unresolved FMP bar convention cannot flow to the pilot.

## Provider responsibilities

| Provider | In scope | Explicit boundary |
|---|---|---|
| FMP Ultimate | Eight-asset one-minute OHLCV and structured earnings audit | Calendar, adjustment, halt and bar start/close semantics must pass first |
| Unusual Whales | Flow alerts, ordinary IV/skew/term-structure field probes and pagination | REST alert fields do not establish PIT availability; Kafka fields are not copied into REST evidence |
| Massive Options Advanced | Event-directed contract reference, trades and quotes | No retrospective full-OPRA quote download; entitlement remains a gate |

## Storage and reproducibility

Raw licensed responses remain outside Git in restricted storage. Tracked artifacts contain
only sanitized schemas, hashes, diagnostics, fixtures and reports. Each normalized row
must retain `run_id`, provider response identity, source hash and UTC/NY timestamps. Every
execution records repository revision, lockfile state, configuration hash and safety flags.

## Evaluation boundary

B0 contains underlying and market controls. B1 adds ordinary option state only after
point-in-time availability is proven. B2 adds unusual activity. The sole primary contrast
is `Delta_Q = QLIKE(B1) - QLIKE(B2)` with the same eligible origins and day-clustered
paired bootstrap. No final evaluation is valid while B1 or the common-history gate is red.
