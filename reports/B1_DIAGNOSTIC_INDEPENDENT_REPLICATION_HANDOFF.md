# B1 Diagnostic and Independent B2 Replication Handoff

Fecha de cierre: 2026-08-15
Rama: `codex/b1-diagnosis-replication-20260815`
Commit base: `d2a4eb6e763606c26891b9506a17b418a1b66b8f`

## 1. Decisión ejecutiva

La ejecución técnica fue completada y es reproducible, pero la hipótesis de edge global no fue
confirmada en la replicación independiente.

- Estado terminal preregistrado: `NOT_REPLICATED`.
- B1 frente a B0, modelo confirmatorio Gamma:
  `Delta QLIKE = QLIKE(B0) - QLIKE(B1v3a) = -0.00472640`.
- B2 frente a B1, modelo confirmatorio Gamma:
  `Delta QLIKE = QLIKE(B1v3a) - QLIKE(B2) = -0.00124585`.
- B1 frente a B0, LightGBM de robustez: `+0.00243754`, con intervalo que cruza cero.
- B2 frente a B1, LightGBM de robustez: `-0.00006091`, prácticamente nulo y con intervalo que
  cruza cero.
- Las fechas, features, modelos, hiperparámetros, inferencia y reglas terminales no fueron
  modificados después de observar RV30 o QLIKE.
- El objetivo de replicación fue leído una sola vez. No hubo reentrenamiento, tuning ni reintento
  condicionado al signo.

Por tanto, el proyecto produjo evidencia científica válida, pero no evidencia suficiente para
afirmar que B1 o B2 mejoran globalmente el pronóstico RV30 bajo el diseño confirmatorio congelado.

## 2. Diseño congelado

| Elemento | Contrato ejecutado |
|---|---|
| Desarrollo/diagnóstico | 60 sesiones XNYS, 2024-09-16 a 2024-12-09 |
| Replicación independiente | 30 sesiones XNYS, 2024-12-10 a 2025-01-24 |
| Universo | AAPL, AMZN, META, MSFT, NVDA y TSLA |
| Panel de replicación | 12,744 orígenes naturales de cinco minutos |
| Muestra común evaluable | 11,588 orígenes, 30 días y 6 activos |
| Objetivo | RV30 con 31 cierres y exactamente 30 retornos logarítmicos de un minuto |
| B0 | Estado del subyacente y mercado |
| B1v3a | B0 + nivel ATM IV y cambios exactos de 5 y 30 minutos |
| B2 | B1v3a + nueve features continuas de actividad de opciones preregistradas |
| Confirmatorio | Gamma GLM |
| Challenger | LightGBM, solo robustez |
| Métrica primaria | QLIKE |
| Inferencia | 10,000 bootstrap por día, seed 650, activos agrupados por día |
| Multiplicidad | Holm sobre los dos contrastes confirmatorios globales |
| MDE de entrenamiento | B1: 0.01289701; B2: 0.00812996 |
| Lecturas del objetivo independiente | 1 de 1; token consumido irrevocablemente |

Las identidades preregistradas principales fueron:

- exposure ledger: `1d26548c36c0c8616541386bbd19788847b275d28e07ac89a803397ec23af6df`;
- preregistration: `f233adb30209386d49670b8e035156d0949d5345f60421d745899eda05d58136`;
- method freeze: `e8a819c4cd5f1556142e3d662bed3554afdf26aea7aa0b12ca2da31a684d35fe`;
- result: `3e0f776ecc7f8b53861a380ce8bbd4b6bb9ac69452a87121eb40cb5a206b88a1`.

## 3. Diagnóstico de por qué B1 no mejora B0

El diagnóstico se ejecutó exclusivamente con las 60 sesiones de desarrollo. No leyó el objetivo
de replicación.

### 3.1 Causas descartadas

- No es una ausencia general de quotes: 767,376/767,376 intentos devolvieron una cotización.
- No es un fallo amplio de inversión IV: 755,772/767,376 inversiones fueron exitosas (98.49%).
- No es mala frescura general: edad mediana 2.22 s y P95 31.08 s.
- No es un spread general inaceptable: mediana 1.37% y P95 4.08%.
- No es rango deficiente ni una feature constante: la matriz B0+B1 tiene rango completo,
  condición 8.77 y ninguna columna de varianza cero.
- No es concentración exclusiva al cierre: la cobertura B1 independiente mínima por tercio fue
  75.89% y la cobertura global B1v3a fue 90.93%.

### 3.2 Causa respaldada por evidencia

El nivel ATM IV contiene señal, pero los dos cambios intradía adicionales son débiles después de
regularización. Los coeficientes Gamma estandarizados de desarrollo fueron:

| Feature B1v3a | Coeficiente |
|---|---:|
| Nivel log ATM variance, 30 DTE | 0.147143 |
| Cambio exacto de 5 minutos | -0.004748 |
| Cambio exacto de 30 minutos | 0.007359 |

B0 ya contiene controles de volatilidad y volumen parcialmente redundantes. El nivel ATM mantiene
información propia, pero su contribución incremental no es estable. En tres folds cronológicos de
desarrollo, el contraste B1 fue `+0.013131`, `-0.031584` y `-0.004535`; el agregado fue
`-0.007792`. La reversión más fuerte se concentró en TSLA durante el segundo fold. La causa
principal es, por tanto, inestabilidad temporal, transversal y de especificación, no una falla de
ingeniería de datos.

La replicación independiente confirma esa inestabilidad: Gamma favorece B0, mientras LightGBM
favorece B1 solo de manera pequeña e incierta.

## 4. Resultado científico independiente

Un contraste positivo favorece el conjunto de información expandido.

| Modelo | Contraste | QLIKE base | QLIKE expandido | Delta QLIKE | IC 95% | p Holm |
|---|---|---:|---:|---:|---:|---:|
| Gamma confirmatorio | B0 vs B1v3a | 0.15464887 | 0.15937527 | -0.00472640 | [-0.01270189, 0.00182714] | 0.3432 |
| Gamma confirmatorio | B1v3a vs B2 | 0.15937527 | 0.16062112 | -0.00124585 | [-0.00704436, 0.00399790] | 0.6887 |
| LightGBM robustez | B0 vs B1v3a | 0.13289305 | 0.13045550 | +0.00243754 | [-0.00088342, 0.00607967] | no confirmatorio |
| LightGBM robustez | B1v3a vs B2 | 0.13045550 | 0.13051642 | -0.00006091 | [-0.00108631, 0.00092795] | no confirmatorio |

Ningún efecto confirmatorio excedió su MDE de entrenamiento, ningún intervalo confirmatorio quedó
por encima de cero y ambos p-valores Holm fueron mayores que 0.05. El signo B1 cambia entre Gamma
y LightGBM; el signo B2 es negativo en ambos modelos.

## 5. Estabilidad

### 5.1 B1 frente a B0

- Gamma: B1 fue positivo en 1/6 activos (MSFT), negativo en los tres tercios de sesión y positivo
  solamente en el régimen de volatilidad normal.
- LightGBM: B1 fue positivo en 4/6 activos y en los tres tercios, pero el efecto global fue menor
  que el MDE, `p=0.1604` y su intervalo incluyó cero.
- TSLA volvió a mostrar la mayor contribución Gamma negativa (`-0.02986179`).

La evidencia no permite declarar un beneficio B1 global o estable; sí sugiere una interacción
modelo-régimen que puede estudiarse posteriormente en datos de desarrollo nuevos.

### 5.2 B2 frente a B1

- Gamma: B2 fue positivo en NVDA y TSLA, y negativo en AAPL, AMZN, META y MSFT.
- LightGBM: B2 fue positivo en AAPL, NVDA y TSLA, y negativo en AMZN, META y MSFT.
- Gamma fue positivo únicamente en el primer tercio de sesión y en alta volatilidad.
- LightGBM fue positivo únicamente en el tercio medio y en alta volatilidad.

Estas señales locales son heterogéneas y no autorizan selección posterior de activos o regímenes
con esta misma muestra.

### 5.3 Supuestos temporales conservadores

Se evaluaron FMP +2 minutos, Massive cutoffs de 60 y 300 segundos, y UW `created_at` de 120 y 300
segundos. Todos los intervalos B2 de sensibilidad cruzaron cero. El mejor signo aislado fue
LightGBM/FMP +2 (`+0.00112811`), también con intervalo que cruza cero; Gamma/UW 300 fue
`+0.00010214`, esencialmente nulo. No existe robustez temporal global.

## 6. Datos, adquisición y trazabilidad

- Full Tape UW: 30 ZIP y 240 Parquet auditados de nuevo contra sus hashes.
- Operaciones filtradas: 83,182,232.
- Almacenamiento Full Tape: 27.396 GiB raw y 4.495 GiB Parquet.
- B1Q Massive: 5,400 contract-days, 206,298,041 quotes y 382,320 intentos IV.
- Quotes futuros seleccionados: 0.
- Identidades duplicadas de intentos/payload: 0.
- B1v3a replication coverage: 90.93% global; mínimo por activo 90.07%; mínimo por tercio 75.89%.
- B2: 12,744/12,744 orígenes elegibles en cada una de las tres latencias; sidecar total 38,232.
- Panel común: 11,588 orígenes evaluables, sin balancing artificial.

## 7. Incidentes de implementación corregidos

1. El esquema B2 confundía el número de orígenes con el número de filas del sidecar de tres
   variantes. Se corrigió a 38,232 y el gate legacy quedó como enum explícito.
2. `target_moneyness` activaba por texto una defensa contra columnas target. Se documentó como
   metadato de diseño permitido y se mantuvo el rechazo estricto de `rv30`, `qlike`, pérdidas,
   residuos y predicciones.
3. El consumidor temporal esperaba nombres obsoletos `sensitivity_*`; se alineó con los nombres
   canónicos `latency_*` y se añadió regresión.
4. Se añadió reanudación hash-validada desde predictores temporales sellados para no repetir una
   reselección local de más de 20 GiB después de un fallo aguas abajo.
5. ZIP/Parquet y salidas B1Q se escriben mediante temporales y promoción atómica; no se aceptan
   archivos parciales.

## 8. Verificación técnica

| Puerta | Resultado |
|---|---|
| Pytest | 1,004 tests; 992 pass; 12 skip; 0 fail/error |
| Cobertura | 81.57%, umbral 80% aprobado |
| Ruff | PASS |
| Mypy `--strict` | 206 archivos, 0 errores |
| JSON Schema | 21 documentos de cierre, PASS |
| Self-hashes | 22 documentos, PASS |
| Evidencia final | 6/6 archivos ligados por SHA-256, PASS |
| Secretos/rutas personales | 0 hallazgos |
| Full Tape raw/Parquet | 270 archivos, 0 hash/readability issues |
| Replication outcome reads | exactamente 1 |
| Evaluation attempts | exactamente 1 |

Los skips corresponden a integraciones explícitamente no ejecutadas por la suite local; no hubo
fallos ocultos ni tests rebaselined para aceptar el resultado.

## 9. Artefactos principales

- Diagnóstico: `artifacts/b1_diagnostic_replication/diagnostic/diagnostic.json`
- Hallazgos B1: `docs/b1_diagnostic_findings_20260815.md`
- Preregistración: `artifacts/b1_diagnostic_replication/preregistration/preregistration.json`
- Adquisición UW: `artifacts/b1_diagnostic_replication/acquisition/full_tape_acquisition_manifest.json`
- Fuente B1Q: `artifacts/b1_diagnostic_replication/panel/b1q_source_manifest.json`
- B2 target-blind: `artifacts/b1_diagnostic_replication/panel/b2_predictor_manifest.json`
- Panel común: `artifacts/b1_diagnostic_replication/panel/common_predictor_manifest.json`
- Sensibilidades: `artifacts/b1_diagnostic_replication/panel/timing_common_manifest.json`
- Method freeze: `artifacts/b1_diagnostic_replication/method_freeze/method_freeze.json`
- Access ledgers: `artifacts/b1_diagnostic_replication/access/`
- Resultado sellado: `artifacts/b1_diagnostic_replication/result/result.json`
- Forecasts/evaluation: `D:/MDS650/b1_diagnostic_replication/evaluation/`
- Pruebas/cobertura: `artifacts/b1_diagnostic_replication/quality/`

## 10. Límites de afirmación

- FMP +1 minuto continúa siendo un supuesto de investigación conservador, no una confirmación
  contractual de first availability.
- UW `created_at <= origin - 60s` continúa siendo un proxy operativo, no publication time.
- Massive `sip_timestamp <= origin` demuestra orden temporal SIP, no first availability del REST.
- El resultado no prueba causalidad, intención informada, rentabilidad, costos de transacción ni
  preparación para trading real.
- No es válido reutilizar estas 30 sesiones para seleccionar nuevas features, activos, modelos o
  regímenes y después presentarlos como confirmación independiente.

## 11. Conclusión y siguiente decisión

La pregunta fue respondida de forma falsificable:

1. B1 no mejora B0 globalmente bajo Gamma; su contribución es débil, redundante en parte e
   inestable. LightGBM observa una mejora pequeña, pero no confirmatoria ni material.
2. La mejora B2 previa no se reproduce globalmente. El contraste es negativo en Gamma y
   esencialmente nulo-negativo en LightGBM.
3. Existen señales locales en NVDA, TSLA, alta volatilidad y algunos supuestos, pero no son
   estables ni pueden convertirse en una afirmación global usando esta misma muestra.

Recomendación: conservar este resultado como conclusión principal honesta. Cualquier intento de
reformular B1, segmentar B2 o ampliar potencia debe preregistrarse como un estudio nuevo y usar
fechas no expuestas; no debe optimizarse esta replicación para producir un signo favorable.
