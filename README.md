# MDS650 — Point-in-Time Options Activity for RV30 Forecasting

Este repositorio es la fuente modular y auditable del proyecto que estudia si el estado
ordinario de las opciones y la actividad derivada de sus operaciones mejoran el pronóstico
fuera de muestra de la varianza realizada durante los siguientes 30 minutos (`RV30`).

## Estado verificable al 14 de agosto de 2026

| Área | Estado |
|---|---|
| Objetivo | `RV30`: 31 cierres consecutivos producen exactamente 30 log-retornos de un minuto. |
| Datos | FMP, Massive y Unusual Whales fueron auditados y materializados en paneles históricos; los datos pesados y licenciados viven fuera de Git. |
| B1 frente a B0 | No está confirmado globalmente. La reevaluación forense vigente muestra dependencia del modelo y un resultado Gamma desfavorable. |
| B2 frente a B1 | Existe una señal dirigida positiva con Gamma, pero LightGBM no la confirma y `confirmed_contrasts` sigue vacío. No es un edge universal. |
| Timing PIT | La evidencia existente es válida bajo supuestos temporales registrados; no demuestra una latencia universal de publicación de los proveedores. |
| Uso | Investigación académica solamente. No ejecuta órdenes, no constituye un backtest de P&L y no prueba rentabilidad operativa. |

La narración completa, el catálogo archivo por archivo, las uniones, los backfills, los
modelos, los resultados, las brechas y el roadmap están en
[`reports/MDS650_MASTER_PROJECT_DOSSIER.md`](reports/MDS650_MASTER_PROJECT_DOSSIER.md).

## Jerarquía de autoridad

1. Artefactos inmutables, hashes, manifiestos y logs de ejecución.
2. Contratos y especificación bajo `specs/001-pit-options-rv30/`.
3. Decisiones y riesgos en `docs/methodology_decisions.md` y `docs/risk_register.md`.
4. El expediente maestro como índice humano de las fuentes anteriores.

Una conclusión posterior no reescribe un artefacto anterior: lo clasifica como vigente,
exploratorio, inválido, supersedido o de diagnóstico.

## Entorno y reproducción

- Runtime congelado: Python 3.12 con `uv` y `uv.lock`.
- Código y documentación: repositorio Git local.
- Datos pesados, ZIP licenciados, Parquet y cachés: `D:\MDS650`.
- Secretos: variables de entorno; nunca código, notebooks, logs o manifiestos.

Puerta local mínima:

```powershell
uv sync --frozen
uv run pytest -q
uv run ruff check src scripts tests
uv run mypy src scripts
```

La reproducción académica sin licencias usa fixtures sanitizados. La reproducción completa
requiere credenciales y derechos vigentes de los tres proveedores, además de respetar los
manifiestos, calendarios, cutoffs y puertas de almacenamiento registrados.

## Estado tras la consolidación del 17 de agosto de 2026

- `main` es la única rama canónica (decisión 50); el estado sucio pre-consolidación quedó
  preservado íntegro en `archive/meeting-dirty-20260816` y en
  `D:\MDS650\backups\repo_20260817\`. Registro completo:
  [`docs/consolidation_record_20260817.md`](docs/consolidation_record_20260817.md).
- `B1v3` completó su confirmación one-read el 14 de agosto (decisión 48): resultado
  vinculante `POSITIVE_BUT_NOT_GLOBALLY_CONFIRMED` — incremento B2 positivo y robusto a las
  cinco sensibilidades de timing bajo Gamma, invertido bajo LightGBM; B1v3a no supera a B0.
- La vista canónica de todas las campañas está en
  [`docs/results_reconciliation_v2.md`](docs/results_reconciliation_v2.md); la jerarquía de
  reporte vinculante es la decisión 53.
- Cohortes selladas (Validation A/B, Phase 8): disposición pendiente del propietario (D006,
  [`docs/sealed_cohorts_disposition_v1.md`](docs/sealed_cohorts_disposition_v1.md));
  moratoria de nuevas campañas retrospectivas (decisión 52).
- Evidencia pesada montada en `D:\MDS650\evidence_root` (`MDS650_EVIDENCE_ROOT`);
  `MDS650_DATA_ROOT=D:\MDS650`.

## Nota sobre el notebook

`notebooks/MDS650_Research_Pipeline.ipynb` es una plantilla de orquestación para
Colab/entornos hospedados. Nunca ha sido ejecutado de extremo a extremo y no es la vía de
reproducción de ningún resultado reportado; la reproducción real usa los scripts y las
puertas descritas arriba. No lo cites como pipeline ejecutado.
