# Ventanas de mantenimiento que le cuestan menos al sistema

Optimizador de programación de mantenimientos de transmisión/subestación coordinada con el CEN, con pronósticos ML de falla como insumo.

Caso de estudio: reducción representativa del SEN central chileno (Quillota – Temuco), 15 subestaciones, 17 líneas 220 kV, 12 semanas de horizonte operativo.

## Qué hay

- **`data/`** Red reducida y series operativas sintéticas calibradas al SEN central. Sustituible directamente por Open Data CEN.
- **`src/`** Módulo `optimizacion.py` con DC power flow, MILP (PuLP/CBC), Bertsimas-Sim, SAA, NSGA-II propio, Random Forest de falla, SAIDI zonal. `pipeline.py` orquesta todos los modelos y exporta JSON para el dashboard. `generar_datos.py` crea los datos sintéticos (incluye coordenadas geográficas de las SE).
- **`notebook/`** Jupyter ejecutable con narrativa matemática y plots (`src/build_notebook.py` lo construye).
- **`dashboard/`** Dashboard interactivo D3.js one-page estilo guía editorial (papel técnico, retícula milimétrica): topología geográfica con selección de elementos, Gantt vinculado a costos semanales, matriz de costo por ventana, frente de Pareto seleccionable, modelo ML (importancias + observado vs predicho), riesgo con VaR/CVaR recalculados en vivo (α deslizable) y contrato de robustez Γ interactivo, SAIDI zonal.
- **`informe/`** Informe tipo tesis en Markdown con marco regulatorio, formulación, datos, resultados, conclusiones y referencias.
- **`AUDITORIA.md`** Auditoría técnica del proyecto: errores encontrados y corregidos, limitaciones aceptadas.

## Qué no hay

- Datos reales del CEN (usar `data/red.json`, `historico_*.csv`, `demanda_horaria.csv`, `generacion_horaria.csv` desde https://www.coordinador.cl/open-data).
- AC power flow (solo DC PF; válido para 220+ kV con buen factor de potencia).
- Coordinación distribuida entre múltiples agentes (futuro; ADMM).
- Aprendizaje reforzado para online scheduling (futuro).
- Red de distribución (futuro; multas SAIDI/SAIFI Decreto 4/2018).

## Cómo ejecutar

```bash
# 1. Generar datos sintéticos (determinista por semilla)
python src/generar_datos.py

# 2. Pipeline completo (~30 segundos)
python src/pipeline.py

# 3. Construir el notebook Jupyter
python src/build_notebook.py

# 4. Servir el dashboard (requiere HTTP, no file://)
cd dashboard
python -m http.server 8766
# Abrir http://localhost:8766
```

## Despliegue en Vercel

El dashboard es 100% estático y está listo para desplegarse sin cambios:

1. Importe el repositorio en [vercel.com/new](https://vercel.com/new) (framework: **Other**, sin configuración adicional — el `vercel.json` raíz ya apunta el output a `dashboard/`).
2. O desde CLI: `vercel --prod` en la raíz del repo.

No hay build step: los JSON de `dashboard/data/` se sirven tal cual, con cabeceras de caché definidas en `vercel.json`. Para actualizar el dashboard tras re-correr el pipeline, re-ejecute `python src/pipeline.py` y haga push.

## Resultados principales (caso de estudio, tras auditoría v2)

| Métrica | Valor |
|---|---|
| Líneas en plan | 8 (top por historial de mantenimiento) |
| Costo óptimo MILP (incremental) | USD 3.444 (proxy DC-PF) |
| VaR(95%) horas forzadas | 16,0 h |
| CVaR(95%) horas forzadas | 16,9 h |
| Robustez Bertsimas-Sim (Γ=2) | **Vulnerable** — Γmáx = 0, semana crítica S11 |
| Frente Pareto NSGA-II | 15 puntos no dominados |
| R² ML (in-sample, n=17) | 0,80 |

Nota: el chequeo de robustez es ahora un test real (antes siempre devolvía "OK").
El plan MILP llena las semanas 10–11 (2 líneas simultáneas) y por construcción
no tolera extensiones: el dashboard permite explorar el compromiso con el
slider Γ. Hallazgo dominante del DC-PF: L014 (Itahue–Pehuenche) es la única
línea cuyo retiro congestiona el sistema (~USD 17,5k en semanas de punta); el
optimizador la programa en el valle de demanda (S8).

## Stack

- `pandas`, `scipy`, `scikit-learn` (modelos base)
- `pulp` (MILP - CBC solver)
- `matplotlib` (plots en el notebook)
- `d3.js v7` (dashboard vía CDN)
- `nbformat` (construcción del notebook)

## Marco regulatorio

- Ley 20.936 (2016): coordinación del SEN a través del CEN.
- Decreto 51/2021: reglamento de coordinación y mantenimiento.
- LM NTSyCS Distribución (Decreto 4/2018): calidad de servicio en distribución.

## Publicación objetivo

IEEE Trans. Power Systems o Applied Energy (Q1). El enfoque de combinar pronóstico ML + optimización robusta bajo marco regulatorio chileno es diferencial y publicable.

## Autor

Miguel Ortiz Coilla. 2026.
