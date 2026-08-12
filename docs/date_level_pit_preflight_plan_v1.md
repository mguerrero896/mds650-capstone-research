# Date-level PIT preflight plan v1

## Estado

`CANDIDATE_APPROVAL_REQUIRED`. Este artefacto es un plan calendar-derived local, no un
preflight PIT ejecutado. Sus flags vinculantes son `NO_PROVIDER_CALLS_EXECUTED=true` y
`NOT_AUTHORIZATION_FOR_ACQUISITION=true`.

## Alcance fijo

- Assets: `SPY`, `QQQ`, `AAPL`, `MSFT`, `NVDA`, `TSLA`, `AMZN`, `META`.
- Sesiones sentinel: anomalía UW (2025-10-20), cierres tempranos (2025-11-28 y
  2025-12-24), regular de invierno (2026-01-20), antes/después de DST (2026-03-06 y
  2026-03-09) y regular de verano (2026-07-13).
- Fuente de calendario local: `exchange_calendars`, exchange `XNYS`, zona
  `America/New_York`.

Cada sesión contiene tipo (`REGULAR` o `EARLY_CLOSE`), apertura y cierre UTC, longitud de
sesión, timezone y resultado de validez XNYS. El plan no formula una afirmación sobre datos,
costes, disponibilidad, latencia o calidad de un proveedor externo.

## Integridad y reproducción

El generador serializa JSON UTF-8 canónico (keys ordenadas, separadores compactos y newline
final). `semantic_self_hash` es SHA-256 del mismo objeto sin ese campo; por tanto detecta
cambios semánticos sin depender de espaciado.

```powershell
uv run python scripts/generate_date_level_pit_preflight_plan_v1.py
uv run pytest tests/unit/test_generate_date_level_pit_preflight_plan_v1.py
```

El resultado sólo prepara una revisión humana de aprobación. No habilita adquisición ni abre
ningún flujo OOS.
