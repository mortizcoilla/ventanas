# Auditoría técnica — Ventanas de Mantenimiento (SEN chileno)

Fecha: 2026-10-02 · Alcance: `src/`, `dashboard/`, `data/`, `notebook/`, `informe/`.
Perspectiva: ingeniería eléctrica + mantenimiento predictivo (ML) + mercado/registro eléctrico chileno.

Leyenda: 🔴 error funcional · 🟠 defecto metodológico / de modelado · 🟡 calidad de código · 🔵 menor/estético.

---

## 1. `src/pipeline.py`

| # | Sev | Hallazgo |
|---|-----|----------|
| P1 | 🔴 | `exportar_para_dashboard()` escribe `costos_ventana.json` **vacío siempre**: el dict-comp itera `(plan_baseline and {} or {}).items()`, expresión que evalúa a `{}` en todos los casos. El archivo queda en 0 bytes. |
| P2 | 🔴 | `_cache_costos_rapido()` usa `hash(elem)` (línea ~234) para el "ruido determinístico". `hash()` de strings en CPython se saltea por `PYTHONHASHSEED` → **resultados no reproducibles entre ejecuciones** pese a `SEED`. |
| P3 | 🟠 | Inconsistencia de escalas entre modelos: el objetivo MILP es **incremental** (USD 5.208) pero el costo de NSGA-II/Pareto es **total** (`base + incremental`, ≈ USD 114k). El dashboard y el README mezclan ambas escalas sin etiquetar. |
| P4 | 🟠 | El cache de costos (proxy sintético con factor estacional) **no es consistente** con la re-simulación DC-PF del plan elegido: el Pareto mínimo dice ≈114k totales, la simulación directa del plan da ≈81k. El MILP optimiza el proxy, no el costo DC-PF real. Aceptable como demo si se etiqueta, pero hoy no se etiqueta. |
| P5 | 🟠 | SAIDI como 3er objetivo de NSGA-II es casi degenerado: los valores del frente van de 0.0019 a 0.0020 (varían en la 4ª cifra). El término `horas_fuera_promedio` depende casi solo de `lambda` (constante por línea), no del plan. |
| P6 | 🟡 | `evaluar()` trunca `plan_s[k] = plan_s[k][:2]` cuando una semana excede el máximo de concurrentes → **líneas que pierden silenciosamente su ventana** (plan incompleto), en vez de penalizar o reparar. |
| P7 | 🟡 | Código muerto: `cargabilidades_base` (placeholder 0.7 nunca usado), import de `_calcular_costos_por_ventana` sin uso, loop SAA duplicado que reimplementa `simular_escenarios()`. |
| P8 | 🟡 | `exportar_para_dashboard()` relee `demanda_horaria.csv` y `generacion_horaria.csv` desde disco en vez de recibir los DataFrames ya cargados. |
| P9 | 🔵 | Typo en `resumen.json`: "DC Power Flow con despacho economico + LM fuerze" (→ "congestión / precios marginales locales"). |

## 2. `src/optimizacion.py`

| # | Sev | Hallazgo |
|---|-----|----------|
| O1 | 🔴 | `robustez_bertsimas_sim()` es un **stub que siempre devuelve `robusto=True`**: calcula `slack = max(0, K - activos)` y luego `min(slack) >= 0`, tautología (el max ya clampea a 0). La afirmación del README/informe "tolera 2 extensiones (Γ=2)" **no está siendo verificada por ningún código**. |
| O2 | 🔴 | `_non_dominated_sort()` está roto y muerto: contiene `for q in set(p)` sobre un `Individuo` no iterable → `TypeError` si alguien lo llama. NSGA-II reimplementa el ordenamiento inline. |
| O3 | 🟠 | Proxy de congestión en `_resolver_dc_pf`: `(carg-0.90)·MVA·CMg` sin multiplicador de horas (cada semana se evalúa en 4 horas representativas, no 168). Las magnitudes "USD" están sub-estimadas en factor ~42. Además el `CMg marginal` se aproxima como el **máximo** CMg despachado, no el dual de la restricción. Etiquetar como índice, no como USD reales. |
| O4 | 🟠 | Generador virtual en slack con capacidad `2×demanda` y costo 200 USD/MWh puede **enmascarar infactibilidad N-1** (siempre despacha antes que violar límites térmicos). Para un estudio de ventanas de mantenimiento esto merege al menos un warning cuando el virtual supera un umbral. |
| O5 | 🟡 | `import json` ubicado **después** de la clase que lo usa (línea 57); funciona solo porque se importa a nivel módulo antes de la primera llamada. Frágil. |
| O6 | 🟡 | `_crossover()`: rama muerta `hijo = ... if False else padre.orden.copy()` + doble muestreo de cortes `i, j`. |
| O7 | 🟡 | Link de duración MILP `x[i, max(1, w-k)]` clampa semanas tempranas hacia `x[i,1]`, sobre-contando en `w ≤ d`. Para `d=1` no afecta; para `d>1` incorrecto. |
| O8 | 🟡 | Variables sin uso: `horas_facturado`, `rng` en `resolver_milp_mantenimiento`. `_semana_a_label()` definido y nunca usado. |
| O9 | 🔵 | `calcular_saidi_zonal()`: `max(plan.keys())` lanza `ValueError` con plan vacío; unidades del "SAIDI proxy" = semanas/MW (no horas/cliente como dice el docstring). |

## 3. `src/generar_datos.py`

| # | Sev | Hallazgo |
|---|-----|----------|
| G1 | 🟠 | `historico_forzado.csv` genera ~7 eventos en 5 años (λ≈0.0019/sem/línea). El Random Forest entrena con **17 filas y ~2 líneas con target≠0**: el modelo no separa señal de ruido y las importancias son espurias. Es la limitación #1 del "predictivo" del proyecto. |
| G2 | 🟡 | `S002 (Polpaico)` declarada a `kv=460` en un network donde todas las líneas son 220 kV y el README dice "17 líneas 220 kV". |
| G3 | 🟡 | Las coordenadas geográficas de las barras están **hardcodeadas en el dashboard** (`dashboard.js`), no en los datos. Reducen portabilidad a datos reales del CEN. |
| G4 | 🔵 | `capa_uso` mapeada desde edad con umbrales arbitrarios (90/18/9/3) sin unidad documentada. |

## 4. Modelo ML (en `optimizacion.py` + `pipeline.py`)

| # | Sev | Hallazgo |
|---|-----|----------|
| M1 | 🟠 | Sin split train/test ni validación cruzada: el dashboard muestra predicciones **in-sample** sin decirlo. Con n=17 el R² in-sample es trivialmente alto. |
| M2 | 🟠 | `construir_features()` calcula `tasa_forz_anio` y la mergea al DataFrame pero **no entra al modelo** (las `cols` no la incluyen): la feature más informada queda fuera. `uso_intensivo = MVA/(kV·1.4)` es ad-hoc y correlaciona con capacidad. |
| M3 | 🟡 | El objetivo `lambda_sem = n_forzados/(5·52)` por línea colapsa a casi-cero; Poisson con exposure (offset log-km o trenes de semana-línea) sería el enfoque correcto para tasas de falla. |

## 5. `dashboard/` (D3.js)

| # | Sev | Hallazgo |
|---|-----|----------|
| D1 | 🟠 | Pareto: escala de color `interpolateRdYlGn` mapea SAIDI bajo (bueno) a **rojo** y SAIDI alto (malo) a verde — semántica invertida. |
| D2 | 🟠 | Tab "Costos semanales" titulada "costo incremental del plan óptimo" pero grafica congestión **total** (incluye base ~USD 6.7k/semana sin mantenimiento). |
| D3 | 🟡 | Eje del Gantt muestra "S0..S12" (13 ticks) para 12 semanas; el dominio [0,12] con `ticks(12)` genera el tick 0. |
| D4 | 🟡 | `costos_ventana.json` se consume en ningún lado (y está vacío por P1). El hero muestra "Robustez: OK" siempre cierto por O1 — indicador sin contenido informativo. |
| D5 | 🟡 | Tooltips posicionados con `ev.pageX/pageY` se salen de la ventana en bordes; sin `pointer-events` guard ya lo tiene. Sin estados de carga ni manejo de datos vacíos por tab (parcial). |
| D6 | 🔵 | `fmt()` casi sin uso; leyenda de topología con guion bajo "Linea en plan" sin marcar de qué depende el dash. |

## 6. Higiene del repositorio

- 14 scripts de depuración (`src/_debug1..9.py`, `_inspect1..3.py`, `_fix.py`, `_check_nb.py`, ~610 líneas) mezclados con el código fuente.
- `__pycache__` versionado en el árbol.
- Notebook generado (`563 líneas`) ejecutable — OK.

---

## Correcciones aplicadas (resumen)

1. **P1**: `costos_ventana.json` ahora exporta el cache real `{clave: costo}` (tuplas serializadas `"L001,5"`), consumido por el nuevo dashboard.
2. **P2**: ruido determinístico vía `zlib.crc32(elem.encode())` (estable entre procesos). Reproducibilidad total con `SEED`.
3. **P3/P4**: el Pareto ahora reporta costo **incremental** (total − base); el dashboard etiqueta explícitamente "índice de congestión (proxy, 4 h representativas/sem)" y muestra base vs incremental.
4. **O1**: `robustez_bertsimas_sim()` reescrito: para cada semana `w`, verifica `activos[w] + extensiones_entrantes(w) ≤ K` en el peor caso Γ; reporta el mayor Γ tolerado y la semana crítica.
5. **O2/O6/O7/O8**: `_non_dominated_sort` eliminado, `_crossover` limpiado (OX puro), link MILP con `w-k ≥ 1`, variables muertas fuera.
6. **O5**: `import json` al tope del módulo.
7. **P5**: el objetivo SAIDI de NSGA-II ahora pondera por semana (factor estacional de demanda) y por exposición de la línea (λ·semanas desde su ventana) — aún proxy, pero varía con el plan.
8. **P6**: `orden_a_plan()` repara el truncamiento redistribuyendo excedentes a semanas con cupo (ya no hay líneas sin ventana).
9. **P7/P8**: código muerto eliminado; `exportar_para_dashboard()` recibe los DataFrames, no relee CSVs.
10. **P9/M1**: typo corregido; se exporta R² in-sample explícito y etiqueta "in-sample" en el dashboard; `tasa_forz_anio` (M2) se mantiene fuera del feature set a propósito (target leakage) y se documenta.
11. **G2/G3**: `kv` de S002 → 220; coordenadas `lat/lon` añadidas a `BARRAS` y exportadas en `red.json` (el dashboard ya no las hardcodea).
12. **D1..D6 + rediseño completo**: dashboard reconstruido como one-page editorial interactivo (D3 v7): topología geográfica con hover/select, Gantt ligado a costos, Pareto con selección de plan y mini-calendario, histograma de riesgo con α deslizable (VaR/CVaR recalculados en vivo), ML con obs-vs-pred, SAIDI zonal. Ver `dashboard/`.
13. Scripts `_debug*/_inspect*/_fix/_check_nb` eliminados; `__pycache__` limpiado.

## Riesgos residuales aceptados (documentados, no corregidos)

- DC-PF sin pérdidas ni AC: válido como proxy en 220 kV; el informe ya lo declara.
- Congestión en unidades proxy (4 h/sem): magnitudes indicativas, no facturables.
- ML con n=17 sintético: el pipeline es correcto, los datos no alcanzan para validar señal predictiva. Con datos reales del CEN (Open Data) el mismo código entrena serio.
- Bertsimas-Sim solo protege restricciones de simultaneidad (K, cuadrillas), no re-evalúa DC-PF del plan extendido.
