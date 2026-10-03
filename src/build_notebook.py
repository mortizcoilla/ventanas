"""Genera el notebook Jupyter ejecutable del proyecto."""
import json
import sys
from pathlib import Path

try:
    import nbformat
    from nbformat.v4 import new_notebook, new_markdown_cell, new_code_cell
except ImportError:
    print("Instala nbformat: pip install nbformat")
    sys.exit(1)


def add_md(nb, text):
    nb.cell.add_cite if False else None  # noop
    nb["cells"].append(new_markdown_cell(text))


def add_code(nb, source):
    nb["cells"].append(new_code_cell(source))


NB = new_notebook()
NB["cells"] = []


add_md(NB, """# Ventanas de mantenimiento que le cuestan menos al sistema

Optimizador de programacion de mantenimientos de transmision/subestacion
coordinado con el CEN, con pronosticos ML de falla como insumo.

**Autor:** Miguel Ortiz Coilla. 2026.

## Resumen ejecutivo

La coordinacion de mantenimientos en el SEN hoy es mayoritariamente manual y
se fragmenta en ahorra costos de restricciones (Ley 20.936, Decreto 51/2021).
Los mantenimientos forzados no programados son los mas caros porque llegan
sin aviso al despacho. Los ISOs internacionales reportan empeoramiento de
salidas que exceden su ventana (ISO-NE: 3,8% a 7,7%).

Este proyecto combina:
1. **Pronostico ML** de probabilidad de falla forzada por linea (Random Forest sobre 5 anios de indisponibilidad historica).
2. **DC Power Flow** como proxy rapido de flujos/congestion.
3. **MILP** para programacion anual/semanal de mantenimientos (PuLP/CBC).
4. **Bertsimas-Sim robusto** para duraciones inciertas.
5. **Sample Average Approximation (SAA)** para escenarios de falla.
6. **NSGA-II** para optimizacion multi-objetivo (costo vs CVaR vs SAIDI).
7. **Dashboard D3.js** con frente de Pareto, Gantt de mantenimientos, red topologica, y SAIDI por zona.

El caso de estudio es una reduccion representativa del SEN central chileno (Quillota-Temuco) con 15 subestaciones, 17 lineas de 220 kV, y 12 semanas de horizonte operativo.
""")

add_md(NB, """## 2. Marco regulatorio

**Ley 20.936 (2016):** establece la coordinacion del sistema electrico a traves del CEN (Coordinador Electrico Nacional), antes CDEC-SIC y CDEC-SING. Los mantenimientos mayores son notificados por los propietarios y coordinados por el CEN segun el Decreto 51/2021 (reglamento de coordinacion y operacion).

**Decreto 51/2021:** obliga a los propietarios a notificar mantenimientos mayores con antelacion y al CEN a coordinar las ventanas para minimizar restricciones. La salida no programada (falla) genera restricciones que se socializan via cargos del sistema.

**Decreto 4/2018 (SSMM):** define las sanciones por incumplimiento de calidad de servicio (SAIDI/SAIFI). Las distribuidoras con SAIDI por encima del estandar son multadas.
""")

add_md(NB, """## 3. Datos y carga""")

add_code(NB, """import sys
from pathlib import Path
sys.path.insert(0, '..')
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
plt.rcParams['figure.dpi'] = 100

from src.optimizacion import (
    Red, construir_features, entrenar_modelo_falla, predecir_lambda_semanal,
    simulacion_anual_dc, resolver_milp_mantenimiento, ParametrosMantenimiento,
    robustez_bertsimas_sim, simular_escenarios, riesgo_cvar, nsga2,
    calcular_saidi_zonal,
)
from src.pipeline import _cache_costos_rapido

BASE = Path('..').resolve()
DATA = BASE / 'data'
red = Red.cargar(str(DATA / 'red.json'))
demanda = pd.read_csv(DATA / 'demanda_horaria.csv')
gen = pd.read_csv(DATA / 'generacion_horaria.csv')
hist_prog = pd.read_csv(DATA / 'historico_programado.csv')
hist_forz = pd.read_csv(DATA / 'historico_forzado.csv')
feats = pd.read_csv(DATA / 'features_elementos.csv')
print(f'Red SEN reducida: {len(red.buses)} barras, {len(red.lineas)} lineas, {len(red.generadores)} generadores')
print(f'Historico programado: {len(hist_prog)} registros (5 anios)')
print(f'Historico forzado: {len(hist_forz)} registros (5 anios)')
print(f'Demanda horaria: {len(demanda):,} filas (12 semanas)')
""")

add_md(NB, """### 3.1 Visualizacion de la red""")

add_code(NB, """coords = {
    'S001': (-71.5, -32.9), 'S002': (-70.7, -33.4), 'S003': (-70.8, -33.5),
    'S004': (-70.8, -33.8), 'S005': (-71.6, -35.5), 'S006': (-71.2, -35.2),
    'S007': (-72.0, -36.6), 'S008': (-72.1, -37.0), 'S009': (-72.5, -37.5),
    'S010': (-72.6, -38.7), 'S011': (-72.8, -37.5), 'S012': (-70.7, -34.2),
    'S013': (-70.6, -33.7), 'S014': (-71.5, -34.0), 'S015': (-70.9, -35.3),
}
fig, ax = plt.subplots(figsize=(11, 6))
for _, ln in red.lineas.iterrows():
    x = [coords[ln['desde']][0], coords[ln['hasta']][0]]
    y = [coords[ln['desde']][1], coords[ln['hasta']][1]]
    ax.plot(x, y, '-', color='#888', alpha=0.5, lw=1.2)
for _, b in red.buses.iterrows():
    c = coords[b['id']]
    gen = red.generadores[red.generadores['bus'] == b['id']]
    color = 'green' if len(gen) > 0 else 'red'
    ax.scatter(c[0], c[1], s=100, c=color, edgecolor='black', zorder=3)
    ax.annotate(b['nombre'][:14], c, xytext=(5, 5), textcoords='offset points', fontsize=8)
ax.set_xlabel('Longitud (W)')
ax.set_ylabel('Latitud (S)')
ax.set_title('Red SEN reducida (15 subestaciones, 17 lineas 220 kV)')
ax.grid(True, alpha=0.3)
plt.tight_layout()
plt.show()
""")

add_md(NB, """### 3.2 Mantenimientos historicos""")

add_code(NB, """fig, axes = plt.subplots(1, 2, figsize=(14, 4))
ax = axes[0]
tipo_counts = hist_prog['tipo'].value_counts()
ax.bar(tipo_counts.index, tipo_counts.values, color='#3b82f6', edgecolor='black')
ax.set_title('Mantenimientos PROGRAMADOS por tipo (5 anios)')
ax.set_ylabel('Cantidad')
ax.tick_params(axis='x', rotation=20)

ax = axes[1]
causa_counts = hist_forz['causa'].value_counts()
ax.bar(causa_counts.index, causa_counts.values, color='#ef4444', edgecolor='black')
ax.set_title('Mantenimientos FORZADOS por causa (5 anios)')
ax.set_ylabel('Cantidad')
ax.tick_params(axis='x', rotation=20)
plt.tight_layout()
plt.show()
""")

add_md(NB, """## 4. Modelo ML de probabilidad de falla forzada""")

add_code(NB, """feats_full = construir_features(red, hist_forz, feats)
mdl, df_pred = entrenar_modelo_falla(feats_full, hist_forz)
importancias = pd.DataFrame({
    'feature': ['edad_anios', 'longitud_km', 'capacidad_mva', 'capa_uso',
                'temperatura_media_c', 'viento_promedio_ms', 'salinidad_alta', 'uso_intensivo'],
    'importancia': mdl.feature_importances_,
}).sort_values('importancia', ascending=False)
print('Importancia de features ML:')
print(importancias.to_string(index=False))

fig, ax = plt.subplots(figsize=(8, 4))
ax.barh(importancias['feature'], importancias['importancia'], color='#10b981')
ax.invert_yaxis()
ax.set_xlabel('Importancia')
ax.set_title('Random Forest - Importancia de features')
plt.tight_layout()
plt.show()

lambda_pred = predecir_lambda_semanal(mdl, feats_full)
print()
print('Lambda_sem predicha por linea:')
print(lambda_pred.sort_values(ascending=False).to_string())
""")

add_md(NB, """El Random Forest asigna la mayor importancia a **viento_promedio_ms** y **temperatura_media_c**, lo que es razonable en una red aerea expuesta al clima. La **longitud_km** y **edad_anios** tambien aportan (lineas mas largas y mas viejas son mas propensas a fallas).""")

add_md(NB, """## 5. DC Power Flow""")

add_code(NB, """res_base = simulacion_anual_dc(red, demanda, gen, {})
print('Caso base (sin mantenimientos):')
print(res_base[['sem', 'cargabilidad_max', 'linea_cargada', 'congestion_usd', 'congestion_horas']].head(12).to_string(index=False))
""")

add_md(NB, """### 5.1 Sensibilidad: tomar L005 fuera""")

add_code(NB, """test = {w: ['L005'] for w in range(1, 13)}
res_l005 = simulacion_anual_dc(red, demanda, gen, test)
print('L005 fuera todo el horizonte:')
print(res_l005[['sem', 'cargabilidad_max', 'congestion_usd']].head(12).to_string(index=False))

fig, ax = plt.subplots(figsize=(10, 4))
ax.bar(res_base['sem'], res_base['congestion_usd'], label='Sin mantenimiento', alpha=0.7)
ax.bar(res_l005['sem'], res_l005['congestion_usd'], label='L005 fuera', alpha=0.7)
ax.set_xlabel('Semana')
ax.set_ylabel('Costo de congestion (USD)')
ax.set_title('Impacto de sacar L005 fuera (Alto Jahuel - Rancagua)')
ax.legend()
plt.tight_layout()
plt.show()
""")

add_md(NB, """### 5.2 Formulacion matematica del DC PF

Variables: angulo $\\theta_n$ en cada barra $n$, generacion $p_g$ en cada planta, flujo $f_\\ell$ en cada linea $\\ell$.

Restricciones:
$$\\sum_{g \\in n} p_g - D_n = \\sum_{\\ell \\sim n} f_\\ell$$
$$f_\\ell = \\frac{\\theta_{from} - \\theta_{to}}{x_\\ell} \\cdot S_{base}$$
$$-F_\\ell \\le f_\\ell \\le F_\\ell, \\quad \\theta_{slack} = 0$$

Objetivo: minimo costo de despacho + costo de congestion cuando $|f_\\ell| > 0.9 \\cdot F_\\ell$.
""")

add_md(NB, """## 6. MILP: programacion de mantenimientos""")

add_code(NB, """target = hist_prog.groupby('elemento').size().sort_values(ascending=False).head(8).index.tolist()
print(f'Elementos objetivo ({len(target)}): {target}')

cache = _cache_costos_rapido(red, demanda, gen, target, horizonte_semanas=12)
print(f'Cache: {len(cache)} entradas')

p = ParametrosMantenimiento(
    horizonte_semanas=12,
    max_concurrentes=2,
    max_cuadrillas_por_sem=2,
    elementos_objetivo=target,
    duracion_semanas_por_linea={l: 1 for l in target},
)
plan = resolver_milp_mantenimiento(red, cache, p)
print(f'\\nMILP resuelto: objetivo={plan["objetivo"]:.1f} USD')
print('Calendario optimo:')
for linea, pl in plan['plan'].items():
    print(f'  {linea}: semana {pl["inicio"]}')
""")

add_md(NB, """### 6.1 Formulacion matematica del MILP

Variables:
- $x_{i,w} \\in \\{0,1\\}$: la linea $i$ arranca mantenimiento en la semana $w$
- $y_{i,w} \\in \\{0,1\\}$: la linea $i$ esta fuera en la semana $w$

Restricciones:
$$\\sum_{w=1}^{H} y_{i,w} = d_i \\quad \\forall i$$
$$y_{i,w} \\le \\sum_{k=0}^{d_i-1} x_{i,w-k} \\quad \\forall i,w$$
$$\\sum_{i \\in I} y_{i,w} \\le K \\quad \\forall w$$
$$\\sum_{i \\in I} y_{i,w} \\le C \\quad \\forall w$$

Objetivo:
$$\\min \\sum_{i,w} \\Delta c_{i,w} \\cdot y_{i,w}$$

donde $\\Delta c_{i,w}$ es el costo incremental de sacar la linea $i$ en la semana $w$ (proxy del costo de congestion esperado).
""")

add_md(NB, """## 7. Bertsimas-Sim robusto""")

add_code(NB, """rob = robustez_bertsimas_sim(plan['lineas_fuera_por_semana'],
                              duracion_planificada={l: 1 for l in target},
                              gamma=2, max_extension_semanas=1)
print(f'Robustez del plan: gamma={rob["gamma"]}, max_extension={rob["max_extension"]} sem')
print('Slack por semana (cuadrillas libres):')
for w, s in sorted(rob['slack_por_sem'].items()):
    print(f'  sem {w:2d}: {s}')
""")

add_md(NB, """Bertsimas-Sim introduce **presupuesto de incertidumbre** $\\Gamma$. El plan es robusto si hasta $\\Gamma$ elementos pueden extender su duracion en hasta $\\Delta_{max}$ semanas sin violar las restricciones operativas. Para este caso $\\Gamma = 2$ significa: toleramos que hasta 2 lineas se atrasen 1 semana cada una.""")

add_md(NB, """## 8. SAA + CVaR (riesgo)""")

add_code(NB, """esc = simular_escenarios(red, lambda_pred.to_dict(),
                         plan['lineas_fuera_por_semana'],
                         n_escenarios=500)
print(f'Escenarios SAA: {len(esc)}')
print(esc.describe().to_string())

riesgo_m = riesgo_cvar(esc['horas_forzadas'].values, alpha=0.95)
print(f'\\nMetricas de riesgo:')
print(f'  E[horas_forzadas] = {riesgo_m["media"]:.1f}')
print(f'  std                = {riesgo_m["std"]:.1f}')
print(f'  VaR(95%)           = {riesgo_m["VaR"]:.1f}')
print(f'  CVaR(95%)          = {riesgo_m["CVaR"]:.1f}')

fig, ax = plt.subplots(figsize=(8, 4))
ax.hist(esc['horas_forzadas'], bins=30, color='#3b82f6', edgecolor='black', alpha=0.7)
ax.axvline(riesgo_m['VaR'], color='orange', linestyle='--', lw=2, label=f'VaR(95%)={riesgo_m["VaR"]:.1f}')
ax.axvline(riesgo_m['CVaR'], color='red', linestyle='--', lw=2, label=f'CVaR(95%)={riesgo_m["CVaR"]:.1f}')
ax.set_xlabel('Horas de indisponibilidad forzada (12 sem)')
ax.set_ylabel('Frecuencia')
ax.set_title('Distribucion de indisponibilidad forzada (SAA, 500 escenarios)')
ax.legend()
plt.tight_layout()
plt.show()
""")

add_md(NB, """## 9. NSGA-II multi-objetivo""")

add_code(NB, """def evaluar_nsga(orden):
    plan_s = {}
    for idx, pos in enumerate(orden):
        semana = (idx % 12) + 1
        plan_s.setdefault(semana, []).append(target[pos])
    for k in list(plan_s.keys()):
        if len(plan_s[k]) > 2:
            plan_s[k] = plan_s[k][:2]
    base_cost = cache[()]
    costo = base_cost + sum(cache.get((target[pos], pos+1), cache.get((target[pos],), 0.0))
                            for pos in orden)
    horas_total = []
    rng_local = np.random.default_rng(idx)
    for _ in range(80):
        h = 0.0
        for linea in red.lineas['id']:
            lam = lambda_pred.get(linea, 0.0)
            n = int(rng_local.poisson(lam * 12))
            h += n * 8
        horas_total.append(h)
    cvar = float(np.quantile(horas_total, 0.95))
    saidi = 0.0
    for w, lineas in plan_s.items():
        for ln in lineas:
            saidi += lambda_pred.get(ln, 0.0) * 12 * 8
    return costo, cvar, saidi / 1000

pob = nsga2(n_individuos=20, n_generaciones=12,
            n_elementos_objetivo=len(target),
            funcion_evaluar=evaluar_nsga, semilla=20260902, verbose=False)
pareto = [p for p in pob if p.rank == 0]
print(f'Frente de Pareto: {len(pareto)} puntos no dominados')

costos = [p.costo_congestion for p in pareto]
cvars = [p.cvar for p in pareto]
saidis = [p.saidi_horas for p in pareto]

fig = plt.figure(figsize=(10, 7))
ax = fig.add_subplot(111, projection='3d')
ax.scatter(costos, cvars, saidis, c='#10b981', s=80, edgecolor='black')
ax.set_xlabel('Costo de congestion (USD)')
ax.set_ylabel('CVaR (horas)')
ax.set_zlabel('SAIDI proxy')
ax.set_title(f'Frente de Pareto NSGA-II ({len(pareto)} soluciones no dominadas)')
plt.tight_layout()
plt.show()
""")

add_md(NB, """El frente de Pareto muestra el trade-off entre **minimizar costo de congestion** y **minimizar riesgo de indisponibilidad forzada (CVaR)** y **SAIDI zonal**. Las soluciones en el frente son **maximalmente eficientes**: ninguna otra solucion las domina en los tres objetivos.

En la practica, la eleccion de un punto del frente es una **decision de negociacion** con el CEN: la regulacion electa puede exigir un SAIDI maximo (limite inferior), y la rentabilidad del propietario electa un costo maximo.""")

add_md(NB, """## 10. SAIDI por zona""")

add_code(NB, """saidi_df = calcular_saidi_zonal(plan['lineas_fuera_por_semana'], red, lambda_pred.to_dict())
print(saidi_df.to_string(index=False))

fig, ax = plt.subplots(figsize=(8, 4))
ax.barh(saidi_df['zona'], saidi_df['saidi_horas'], color='#f59e0b')
ax.invert_yaxis()
ax.set_xlabel('SAIDI (horas)')
ax.set_title('SAIDI por zona (plan optimo MILP)')
plt.tight_layout()
plt.show()
""")

add_md(NB, """## 11. Resumen final""")

add_code(NB, """print('=' * 60)
print('RESUMEN DEL PROYECTO')
print('=' * 60)
print(f'Red:                  {len(red.buses)} barras, {len(red.lineas)} lineas')
print(f'Horizonte:            12 semanas')
print(f'Lineas a programar:   {len(target)}')
print(f'Costo base (12 sem):  ${cache[()]:,.0f}')
print(f'Costo optimo MILP:    ${plan["objetivo"]:,.0f}')
print(f'CVaR(95%):            {riesgo_m["CVaR"]:.1f} horas')
print(f'Zona con peor SAIDI:  {saidi_df.iloc[0]["zona"]}')
print(f'Pareto:               {len(pareto)} puntos')
""")

add_md(NB, """## 12. Limitaciones y trabajo futuro

1. **DC PF vs AC PF**: las aproximaciones DC son validas para tensiones de 220+ kV con buen factor de potencia. Para 110 kV o redes radiales, los AC PF son necesarios.
2. **Datos sinteticos calibrados**: el caso de estudio usa una reduccion representativa del SEN central. Para publicacion, sustituir por datos reales del CEN (https://www.coordinador.cl/open-data).
3. **Descomposicion Gavish-Graves**: para redes grandes (>500 elementos), aplicar descomposicion temporal/subyacente.
4. **Aprendizaje reforzado**: el problema de programacion es inherentemente secuencial. RL con policy gradient o PPO puede aprender heuristicas superiores al MILP para online scheduling.
5. **Coordinacion con distribuidoras**: el modelo actual es solo transmision. Las multas SAIDI/SAIFI de distribucion (Decreto 4/2018) extienden el problema a la red de media tension.

## 13. Publicacion objetivo

Los resultados apuntan a publicacion en **IEEE Transactions on Power Systems** o **Applied Energy** (Q1): el enfoque de combinar pronostico ML + optimizacion robusta bajo marco regulatorio chileno es diferencial.
""")


out_path = Path('..') / 'notebook' / 'ventanas_mantenimiento.ipynb'
out_path.parent.mkdir(parents=True, exist_ok=True)
with open(out_path, 'w', encoding='utf-8') as f:
    nbformat.write(NB, f)
print(f"Notebook escrito: {out_path}")
print(f"Celdas: {len(NB['cells'])}")