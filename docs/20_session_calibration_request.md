# Solicitud condicionada de calibración de 20 sesiones

Estado: **NO AUTORIZADA PARA EJECUCIÓN AUTOMÁTICA**.

La solicitud se prepara únicamente con las cinco sesiones ya observadas; no
descarga ni reserva nuevas sesiones. La ventana propuesta son las veinte
sesiones de negociación inmediatamente anteriores al 13 de julio de 2026, sin
incluir las cinco sesiones del Pilot V2.

## Estimación preliminar

| escenario | raw ZIP | Parquet | combinado | combinado + 30% margen |
|---|---:|---:|---:|---:|
| media diaria × 20 | 30.35 GB | 5.12 GB | 35.47 GB | 46.12 GB |
| P95/máximo observado × 20 | 34.81 GB | 5.69 GB | 40.50 GB | **52.65 GB** |

La estimación P95 es conservadora: la muestra contiene cinco días y su P95 se
aproxima por el máximo observado. No incluye memoria pico, archivos temporales,
índices ni espacio de recuperación; por ello el margen del 30% es un mínimo
operativo, no una garantía de capacidad.

## Condiciones de autorización

Solo se podrá solicitar la ejecución cuando B1a alcance la cobertura definida,
no exista fuga PIT, al menos cuatro activos pasen common-history, el pipeline
sea reanudable por día, tests y esquemas pasen y el espacio libre confirmado
supere 52.65 GB. La calibración se limitará a percentiles trailing, MAD,
normalización por activo/hora y prevalencia natural; no incluye modelos,
QLIKE ni test final.
