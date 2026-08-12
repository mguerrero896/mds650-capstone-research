# Date-level PIT preflight runner v1

El runner prepara un reporte fail-closed sobre el plan calendar-derived v1. Por defecto es
dry-run: bloquea toda request y produce `DRY_RUN_NETWORK_BLOCKED`. El CLI no instala ningún
transporte de red; aun con `--execute`, el catálogo configurado sin transporte explícito termina
en `NETWORK_TRANSPORT_UNCONFIGURED`.

La única ruta ejecutable por código es una función inyectable para tests o futura integración.
Una respuesta de esa ruta queda etiquetada
`INJECTED_TRANSPORT_COMPLETED_NOT_PROVIDER_VALIDATED`: no constituye validación, autenticación ni
evidencia de proveedor.
Exige simultáneamente `--execute`, el hash semántico exacto del plan, la aserción explícita de
gasto incremental cero, al menos 80 GiB libres en `D:`, y presencia booleana de las tres claves
(`FMP_API_KEY`, `UNUSUALWHALES_API_KEY`, `MASSIVE_API_KEY`). Nunca extrae ni imprime sus valores.
La aserción de gasto es una declaración de gate, no una afirmación independiente sobre costes.

El catálogo versionado por defecto es
`config/date_level_pit_preflight_endpoint_catalog_v1.json`, validado contra
`specs/001-pit-options-rv30/contracts/date-level-pit-preflight-endpoint-catalog-v1.schema.json`.
Registra la ruta FMP de 1 minuto, un probe de rango histórico Full Tape de Unusual Whales sólo de
metadatos y los contratos/cotizaciones as-of de Massive. El probe UW usa un target lógico, no
declara una URL de proveedor ni semántica de timestamps no documentada. Massive fija
`timestamp.lte` en nanosegundos, `sort=timestamp`, `order=desc` y `limit=1`.

El catálogo configura FMP, Unusual Whales y Massive para diagnóstico, pero no autoriza
adquisición ni crea clientes o transporte. Una ejecución futura sigue exigiendo autorización
explícita, hash semántico aprobado, aserción de gasto incremental cero, al menos 80 GiB libres en
`D:`, presencia booleana de las tres claves y un transporte inyectado/revisado. El reporte nunca
emite request targets, URLs, bodies ni payloads; sólo un hash de la forma de respuesta.

```powershell
uv run python scripts/run_date_level_pit_preflight_v1.py
uv run pytest tests/unit/test_date_level_pit_preflight_v1.py tests/contract/test_date_level_pit_preflight_report_v1.py
```

Las escrituras usan create-or-identical; bytes distintos en un path existente fallan con
`REPORT_OUTPUT_CONFLICT`.
