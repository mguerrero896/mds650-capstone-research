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

## Próxima decisión metodológica

`B1v3` es una propuesta target-blind para reconstruir ATM IV, skew y estructura temporal con
geometría coherente de contratos. Su implementación y cualquier nueva evaluación permanecen
`PENDING_EXPLICIT_APPROVAL`; no se seleccionará una variante por el signo de RV30 o QLIKE.
