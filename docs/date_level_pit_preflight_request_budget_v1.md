# Date-level PIT preflight request budget v1

## Estado y alcance

El presupuesto es un artefacto estático, local y sin transporte. Deriva únicamente de las ocho
assets y siete sesiones declaradas en el plan v1, y de descriptores ya configurados en el
catálogo. No ejecuta llamadas, no construye clientes de proveedor y no expone detalles de rutas.

Su estado es `CANDIDATE_AUTHORIZATION_REQUIRED`: no autoriza adquisición, ni confirma
entitlements, disponibilidad, precios o gasto.

## Conteos deterministas

Hay `7 × 8 = 56` asset-days.

- FMP: una comprobación de un minuto por asset-day: `56` solicitudes.
- Unusual Whales: un probe Range de metadatos por sesión, cacheado entre assets: `7` solicitudes.
- Massive: una búsqueda inicial de contrato por asset-day: `56` solicitudes. La cotización as-of
  puede añadirse exactamente una vez por asset-day, solo después de resolver el contrato:
  máximo condicional `56` solicitudes.

Por tanto, el conteo inicial no condicional es `56 + 7 + 56 = 119`. Si cada búsqueda inicial
resuelve el contrato, su cota superior es `119 + 56 = 175`.

El límite explícito para búsqueda de contrato Massive es tres páginas por asset-day. Bajo ese
límite, la cota total es `56 + 7 + (3 × 56) + 56 = 287` solicitudes. Si una continuación exigiera
una cuarta página, el futuro ejecutor debe detenerse con
`FAILED_CLOSED_CONTRACT_PAGINATION_CAP_EXCEEDED`, sin solicitar cotización as-of para ese
asset-day.

## Autorización y costes

Los conteos son límites operativos, no una estimación de precio ni una afirmación de facturación.
La autorización de coste permanece externa al artefacto y debe pasar los gates de ejecución antes
de cualquier actividad futura.

## Reproducción local

El artefacto se serializa como JSON UTF-8 canónico, con claves ordenadas y newline final. Su
`semantic_self_hash` cubre el objeto sin ese campo, por lo que una repetición con los mismos inputs
produce los mismos bytes.

```powershell
uv run pytest tests/unit/test_date_level_pit_preflight_request_budget_v1.py
```
