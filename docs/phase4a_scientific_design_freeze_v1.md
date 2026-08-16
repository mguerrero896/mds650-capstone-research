# Phase 4A — Scientific design freeze

Estado de esta revisión: **PARTIAL / local-only**. El diseño está congelado como
convención de investigación, pero no se autoriza backfill, entrenamiento ni
evaluación fuera de muestra.

## Pregunta y estimando

> “Do continuous unusual options-activity features improve out-of-sample RV30
> forecasting beyond information contained in the underlying market and
> conventional options-state variables?”

La afirmación es incremental y predictiva; no es una afirmación causal ni una
afirmación sobre intención del operador.

El estimando futuro será la diferencia de pérdida esperada entre B1Q y B2 sobre
los mismos orígenes, activos y fechas que sobrevivan a los filtros PIT. La
evaluación aún no existe y queda fuera de este objetivo.

## Unidad y target

Una fila es un activo `i`, una sesión regular XNYS y un origen `t` de cinco
minutos. El target es RV30 no anualizada:

```text
r(i,t+j) = ln(C(i,t+j) / C(i,t+j-1)), j=1,...,30
RV30(i,t:t+30) = sum_j r(i,t+j)^2
```

Se requieren exactamente 31 precios: el cierre ancla disponible en `t` y los
30 cierres futuros. El repositorio contiene RV30, no RV10.

## Diseño congelado

| Decisión | Status | Source | Evidence | Assumption class | Consequence |
|---|---|---|---|---|---|
| Horizonte | PASS | owner decision and contract | `src/mds650/targets.py`; `artifacts/common_sample/common_matrix_profile_v1.json` | HUMAN_APPROVED_RESEARCH_ASSUMPTION | No se implementa RV10. |
| Origen | PASS | project contract | `specs/001-pit-options-rv30/` | PROVIDER_CONFIRMED_FACT for session calendar; design convention for five-minute grid | `asset|session_date|forecast_origin_utc` is the key. |
| FMP availability | PARTIAL | authenticated probe + owner approval | `artifacts/pit/fmp_bar_semantics_v3.json` | HUMAN_APPROVED_RESEARCH_ASSUMPTION | raw+1m primary; raw+2m sensitivity; no provider claim. |
| UW availability | PARTIAL | retained Full Tape and documentation | `artifacts/pit/uw_created_at_semantics_v1.json` | HUMAN_APPROVED_RESEARCH_ASSUMPTION + UNRESOLVED_LIMITATION | `max(executed_at,created_at)`; 60s primary; 120/300 sensitivity. |
| Massive quotes | PASS for selected rows | authenticated local evidence | `artifacts/b1_full_origin/b1_origin_matrix.parquet` | AUTHENTICATED_EMPIRICAL_EVIDENCE | `sip_timestamp <= origin`, positive bid, ask>bid, age/spread filters. |
| Universe | PASS as purposive universe | project decision | `specs/001-pit-options-rv30/spec.md` | HUMAN_APPROVED_RESEARCH_ASSUMPTION | Eight liquid assets; not the US equity market. |
| Earnings | PASS for exclusion | approved design | `docs/earnings_pit_contract_v2.md` | HUMAN_APPROVED_RESEARCH_ASSUMPTION | Actual EPS/revenue are excluded from primary predictors. |
| Missingness | PASS | engineering contract | `artifacts/common_sample/common_matrix_exclusions_v1.parquet` | PROVIDER_CONFIRMED_FACT + design rule | No zero substitution, interpolation or silent repair. |
| Model and inference method | UNRESOLVED | not approved in this phase | `artifacts/methodology/` | FUTURE_METHOD_CANDIDATE | No method is selected or implemented. |

## Information sets

- **B0:** lagged underlying OHLCV and session controls available at the origin.
- **B1Q:** B0 plus ordinary option state reconstructed from Massive quotes and
  valid historical contracts.
- **B2:** B1Q plus continuous Full Tape activity aggregates. `unusual_event` is
  metadata only until a trailing calibration on prior sessions is approved.

The strict matrix requires every mandatory field in B0, B1Q and B2. The
availability-aware matrix retains valid B0/RV30 rows with explicit missingness.
Calibration rows precede pilot rows; no pilot-derived transform is used.

## Permitted and forbidden claims

Permitted: engineering coverage, reproducible as-of joins, missingness and
descriptive sample differences. Forbidden: causal claims, informed-trading or
direction claims, out-of-sample performance, final asset selection, or a claim
that `created_at` is publication time.

## Later human decisions

The owner must approve any provider-semantic closure, backfill execution window,
primary model, tuning policy, final test dates, inference procedure and asset
freeze. This Phase 4A report is not such approval.
