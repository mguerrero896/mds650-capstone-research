# Plan maestro de corrección RP2-v3

> **Documento de referencia vinculante.** Contenido íntegro tal como lo entregó el
> propietario del proyecto. Lo único reconstruido es el marcado matemático, que se
> corrompió al pegar el texto (las fórmulas LaTeX llegaron partidas en varias líneas con
> `===` y `---` donde debía haber un signo igual o un menos). No se ha añadido, quitado ni
> reinterpretado ninguna instrucción.

No conviene hacer otro PR gigantesco. Debes avanzar mediante **gates independientes**, donde cada gate tenga:

1. un problema bien delimitado;
2. tests que fallen antes de la corrección;
3. código mínimo que los haga pasar;
4. métricas antes/después;
5. un PR separado;
6. un criterio objetivo de aprobación.

El estado de partida verificable es `main` en el commit:

```text
8c01b0a0fb329013e5c335f5f9af6b516ffaf6a0
```

La rama está protegida y exige los checks `quality` y `hermetic`. El proyecto utiliza Python 3.12, `uv`, Ruff, mypy estricto y pytest con cobertura mínima de 80%.

La mejora "exponencial" que sí puede exigirse es en:

* frescura de B1;
* cobertura de datos;
* exactitud temporal de B2;
* reproducibilidad;
* reducción de grados de libertad;
* potencia estadística;
* trazabilidad;
* ejecución en cascada.

No se puede garantizar de antemano una mejora exponencial de QLIKE. Esa métrica debe responder a la información real del mercado, no a nuestro deseo de positividad.

---

# 0. Congelar formalmente RP2-v3

Antes de modificar código, crea:

```text
docs/rp2_v3/
├── RESEARCH_CONTRACT.md
├── IMPLEMENTATION_STATUS.md
├── SCORECARD_SCHEMA.md
└── SUPERSEDED_RESULTS.md
```

En `RESEARCH_CONTRACT.md` deja congelado:

```text
Primary target: RV30
Primary comparisons:
    B0 vs B0+B1
    B0+B1 vs B0+B1+B2
Primary loss:
    QLIKE
Primary models:
    Gamma GLM
    Ridge-log
    LightGBM-QLIKE
Inference unit:
    Trading session
Primary B1:
    Contemporaneous option-state snapshot
Primary B2:
    Point-in-time option-flow activity
No sealed confirmation cohort may be read during development.
```

También define los signos:

$$\Delta_{B1} = L(B0) - L(B0{+}B1)$$

$$\Delta_{B2\mid B1} = L(B0{+}B1) - L(B0{+}B1{+}B2)$$

El objetivo es:

$$\Delta_{B1} > 0, \qquad \Delta_{B2\mid B1} > 0.$$

### Criterio de salida

No empieces a modificar código hasta que este contrato esté comprometido en Git.

### Commit

```powershell
git add docs/rp2_v3
git commit -m "docs: freeze rp2 v3 research contract"
```

---

# 1. Actualizar y verificar la línea base local

Abre PowerShell dentro de la carpeta del repositorio:

```powershell
git fetch origin --prune
git switch main
git pull --ff-only origin main
git status --short
git rev-parse HEAD
```

La última instrucción debe devolver:

```text
8c01b0a0fb329013e5c335f5f9af6b516ffaf6a0
```

Sincroniza el entorno:

```powershell
uv sync --locked
```

Ejecuta la línea base hermética:

```powershell
uv run ruff check src scripts tests
uv run mypy src scripts
uv run pytest tests -q
```

Ejecuta también los gates locales que dependen de la evidencia privada:

```powershell
uv run python scripts/run_local_evidence_gates.py
```

Guarda la salida:

```powershell
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$Baseline = "artifacts/rp2_v3_baseline/$Stamp"
New-Item -ItemType Directory -Force $Baseline | Out-Null

git rev-parse HEAD |
    Set-Content "$Baseline/head_sha.txt"

uv run ruff check src scripts tests 2>&1 |
    Tee-Object "$Baseline/ruff.txt"

uv run mypy src scripts 2>&1 |
    Tee-Object "$Baseline/mypy.txt"

uv run pytest tests -q 2>&1 |
    Tee-Object "$Baseline/pytest.txt"

uv run python scripts/run_local_evidence_gates.py 2>&1 |
    Tee-Object "$Baseline/evidence_gates.txt"
```

### No avances si

* el repositorio está sucio;
* falla Ruff;
* falla mypy;
* falla pytest;
* falla el gate local de evidencia.

Primero debes resolver cualquier fallo preexistente y documentarlo.

---

# 2. Crear un worktree aislado

No trabajes directamente sobre `main`.

Comprueba si `.worktrees` está ignorado:

```powershell
git check-ignore .worktrees
```

Si no devuelve `.worktrees`, añade:

```powershell
Add-Content .gitignore "`n.worktrees/"
git add .gitignore
git commit -m "chore: ignore local worktrees"
git push origin main
```

Crea el primer worktree:

```powershell
git worktree add `
    ".worktrees/rp2-v3-panel-contracts" `
    -b "fix/rp2-v3-panel-contracts" `
    origin/main

Set-Location ".worktrees/rp2-v3-panel-contracts"
uv sync --locked
uv run pytest tests -q
```

### Regla permanente

Cada gate tendrá:

* una rama;
* un worktree;
* un PR;
* una revisión;
* un merge;
* limpieza del worktree.

Después de fusionar cada PR:

```powershell
Set-Location ../..
git switch main
git pull --ff-only origin main
git worktree remove ".worktrees/rp2-v3-panel-contracts"
git branch -d "fix/rp2-v3-panel-contracts"
```

---

# 3. PR 1 — Hacer que el pipeline falle de forma cerrada

## Problema

Actualmente hay rutas donde:

* un archivo B1 o B2 ausente puede ser omitido;
* una feature registrada pero ausente puede no entrar en el diseño;
* una ejecución llamada `B0+B1+B2` puede terminar conteniendo menos información de la declarada.

Eso debe ser imposible.

## Archivos

```text
Modify:
    src/mds650/rp2/panel.py

Modify tests:
    tests/unit/test_rp2_panel.py
    tests/contract/test_feature_registry_reaches_the_panel.py
```

## Tests que debes escribir primero

```python
def test_missing_b1_file_fails_closed() -> None:
    ...

def test_missing_b2_file_fails_closed() -> None:
    ...

def test_registered_b1_feature_missing_from_panel_fails_closed() -> None:
    ...

def test_registered_b2_feature_missing_from_panel_fails_closed() -> None:
    ...

def test_nested_information_sets_use_the_same_evaluation_rows() -> None:
    ...
```

Ejecuta cada test antes de corregir:

```powershell
uv run pytest `
    tests/unit/test_rp2_panel.py::test_missing_b1_file_fails_closed `
    -vv
```

Debe fallar por el comportamiento actual, no por errores de sintaxis.

## Corrección

En `load_merged_panel()` elimina cualquier comportamiento equivalente a:

```python
if not path.is_file():
    continue
```

Debe convertirse en:

```python
if not b1_path.is_file():
    raise FileNotFoundError(f"RP2_PANEL_INPUT_MISSING:B1:{b1_path}")

if not b2_path.is_file():
    raise FileNotFoundError(f"RP2_PANEL_INPUT_MISSING:B2:{b2_path}")
```

En `build_design()` elimina:

```python
if column not in panel.columns:
    continue
```

Antes de construir el diseño:

```python
assert_required_columns(panel, feature_map.keys())
```

Registra también:

```text
requested_information_set
resolved_feature_names
feature_count
evaluation_mask_sha256
```

en cada artifact.

## Criterio de salida

Una ejecución sólo puede llamarse `B0+B1+B2` si:

$$\text{features resueltas} = \text{features registradas}.$$

Y los tres modelos deben evaluarse sobre la misma máscara de filas para un contraste determinado.

## Commit y GitHub

```powershell
git add src/mds650/rp2/panel.py tests
git commit -m "fix: make rp2 information sets fail closed"
git push -u origin fix/rp2-v3-panel-contracts
```

Abre el PR y coloca en la descripción:

```text
Scope: panel contracts only
Sealed cohorts read: 0
Artifacts recalculated: none
Scientific claims changed: none
```

Solicita:

```text
@codex review
```

No fusiones hasta:

* `quality`: verde;
* `hermetic`: verde;
* comentarios P1/P2 resueltos;
* revisión nueva sobre el último commit.

---

# 4. PR 2 — Corregir definitivamente el EWMA de B0

## Problema

La función EWMA fue mejorada, pero el productor todavía utiliza una transformación del target RV30 como entrada del benchmark. Eso no representa un forecast causal basado en retornos observados.

## Archivos

```text
Modify:
    src/mds650/rp2/baseline.py
    scripts/rp2_block4_b0_panel.py

Tests:
    tests/unit/test_rp2_baseline.py
    tests/unit/test_rp2_block4_b0.py
```

## Tests primero

```python
def test_ewma_forecast_at_t_is_invariant_to_returns_after_t() -> None:
    ...

def test_ewma_state_is_separate_for_each_asset() -> None:
    ...

def test_block4_ewma_never_receives_rv30_target_as_input() -> None:
    ...

def test_ewma_30m_forecast_uses_only_observed_one_minute_returns() -> None:
    ...
```

El test principal debe:

1. construir retornos hasta $t$;
2. calcular el forecast;
3. alterar violentamente todos los retornos después de $t$;
4. comprobar que el forecast en $t$ no cambia.

## Implementación

Crea una función equivalente a:

```python
def causal_ewma_horizon_variance(
    returns: FloatArray,
    origins: IntArray,
    *,
    decay: float,
    horizon: int,
    initial_state: float | None,
) -> tuple[FloatArray, float]:
    ...
```

En cada origen $t$:

$$h_t = \lambda h_{t-1} + (1-\lambda)\, r_{t-1}^{2}$$

y un forecast simple de RV30 puede ser:

$$\widehat{RV30}_t = 30\, h_t.$$

La recursión debe ser:

* independiente por activo;
* cronológica;
* transportable entre sesiones;
* alimentada por retornos de un minuto;
* completamente independiente de `rv30`.

Elimina cualquier llamada equivalente a:

```python
ewma_variance(np.sqrt(target))
```

## Criterio de salida

* Future perturbation test: pasa.
* Cross-asset isolation test: pasa.
* Ningún target aparece en la construcción EWMA.
* Block 4 se reconstruye sin cambiar los artifacts congelados anteriores.

## Commit

```powershell
git add src/mds650/rp2/baseline.py `
        scripts/rp2_block4_b0_panel.py `
        tests
git commit -m "fix: build causal asset-local ewma baseline"
```

---

# 5. PR 3 — Reconstruir B1 como estado contemporáneo

Éste es el cambio con **mayor impacto esperado**.

## Problema

B1 se construyó con una ventana antigua para evitar reutilizar las mismas filas que B2. Eso convirtió B1 en un estado rezagado, no en el estado contemporáneo del mercado de opciones.

B1 y B2 pueden estar correlacionados. El contraste es condicional:

$$E[Y \mid B0, B1, B2] \quad\text{contra}\quad E[Y \mid B0, B1].$$

No necesitas separar ambas capas mediante una brecha temporal artificial.

## Archivos

```text
Create:
    docs/rp2_v3/B1_CONTEMPORANEOUS_SPEC.md
    src/mds650/rp2/b1_snapshot.py

Modify:
    scripts/rp2_block5_surface_panel.py
    src/mds650/rp2/surface.py
    src/mds650/rp2/panel.py

Tests:
    tests/unit/test_rp2_b1_snapshot.py
    tests/e2e/test_rp2_b1_contemporaneous.py
```

## Especificación congelada

```text
Forecast origin: t
Availability cutoff: t - 120 seconds
Maximum quote age: 30 minutes
Sensitivity maximum age: 60 minutes
Contract state: last available NBBO per contract
Primary source label: trade_sampled_contemporaneous_nbbo
Post-cutoff observations: forbidden
```

## Algoritmo

Para cada origen $t$:

1. calcula:

$$c_t = t - 120\,\text{s};$$

2. conserva sólo filas con:

$$\text{created\_at} \le c_t;$$

3. elimina filas anteriores a:

$$c_t - 30\,\text{m};$$

4. agrupa por contrato;
5. conserva la última observación disponible de cada contrato;
6. construye la superficie con ese snapshot.

No uses una ventana que termine 32 minutos antes del origen.

## Tests primero

```python
def test_b1_uses_a_quote_three_minutes_before_origin() -> None:
    ...

def test_b1_rejects_any_quote_after_the_cutoff() -> None:
    ...

def test_b1_keeps_only_the_latest_quote_per_contract() -> None:
    ...

def test_b1_quote_age_is_measured_against_forecast_origin() -> None:
    ...

def test_b1_at_1000_does_not_require_premarket_state() -> None:
    ...
```

## Crear B1-core

El conjunto primario debe incluir sólo features de alta cobertura:

```text
b1_iv_7d
b1_iv_30d
b1_iv_60d
b1_term_slope
b1_smile_level
b1_risk_reversal_25
b1_median_relative_spread
b1_median_quote_age_s
b1_surface_coverage
b1_iv_minus_trailing_rv_30d
```

Mantén en `B1-rich`, no en el primario:

```text
b1_implied_rate
b1_implied_dividend_yield
arbitrage diagnostics
low-coverage curvature diagnostics
```

No descartes una fila completa porque falle implied rate.

## Métricas técnicas obligatorias

Antes/después:

| Métrica | Objetivo RP2-v3 |
| --- | ---: |
| Cobertura B1-core | >90% |
| Mediana de quote age respecto del origen | <900 s |
| P95 quote age | ≤1,800 s |
| Filas descartadas por rate/dividend | 0 |
| Observaciones post-cutoff | 0 |
| Contratos duplicados por snapshot | 0 |

## Validación independiente

Usa `rp2_block5b_independent_surface.py` sobre una muestra bounded de Massive para estimar:

$$B1_{\text{trade-sampled}} - B1_{\text{independent quotes}}.$$

No uses esa pequeña muestra como prueba de forecast; úsala como auditoría de medición.

## Commit

```powershell
git add docs/rp2_v3 `
        src/mds650/rp2/b1_snapshot.py `
        src/mds650/rp2/surface.py `
        src/mds650/rp2/panel.py `
        scripts/rp2_block5_surface_panel.py `
        tests
git commit -m "feat: build contemporaneous b1 option-state snapshots"
```

---

# 6. PR 4 — Corregir relojes, 0DTE y Greeks de B2

## Principio

B2 necesita dos relojes diferentes:

### Reloj económico

```text
executed_at
```

Representa cuándo ocurrió la operación.

Debe usarse para:

* spot as-of;
* Greeks;
* interarrivals;
* intensidad;
* time-to-expiry.

### Reloj de disponibilidad

```text
created_at
```

Representa cuándo el proveedor hizo visible el evento.

Debe usarse para:

$$\text{created\_at} \le t - 120\,\text{s}.$$

## Archivos

```text
Create:
    src/mds650/rp2/option_clock.py

Modify:
    scripts/rp2_block6_flow_panel.py
    src/mds650/rp2/flow.py

Tests:
    tests/unit/test_rp2_option_clock.py
    tests/unit/test_rp2_flow.py
    tests/e2e/test_rp2_b2_point_in_time.py
```

## Tests primero

```python
def test_trade_is_unavailable_before_created_at() -> None:
    ...

def test_greeks_use_spot_at_executed_at() -> None:
    ...

def test_intensity_uses_exchange_execution_time() -> None:
    ...

def test_zero_dte_uses_fractional_time_until_expiry() -> None:
    ...

def test_provider_batching_does_not_create_economic_intensity() -> None:
    ...

def test_empty_window_is_distinct_from_provider_failure() -> None:
    ...
```

## Expiración

No utilices:

```python
max(expiry_date - session_date, 1.0)
```

Construye:

```text
expiry_timestamp_utc
```

por contrato.

Después:

$$T = \frac{\text{expiry\_timestamp\_utc} - \text{executed\_at}}{365.25 \times 24 \times 3600}.$$

Añade features explícitas:

```text
b2_5m_zero_dte_premium_share
b2_5m_zero_dte_signed_premium
b2_5m_zero_dte_trade_share
b2_5m_mean_provider_latency_s
b2_5m_late_arrival_share
```

Renombra cualquier `median_age_s` que realmente sea media, o calcula una mediana real.

## Criterio de salida

* 100% de los eventos usados cumplen PIT.
* 0DTE no se representa como un día entero.
* Intensidad económica no usa `created_at`.
* Latencia sigue disponible como feature independiente.
* Fallo del proveedor no equivale a flujo igual a cero.

---

# 7. PR 5 — Crear un registry compacto: Core versus Rich

## Problema

Un conjunto de más de cien dimensiones frente a unas pocas decenas de sesiones independientes tiene enorme varianza de estimación.

## Crear

```text
src/mds650/rp2/feature_registry.py
configs/rp2_v3_feature_sets.json
tests/contract/test_rp2_v3_feature_registry.py
```

## Estructura

```python
@dataclass(frozen=True)
class FeatureSet:
    name: str
    version: str
    features: tuple[str, ...]
    minimum_coverage: float
```

Registra:

```text
B0_CORE
B1_CORE
B2_CORE
B1_RICH
B2_RICH
```

## B2-core recomendado

Aproximadamente 10–12 mecanismos:

```text
b2_5m_trades
b2_5m_premium
b2_5m_buy_premium_share
b2_5m_delta_flow
b2_5m_vega_flow
b2_5m_vega_flow_short_dte
b2_5m_zero_dte_premium_share
b2_5m_decay_intensity_innovation
b2_5m_d_iv
b2_5m_strike_hhi
b2_5m_multileg_share
b2_5m_mean_provider_latency_s
```

## Regla

Las features core se definen por:

* mecanismo económico;
* cobertura;
* estabilidad;
* disponibilidad PIT.

No por el p-value histórico individual.

## Artifact obligatorio

```text
feature_registry_sha256
feature_names
feature_count
coverage_by_feature
missingness_by_feature
```

---

# 8. PR 6 — Imputación fold-local y máscara común

## Problema

No debes eliminar una fila porque una feature secundaria sea `NaN`, ni puedes imputar utilizando información de validación.

## Crear

```text
src/mds650/rp2/preprocessing.py
tests/unit/test_rp2_preprocessing.py
```

## Interfaz

```python
@dataclass(frozen=True)
class FittedPreprocessor:
    medians: dict[str, float]
    means: dict[str, float]
    scales: dict[str, float]
    missing_indicator_features: tuple[str, ...]
```

Funciones:

```python
def fit_preprocessor(
    frame: pl.DataFrame,
    features: Sequence[str],
    train_mask: BoolArray,
) -> FittedPreprocessor:
    ...

def transform_features(
    frame: pl.DataFrame,
    features: Sequence[str],
    fitted: FittedPreprocessor,
) -> FloatArray:
    ...
```

## Tests primero

```python
def test_imputation_uses_training_rows_only() -> None:
    ...

def test_validation_extreme_values_do_not_change_training_median() -> None:
    ...

def test_missing_indicator_preserves_missingness_information() -> None:
    ...

def test_b0_b1_b2_are_evaluated_on_the_same_common_rows() -> None:
    ...
```

## Máscara común

Para cada contraste:

$$M = \text{target válido} \cap \text{claves válidas} \cap \text{availability válida}.$$

Los modelos anidados deben usar exactamente $M$.

No permitas que B0 tenga más filas que B1 simplemente porque B1 contiene missingness imputable.

---

# 9. PR 7 — Alinear LightGBM directamente con QLIKE

## Problema

El modelo no lineal optimiza log-MSE, pero el criterio de decisión es QLIKE.

## Archivos

```text
Modify:
    src/mds650/rp2/ladder.py
    src/mds650/metrics.py

Create:
    src/mds650/rp2/qlike_objective.py

Tests:
    tests/unit/test_rp2_qlike_objective.py
    tests/unit/test_rp2_ladder.py
```

## Objetivo

Sea:

$$z = \log \widehat{\sigma}^{2}.$$

Entonces:

$$L(y, z) = y e^{-z} + z - \log y - 1.$$

Gradiente:

$$g(z) = 1 - \frac{y}{e^{z}}.$$

Hessiano:

$$h(z) = \frac{y}{e^{z}}.$$

Implementación conceptual:

```python
def qlike_gradient_hessian(
    raw_prediction: FloatArray,
    target: FloatArray,
) -> tuple[FloatArray, FloatArray]:
    variance = np.exp(np.clip(raw_prediction, -30.0, 30.0))
    safe_target = np.maximum(target, 1e-12)
    gradient = 1.0 - safe_target / variance
    hessian = safe_target / variance
    return gradient, hessian
```

## Tests

```python
def test_qlike_gradient_matches_finite_difference() -> None:
    ...

def test_qlike_hessian_is_positive() -> None:
    ...

def test_qlike_objective_is_finite_for_small_variances() -> None:
    ...

def test_lightgbm_never_tunes_on_validation_sessions() -> None:
    ...
```

## Modelos primarios

Congela únicamente:

```text
gamma_glm
ridge_log
lightgbm_qlike
```

No añadas una nueva familia hasta que estas tres estén cerradas.

---

# 10. PR 8 — Corregir toda la inferencia a nivel de sesión

## Principio

Primero agrega la diferencia de pérdida por sesión:

$$\bar d_d = \frac{1}{N_d} \sum_{i,t \in d} \left( L_{\text{base},i,t} - L_{\text{expanded},i,t} \right).$$

Después realiza inferencia sobre:

$$\{\bar d_d\}_{d=1}^{D}.$$

## Archivos

```text
Modify:
    src/mds650/rp2/inference.py
    scripts/rp2_block8_ladder.py
    scripts/rp2_block10_inference.py

Tests:
    tests/unit/test_rp2_inference.py
    tests/e2e/test_rp2_incremental_inference.py
```

## Tests primero

```python
def test_replicating_rows_inside_one_day_does_not_change_the_estimate() -> None:
    ...

def test_reordering_assets_inside_a_day_does_not_change_inference() -> None:
    ...

def test_spa_receives_one_observation_per_session() -> None:
    ...

def test_spa_comparisons_are_family_matched() -> None:
    ...

def test_block_bootstrap_resamples_complete_sessions() -> None:
    ...

def test_early_close_days_receive_the_same_day_weight() -> None:
    ...
```

## Contrastes SPA correctos

Correcto:

```text
gamma B0        vs gamma B0+B1
gamma B0+B1     vs gamma B0+B1+B2
lightgbm B0     vs lightgbm B0+B1
lightgbm B0+B1  vs lightgbm B0+B1+B2
ridge B0        vs ridge B0+B1
ridge B0+B1     vs ridge B0+B1+B2
```

Incorrecto:

```text
log-OLS B0 vs LightGBM B0+B1+B2
```

## Métodos

Usa:

* media igual por sesión;
* circular/moving block bootstrap de sesiones;
* bloque primario fijo de cinco sesiones;
* wild cluster bootstrap;
* Newey–West sobre la serie diaria;
* Clark–West sólo para modelos lineales anidados;
* equivalence testing;
* MDE registrado.

## Artifact

Cada contraste debe guardar:

```text
estimate
ci_low
ci_high
p_value
sessions
block_length
common_mask_sha256
model_family
base_information_set
expanded_information_set
mde
equivalence_bound
```

---

# 11. PR 9 — Crear un único runner reproducible

No sigas ejecutando manualmente ocho scripts con configuraciones dispersas.

## Crear

```text
scripts/run_rp2_v3_pipeline.py
src/mds650/rp2/run_manifest.py
tests/e2e/test_run_rp2_v3_pipeline.py
```

## CLI propuesta

```powershell
uv run python scripts/run_rp2_v3_pipeline.py `
    --data-root D:\MDS650 `
    --output-root artifacts\rp2_v3 `
    --run-id rp2-v3-20260820-001 `
    --roles D V `
    --forbid-sealed-cohorts
```

## Orden interno

```text
1. Validate input manifests
2. Build Block 3 targets
3. Build causal B0
4. Build contemporaneous B1
5. Build exact-clock B2
6. Validate feature registry
7. Construct common masks
8. Fit model ladder
9. Run DML diagnostics
10. Run incremental inference
11. Generate scorecard
12. Generate provenance
13. Verify artifact hashes
```

## Comportamiento

El runner debe abortar si:

* falta un input;
* cambia un schema;
* aparece un duplicado;
* una feature core no existe;
* una observación viola PIT;
* intenta acceder a C/Phase 8/Phase 9;
* un artifact ya existe con otro hash bajo el mismo `run_id`.

## Reproducibilidad

Dos ejecuciones con:

* mismos inputs;
* mismo commit;
* misma configuración;
* mismas seeds;

deben producir los mismos hashes científicos. El timestamp de ejecución no debe entrar en el hash del contenido científico.

---

# 12. Construir el scorecard antes/después

Cada rebuild debe producir:

```text
artifacts/rp2_v3/<run_id>/scorecard.json
artifacts/rp2_v3/<run_id>/scorecard.md
```

## Métricas mínimas

### Datos

```text
B0 rows
B1 rows
B2 rows
Common evaluation rows
Sessions D/V
Assets
Duplicate keys
Provider failures
```

### B1

```text
Core coverage
Median quote age
P95 quote age
Surface contracts per origin
Surface expiry coverage
Missing-rate share
```

### B2

```text
PIT violation count
0DTE count
Mean provider latency
P95 provider latency
Multileg share
Empty-window share
Provider-failure share
```

### Forecast

```text
QLIKE B0
QLIKE B0+B1
QLIKE B0+B1+B2
Delta B1
Delta B2|B1
Delta total
CI by session
MDE
Calibration slope/intercept
```

### Ingeniería

```text
Runtime
Peak memory
Input manifest SHA
Feature registry SHA
Model config SHA
Code commit
Artifact SHA
```

## Mejora técnica visible esperada

| Métrica | Estado anterior | Objetivo |
| --- | ---: | ---: |
| Frescura típica B1 | decenas de minutos | <15 minutos |
| Cobertura B1-core | cercana a 60% en features limitantes | >90% |
| 0DTE exacto | no | sí |
| SPA family-matched | no | sí |
| Inferencia por sesión | parcial | completa |
| Faltantes silenciosos | posibles | imposibles |
| Results sin `run_id` | existentes | 0 en RP2-v3 |
| Provenance de inputs reales | incompleta | 100% |

La mejora predictiva se reporta, no se impone.

---

# 13. Preparar Supabase localmente antes de tocar producción

Supabase recomienda desarrollar mediante migrations versionadas, probar localmente y utilizar `db push --dry-run` antes de aplicar las migrations remotas. El CLI puede ejecutarse globalmente o mediante `npx`; si se usa npm requiere Node.js 20 o posterior. ([Supabase][1])

## Inicialización

Desde el repositorio:

```powershell
supabase --version
supabase login
supabase link --project-ref eqpyjikcewqaegnbaemf
supabase migration list
```

Si el directorio Supabase no estuviera inicializado:

```powershell
supabase init
```

Obtén una línea base del schema remoto:

```powershell
supabase db pull
```

Arranca la instancia local:

```powershell
supabase start
supabase db reset
```

`db reset --linked` es destructivo para la base remota vinculada y no debe ejecutarse contra producción. ([Supabase][2])

---

# 14. Crear una migration Supabase versionada

```powershell
supabase migration new rp2_v3_versioned_results
```

La migration debe ampliar `ingestion_runs`:

```sql
alter table public.ingestion_runs
    add column if not exists spec_version text,
    add column if not exists branch_name text,
    add column if not exists feature_registry_sha256 text,
    add column if not exists model_config_sha256 text,
    add column if not exists inference_config_sha256 text,
    add column if not exists common_mask_sha256 text;
```

Crea resultados versionados:

```sql
create table if not exists public.rp2_block_results (
    block_id text not null,
    run_id text not null
        references public.ingestion_runs(run_id)
        on delete restrict,
    status text not null,
    verdict text not null,
    document text not null,
    artifact_sha256 text not null
        check (artifact_sha256 ~ '^[0-9a-f]{64}$'),
    supersedes_run_id text
        references public.ingestion_runs(run_id)
        on delete restrict,
    is_current boolean not null default false,
    created_at timestamptz not null default now(),
    primary key (block_id, run_id)
);

create unique index if not exists
    rp2_block_results_one_current_per_block
on public.rp2_block_results (block_id)
where is_current;
```

Crea la misma estructura conceptual para:

```text
rp2_extension_results
rp2_power_results
rp2_contrast_results
```

## No elimines todavía las tablas actuales

Mantén:

```text
rp2_blocks
rp2_extensions
rp2_power
```

como tablas legacy hasta que:

* todos los resultados nuevos tengan `run_id`;
* las views nuevas estén validadas;
* el reporte final use exclusivamente las tablas versionadas.

---

# 15. Crear una publicación transaccional

Crea:

```text
scripts/publish_rp2_v3_supabase.py
tests/unit/test_publish_rp2_v3_supabase.py
```

## Flujo

Dentro de una transacción:

1. insertar `ingestion_runs` como `RUNNING`;
2. insertar `ingestion_inputs`;
3. validar hashes;
4. insertar `rp2_block_results`;
5. marcar el resultado anterior `is_current=false`;
6. marcar el nuevo `is_current=true`;
7. actualizar `rows_published`;
8. marcar run como `COMPLETE`.

Si algo falla:

* rollback;
* ningún resultado parcial queda publicado;
* registrar el error en una operación separada como `FAILED`.

## Regla

No vuelvas a actualizar resultados manualmente mediante SQL ad hoc.

Toda publicación debe pasar por:

```text
run_id
code_commit
input manifest
feature registry
model config
inference config
artifact hash
```

---

# 16. Views públicas y seguridad

Las tablas origin-level licenciadas deben permanecer privadas.

Publica sólo agregados:

```sql
create or replace view api.current_rp2_block_results as
select
    block_id,
    run_id,
    status,
    verdict,
    artifact_sha256,
    created_at
from public.rp2_block_results
where is_current;
```

Para contrastes:

```sql
create or replace view api.current_rp2_contrasts as
select
    run_id,
    role,
    model_family,
    base_information_set,
    expanded_information_set,
    estimate,
    ci_low,
    ci_high,
    p_value,
    sessions,
    mde
from public.rp2_contrast_results
where is_current;
```

No expongas:

* forecasts por origen;
* raw option trades;
* raw quotes;
* payloads comerciales;
* service-role keys;
* paths locales sensibles.

---

# 17. Validar la migration antes de aplicarla

Localmente:

```powershell
supabase db reset
```

Ejecuta queries de aceptación:

```sql
select count(*)
from public.rp2_block_results
where run_id is null;
```

Debe ser:

```text
0
```

Comprueba unicidad:

```sql
select block_id, count(*)
from public.rp2_block_results
where is_current
group by block_id
having count(*) > 1;
```

Debe devolver cero filas.

Comprueba lineage:

```sql
select r.run_id
from public.rp2_block_results r
left join public.ingestion_runs i
    on i.run_id = r.run_id
where i.run_id is null;
```

Debe devolver cero filas.

Después:

```powershell
supabase db push --dry-run
```

Revisa manualmente el SQL.

Sólo entonces:

```powershell
supabase db push
```

`db push` aplica únicamente migrations pendientes y registra su aplicación en el historial remoto. ([Supabase][2])

---

# 18. Publicar el rebuild RP2-v3

Crea un `run_id` único:

```powershell
$RunId = "rp2-v3-" + (Get-Date -Format "yyyyMMdd-HHmmss")
```

Ejecuta:

```powershell
uv run python scripts/run_rp2_v3_pipeline.py `
    --data-root D:\MDS650 `
    --output-root artifacts\rp2_v3 `
    --run-id $RunId `
    --roles D V `
    --forbid-sealed-cohorts
```

Verifica:

```powershell
uv run python scripts/run_local_evidence_gates.py

uv run python scripts/publish_rp2_v3_supabase.py `
    --run-root "artifacts\rp2_v3\$RunId" `
    --dry-run
```

Revisa el diff de publicación.

Después:

```powershell
uv run python scripts/publish_rp2_v3_supabase.py `
    --run-root "artifacts\rp2_v3\$RunId"
```

Finalmente consulta:

```sql
select *
from api.current_rp2_contrasts
order by role, model_family, base_information_set;
```

---

# 19. PR final de artifacts y documentación

No sobrescribas los artifacts anteriores.

Usa:

```text
artifacts/rp2_v3/<run_id>/
```

Actualiza:

```text
STATUS.md
data/CANONICAL_STATE.json
docs/methodology_decisions.md
docs/rp2_v3/IMPLEMENTATION_STATUS.md
docs/rp2_v3/SUPERSEDED_RESULTS.md
```

Clasifica resultados anteriores afectados como:

```text
SUPERSEDED_BY_RP2_V3
```

No como eliminados.

## PR description

Debe contener una tabla:

| Métrica | RP2-v2 | RP2-v3 | Cambio |
| --- | ---: | ---: | ---: |
| B1 coverage | ... | ... | ... |
| B1 median age | ... | ... | ... |
| B2 PIT violations | ... | ... | ... |
| ΔB1 D | ... | ... | ... |
| ΔB1 V | ... | ... | ... |
| ΔB2\|B1 D | ... | ... | ... |
| ΔB2\|B1 V | ... | ... | ... |
| Sessions OOS | ... | ... | ... |

Añade:

```text
Sealed cohort reads: 0
Confirmation claims: none
Economic claims: none
Supabase migration: applied
Supabase run_id: ...
```

Solicita dos revisiones Codex:

```text
@codex review
```

Después de corregir comentarios:

```text
@codex review
```

sobre el último commit.

---

# 20. Endurecer GitHub CI

Mantén los checks actuales:

```text
quality
hermetic
```

Añade un tercer job:

```text
scientific-contracts
```

Debe ejecutar:

```yaml
- name: RP2 scientific contracts
  run: >
    uv run pytest
    tests/contract/test_rp2_v3_feature_registry.py
    tests/e2e/test_rp2_b1_contemporaneous.py
    tests/e2e/test_rp2_b2_point_in_time.py
    tests/e2e/test_rp2_incremental_inference.py
    tests/e2e/test_run_rp2_v3_pipeline.py
    -q
```

Añade también `.github/pull_request_template.md`:

```markdown
## Scientific integrity

- [ ] No sealed cohort was read
- [ ] Tests were written before production changes
- [ ] All information sets fail closed
- [ ] Same evaluation mask used for nested comparisons
- [ ] Before/after scorecard attached
- [ ] No frozen artifact overwritten
- [ ] Superseded artifacts explicitly recorded

## Verification

- [ ] Ruff
- [ ] mypy
- [ ] hermetic pytest
- [ ] local evidence gates
- [ ] Codex review on latest commit
```

Una vez el job haya pasado correctamente en un PR, agrégalo a la protección de `main`.

---

# 21. Gate científico después del rebuild

Sólo después de todas las correcciones anteriores analiza:

$$\Delta_{B1}$$

y:

$$\Delta_{B2\mid B1}.$$

## Resultado A

$$\Delta_{B1} > 0 \quad\text{y}\quad \Delta_{B2\mid B1} > 0$$

en D y V.

Interpretación:

> La corrección de contemporaneidad, cobertura y relojes recuperó una estructura predictiva coherente.

Entonces se congela una nueva especificación prospectiva.

## Resultado B

$$\Delta_{B1} > 0, \qquad \Delta_{B2\mid B1} \approx 0.$$

Interpretación:

> El estado de opciones ayuda, pero el flujo no añade información explotable sobre B1.

## Resultado C

$$\Delta_{B1} < 0$$

incluso con B1 contemporáneo y cobertura alta.

Interpretación:

> B1 no aporta forecastability contemporánea para RV30 bajo esta representación.

## Resultado D

Efectos positivos, pero:

$$CI_{95\%} \ni 0.$$

Interpretación:

> El efecto estimado puede ser positivo, pero la muestra es insuficiente.

No añadas nuevos modelos para "rescatarlo". Calcula potencia por sesiones.

---

# 22. Congelar la confirmación prospectiva

Cuando RP2-v3 esté terminado:

1. congela feature registry;
2. congela modelos;
3. congela imputation;
4. congela cutoff;
5. congela universo;
6. congela inferencia;
7. congela MDE;
8. genera hashes;
9. inicia una cohorte nueva.

No reutilices D o V como confirmación.

No abras el holdout hasta:

* tamaño preregistrado alcanzado;
* inputs completos;
* provider health validado;
* autorización de lectura;
* una sola ejecución.

---

# 23. No tocar economía todavía

No avances al nuevo backtest hasta que:

$$\Delta_{B2\mid B1} > 0$$

sea estable prospectivamente.

Después, la ejecución debe cumplir:

$$t_{\text{entry}} > t_{\text{signal}} + \text{latencia}.$$

Debe:

* entrar en la primera quote posterior a la señal;
* salir en la primera quote posterior al horizonte;
* sincronizar opción y spot;
* agregar P&L por timestamp;
* aplicar constraints por portafolio simultáneo;
* incluir no-trade band;
* registrar missed fills;
* aplicar spreads y slippage;
* comparar B2 contra B1, no sólo P&L total.

---

# 24. Orden exacto de PRs

No alteres esta secuencia:

1. `docs/rp2-v3-contract`
2. `fix/rp2-v3-panel-contracts`
3. `fix/rp2-v3-causal-b0`
4. `feat/rp2-v3-contemporaneous-b1`
5. `fix/rp2-v3-exact-clock-b2`
6. `feat/rp2-v3-core-feature-registry`
7. `feat/rp2-v3-fold-local-preprocessing`
8. `feat/rp2-v3-qlike-models`
9. `fix/rp2-v3-session-inference`
10. `feat/rp2-v3-pipeline-runner`
11. `db/rp2-v3-versioned-results`
12. `results/rp2-v3-rebuild`

Cada PR debe quedar fusionado antes de crear el siguiente desde `main`.

---

# Prioridad práctica

Las cuatro tareas con mayor retorno esperado son:

1. **B1 contemporáneo.**
2. **B1-core con cobertura superior al 90%.**
3. **B2 con `executed_at`, `created_at` y 0DTE correctamente separados.**
4. **Inferencia igual por sesión y family-matched.**

No dediques más tiempo por ahora a:

* transformers;
* LSTM;
* DeepSets adicionales;
* nuevos indicadores;
* nuevos horizons;
* nuevas estrategias de opciones;
* optimización retrospectiva de thresholds.

Primero debemos conseguir que:

$$B0,\ B1,\ B2$$

representen exactamente la información que dicen representar. Sólo después tiene sentido exigir que:

$$L(B1) < L(B0)$$

y:

$$L(B2) < L(B1).$$

Empieza por el **Paso 0** y no abras el PR de B1 hasta haber fusionado correctamente los PR de contratos del panel y B0 causal.

[1]: https://supabase.com/docs/guides/local-development/cli/getting-started?utm_source=chatgpt.com "Supabase CLI | Supabase Docs"
[2]: https://supabase.com/docs/guides/local-development/cli-workflows?utm_source=chatgpt.com "Local development workflow | Supabase Docs"
