"""
Modelos matematicos para el proyecto "Ventanas de mantenimiento que le cuestan
menos al sistema".

Contiene:
  - DC power flow (LP) sobre la red SEN reducida.
  - MILP de programacion de mantenimientos (PuLP).
  - Bertsimas-Sim robusto para duraciones inciertas.
  - Sample Average Approximation (SAA) para escenarios de falla.
  - NSGA-II para optimizacion multi-objetivo (implementacion propia minima).
  - Modelo ML de probabilidad de falla forzada (sklearn).

Todas las funciones estan desacopladas para que el notebook las invoque en
orden y pueda intercambiarlas (p.ej. usar PuLP o scipy.optimize.milp).
"""
from __future__ import annotations

import json
import math
import random
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from scipy.optimize import linprog
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor

SEED = 20260902


# ===========================================================================
# 0. Estructuras de datos y carga
# ===========================================================================
@dataclass
class Red:
    buses: pd.DataFrame             # columnas: id, nombre, zona, tipo, kv
    lineas: pd.DataFrame             # id, nombre, desde, hasta, kv, r_pu, x_pu, capacidad_mva, ...
    generadores: pd.DataFrame       # id, bus, tecnologia, p_max_mw, c_mg_usd_mwh
    cargas: pd.DataFrame            # bus, zona, demanda_base_mw, perfil
    base_mva: float = 100.0

    @classmethod
    def cargar(cls, ruta_json: Path) -> "Red":
        with open(ruta_json, "r", encoding="utf-8") as f:
            d = json.loads(f.read())
        return cls(
            buses=pd.DataFrame(d["buses"]),
            lineas=pd.DataFrame(d["lineas"]),
            generadores=pd.DataFrame(d["generadores"]),
            cargas=pd.DataFrame(d["cargas"]),
            base_mva=float(d["base_mva"]),
        )


# ===========================================================================
# 1. DC Power Flow (LP)
# ===========================================================================
def _resolver_dc_pf(
    buses: pd.DataFrame,
    lineas: pd.DataFrame,
    generadores: pd.DataFrame,
    cargas_por_bus: Dict[str, float],
    lineas_fuera: Sequence[str] = (),
) -> Dict:
    """
    DC power flow (LP). Devuelve:
      - angulos_rad: dict bus -> theta en radianes
      - flujos_mva:  dict id linea -> flujo en MVA
      - cargabilidad: dict id linea -> |flujo|/capacidad (0..>1)
      - generacion:  dict id gen -> MW despachados
      - costo_total_usd: costo de despacho si se asigna CMg
      - congestion_usd:   costo de aquellas restricciones activas que exceden capacidad
      - factible: bool
    """
    buses_idx = {b: i for i, b in enumerate(buses["id"].tolist())}
    n = len(buses_idx)
    slack = buses.iloc[0]["id"]

    lineas = lineas[~lineas["id"].isin(lineas_fuera)].reset_index(drop=True)
    g_total = generadores.groupby("bus")["p_max_mw"].sum().to_dict()

    # Agregar un generador virtual en el bus slack (referencia) para absorber
    # desbalances de despacho. Costo bajo y capacidad suficiente.
    virtual_gen_id = "_SLACK_VIRTUAL_"
    gens_work = generadores.copy()
    slack_balance_mw = sum(cargas_por_bus.values()) * 2  # 2x demanda como limite
    virtual_row = pd.DataFrame([{
        "id": virtual_gen_id,
        "nombre": "Slack virtual",
        "bus": slack,
        "tecnologia": "virtual",
        "p_max_mw": float(slack_balance_mw),
        "c_mg_usd_mwh": 200.0,   # costo de oportunidad alto para forzar uso de reales
    }])
    if not (gens_work["id"] == virtual_gen_id).any():
        gens_work = pd.concat([gens_work, virtual_row], ignore_index=True)

    g_idx = {g_id: i for i, g_id in enumerate(gens_work["id"].tolist())}
    n_ang = n
    vars_no = n_ang + len(g_idx)
    gens_por_bus: Dict[str, List[str]] = {b: [] for b in buses["id"]}
    for _, g in gens_work.iterrows():
        gens_por_bus[g["bus"]].append(g["id"])

    # funcion objetivo: min sum_g c_g * P_g (en USD/MWh * hr = h volumen)
    c = np.zeros(vars_no)
    for _, g in gens_work.iterrows():
        c[n_ang + g_idx[g["id"]]] = float(g["c_mg_usd_mwh"])

    # restricciones de igualdad: balance nodal para TODOS los buses + theta[slack]=0
    # B*theta (en p.u.) - sum_g p_g/pu = -P_load/pu
    # donde theta en rad (trato como p.u. de angulo), p_g en MW, P_load en MW, base = 100 MVA.
    eq_rows = []
    eq_rhs = []
    # theta_slack = 0 (referencia de angulos)
    fila = np.zeros(vars_no); fila[buses_idx[slack]] = 1.0
    eq_rows.append(fila); eq_rhs.append(0.0)
    base_mva = 100.0
    for bus in buses["id"]:
        fila = np.zeros(vars_no)
        # B*theta: coeficiente theta_self = +1/x, theta_neighbor = -1/x
        for _, ln in lineas.iterrows():
            if ln["desde"] == bus:
                fila[buses_idx[bus]] += 1.0 / float(ln["x_pu"])
                fila[buses_idx[ln["hasta"]]] -= 1.0 / float(ln["x_pu"])
            elif ln["hasta"] == bus:
                fila[buses_idx[bus]] += 1.0 / float(ln["x_pu"])
                fila[buses_idx[ln["desde"]]] -= 1.0 / float(ln["x_pu"])
        # -sum_g (p_g / base_mva)  => coeficiente p_g = -1/base_mva
        for gid in gens_por_bus[bus]:
            fila[n_ang + g_idx[gid]] -= 1.0 / base_mva
        eq_rows.append(fila)
        eq_rhs.append(-cargas_por_bus.get(bus, 0.0) / base_mva)  # RHS = -P_load/base

    # restricciones de desigualdad: limite termico de linea
    ineq_rows = []
    ineq_rhs = []
    for _, ln in lineas.iterrows():
        # flujo = (theta_f - theta_t) / x_pu (en p.u.)
        # limite: -F_l/base <= flujo <= F_l/base
        for signo, f_linea_pu in ((+1, float(ln["capacidad_mva"]) / 100.0),
                                 (-1, float(ln["capacidad_mva"]) / 100.0)):
            fila = np.zeros(vars_no)
            fila[buses_idx[ln["desde"]]] = signo / float(ln["x_pu"])
            fila[buses_idx[ln["hasta"]]] = -signo / float(ln["x_pu"])
            ineq_rows.append(fila)
            ineq_rhs.append(f_linea_pu)

    bounds = []
    for i in range(n):
        bounds.append((None, None))
    for _, g in gens_work.iterrows():
        pmax = float(g["p_max_mw"])
        bounds.append((0.0, pmax))

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            res = linprog(c, A_ub=np.array(ineq_rows), b_ub=np.array(ineq_rhs),
                          A_eq=np.array(eq_rows), b_eq=np.array(eq_rhs),
                          bounds=bounds, method="highs")
        if not res.success:
            return {"factible": False, "mensaje_rango_rad": res.message}
    except Exception as e:
        return {"factible": False, "mensaje_rango_rad": str(e)}

    angulos_rad = {bus: float(res.x[buses_idx[bus]]) for bus in buses["id"]}
    generacion = {gid: float(res.x[n_ang + g_idx[gid]]) for gid in g_idx}

    flujos_mva: Dict[str, float] = {}
    cargabilidad: Dict[str, float] = {}
    congestion_usd = 0.0
    # usar max CMg de los generadores con despacho > 0 (proxy del generador marginal)
    gens_despachados = [(gid, p) for gid, p in generacion.items() if p > 0.1]
    if gens_despachados:
        c_mg_marginal = max(
            float(gens_work[gens_work["id"] == gid]["c_mg_usd_mwh"].iloc[0])
            for gid, _ in gens_despachados
        )
    else:
        c_mg_marginal = 50.0
    for _, ln in lineas.iterrows():
        flujo_pu = (angulos_rad[ln["desde"]] - angulos_rad[ln["hasta"]]) / float(ln["x_pu"])
        flujo_mva = flujo_pu * 100.0
        flujos_mva[ln["id"]] = flujo_mva
        carg = abs(flujo_mva) / float(ln["capacidad_mva"])
        cargabilidad[ln["id"]] = carg
        # Costo de congestion: lo que excede el 90% de capacidad (proxy
        # de capacidad de reserva insuficiente). Esto es un proxy de la
        # verdadera congestion economics (diferencia entre despacho sin/con
        # restricciones), pero operacionalmente util.
        if carg > 0.90:
            congestion_usd += max(0.0, carg - 0.90) * float(ln["capacidad_mva"]) * c_mg_marginal

    return dict(
        factible=True,
        angulos_rad=angulos_rad,
        flujos_mva=flujos_mva,
        cargabilidad=cargabilidad,
        generacion=generacion,
        congestion_usd=congestion_usd,
        cargabilidad_max=max(cargabilidad.values()) if cargabilidad else 0.0,
        # MW despachados por el generador virtual de referencia: si crece, el
        # caso esta cerca de la infactibilidad y el costo de congestion esta
        # siendo "absorbido" artificialmente por el slack virtual.
        virtual_slack_mw=float(generacion.get("_SLACK_VIRTUAL_", 0.0)),
    )


def simulacion_anual_dc(
    red: Red,
    demanda_horaria: pd.DataFrame,
    gen_horaria: pd.DataFrame,
    lineas_fuera_por_semana: Dict[int, Sequence[str]],
    horas_representativas: Optional[Sequence[int]] = None,
) -> pd.DataFrame:
    """
    Corre DC PF para horas representativas por semana (4 por defecto: 4, 12, 19, 22),
    agregando metricas semanales. Mas rapido que las 168 horas reales.
    """
    if horas_representativas is None:
        horas_representativas = (4, 12, 19, 22)
    # Agregar gen_horaria por (semana, hora) -- mediana a traves de los dias.
    gen_agregado = (
        gen_horaria.groupby(["semana", "hora", "generador"], as_index=False)["p_max_mw"].median()
    )
    dem_agregada = (
        demanda_horaria.groupby(["semana", "hora", "bus"], as_index=False)["demanda_mw"].median()
    )
    semanas = sorted(demanda_horaria["semana"].unique())
    filas = []
    for sem in semanas:
        fuera = list(lineas_fuera_por_semana.get(sem, []))
        sem_dem = dem_agregada[dem_agregada["semana"] == sem]
        sem_gen = gen_agregado[gen_agregado["semana"] == sem]
        horas_fact = [h for h in horas_representativas
                      if h in sem_dem["hora"].unique()]
        if not horas_fact:
            horas_fact = sorted(sem_dem["hora"].unique())
        n_horas = len(horas_fact)
        agg = {
            "sem": sem,
            "horas_evaluadas": n_horas,
            "cargabilidad_max": 0.0,
            "carga_max_linea": 0.0,
            "linea_cargada": "",
            "congestion_usd": 0.0,
            "congestion_horas": 0.0,
            "generacion_total_mwh": 0.0,
            "lineas_fuera": ",".join(fuera) or "-",
        }
        for hora in horas_fact:
            dh = sem_dem[sem_dem["hora"] == hora]
            gh = sem_gen[sem_gen["hora"] == hora]
            # escalar pmax por hora (solar/eolica)
            if len(gh) == 0:
                # sin perfil horario -> usar p_max nominal
                gens_aj = red.generadores.copy()
            else:
                gens_aj = red.generadores.merge(
                    gh[["generador", "p_max_mw"]].rename(columns={"p_max_mw": "p_max_horario"}),
                    left_on="id", right_on="generador", how="left",
                )
                # Si hay multiples filas por generador tras merge, colapsar por mediana
                if gens_aj["id"].duplicated().any():
                    gens_aj = (
                        gens_aj.groupby("id", as_index=False)
                        .agg({"p_max_horario": "median", "p_max_mw": "first"})
                        .merge(red.generadores.drop(columns=["p_max_mw"]),
                               on="id", how="left")
                    )
                gens_aj["p_max_mw"] = gens_aj["p_max_horario"].fillna(gens_aj["p_max_mw"])
            # carga horaria por bus
            if len(dh) > 0 and dh["bus"].duplicated().any():
                dh = dh.groupby("bus", as_index=False)["demanda_mw"].median()
            cargas_por_bus = {r["bus"]: float(r["demanda_mw"]) for _, r in dh.iterrows()}
            res = _resolver_dc_pf(red.buses, red.lineas, gens_aj, cargas_por_bus, fuera)
            if not res["factible"]:
                continue
            agg["cargabilidad_max"] = max(agg["cargabilidad_max"], res["cargabilidad_max"])
            if res["cargabilidad_max"] > 0.99 and res["cargabilidad_max"] >= agg["cargabilidad_max"]:
                # linea mas cargada
                linea_top = max(res["cargabilidad"], key=lambda k: res["cargabilidad"][k])
                agg["linea_cargada"] = linea_top
                agg["carga_max_linea"] = res["cargabilidad"][linea_top]
            agg["congestion_usd"] += res["congestion_usd"]
            if res["cargabilidad_max"] > 1.0:
                agg["congestion_horas"] += 1
            agg["generacion_total_mwh"] += sum(res["generacion"].values())
        filas.append(agg)
    return pd.DataFrame(filas)


# ===========================================================================
# 2. Modelo ML de probabilidad de falla forzada
# ===========================================================================
def construir_features(
    red: Red,
    historico_forzado: pd.DataFrame,
    features_estaticos: pd.DataFrame,
) -> pd.DataFrame:
    """Para cada (elemento, semana): # forzados en ultimas 4 sem, edad, tension, etc."""
    # tasa historica de fallas por linea (por anio)
    tasa = (historico_forzado.groupby("elemento").size() / historico_forzado["anio"].nunique()).rename("tasa_forz_anio")
    feats = features_estaticos.merge(tasa, left_on="elemento", right_index=True, how="left").fillna({"tasa_forz_anio": 0.3})

    # uso intensivo en operacion: % tiempo a >75% capacidad en la historia (proxy)
    # Aqui usamos un proxy deterministico: capacidad/kv.
    feats["uso_intensivo"] = feats["capacidad_mva"] / (feats["kv"] * 1.4)
    # senales climaticas ya estan
    return feats


def entrenar_modelo_falla(
    feats: pd.DataFrame,
    historico_forzado: pd.DataFrame,
    random_state: int = SEED,
) -> Tuple[RandomForestRegressor, pd.DataFrame]:
    """
    Entrena regresor (tasa esperada de fallas/semana por linea).
    Crea variable objetivo = # forzados / # semanas observadas por linea.
    obs = historico_forzado.groupby("elemento").size() / (5 * 52)
    features:
      ['edad_anio', 'longitud_km', 'capacidad_mva', 'capa_uso',
       'temperatura_media_c', 'viento_promedio_ms', 'salinidad_alta',
       'uso_intensivo']
    """
    obs = (historico_forzado.groupby("elemento").size() / (5 * 52)).rename("lambda_sem")
    df = feats.merge(obs, left_on="elemento", right_index=True, how="left").fillna({"lambda_sem": 0.001})

    cols = ["edad_anios", "longitud_km", "capacidad_mva", "capa_uso",
            "temperatura_media_c", "viento_promedio_ms", "salinidad_alta",
            "uso_intensivo"]
    X = df[cols].values
    y = df["lambda_sem"].values
    mdl = RandomForestRegressor(n_estimators=300, max_depth=6,
                                random_state=random_state, n_jobs=1)
    mdl.fit(X, y)
    # in-sample scoring para portafolio
    df["lambda_pred_sem"] = mdl.predict(X)
    # guardar importancias
    importancias = pd.DataFrame({
        "feature": cols,
        "importancia": mdl.feature_importances_,
    }).sort_values("importancia", ascending=False).reset_index(drop=True)
    return mdl, df


def predecir_lambda_semanal(mdl: RandomForestRegressor, feats: pd.DataFrame) -> pd.Series:
    cols = ["edad_anios", "longitud_km", "capacidad_mva", "capa_uso",
            "temperatura_media_c", "viento_promedio_ms", "salinidad_alta",
            "uso_intensivo"]
    return pd.Series(mdl.predict(feats[cols].values), index=feats["elemento"].values, name="lambda_sem")


# ===========================================================================
# 3. MILP para programacion de mantenimientos
# ===========================================================================
@dataclass
class ParametrosMantenimiento:
    horizonte_semanas: int = 12
    costo_restriccion_usd_mwh: float = 70.0   # proxy: max CMg observado
    costo_reprogramacion_usd: float = 8_000.0  # por cambio
    max_concurrentes: int = 2                  # N-1: a lo sumo K fuera
    max_cuadrillas_por_sem: int = 4
    presupuesto_horas_max: int = 6             # horas- cuadrilla maxima por semana
    # lineas que requieren mantenimiento en el horizonte:
    elementos_objetivo: Optional[List[str]] = None

    # duracion en semanas (truncada a 1 semana para demo)
    duracion_semanas_por_linea: Dict[str, int] = None  # type: ignore

    def __post_init__(self):
        if self.duracion_semanas_por_linea is None:
            self.duracion_semanas_por_linea = {}
        if self.elementos_objetivo is None:
            self.elementos_objetivo = []


def resolver_milp_mantenimiento(
    red: Red,
    costo_por_ventana: Dict[Tuple[str, ...], float],
    parametros: ParametrosMantenimiento,
    semilla: int = SEED,
) -> Dict:
    """
    MILP: minimizar costo de congestion total.

    Variables:
      x[i,w] = 1 si la linea i sale de servicio en la semana w
      y[i,w] = 1 si la linea i esta fuera durante la semana w
    Restricciones:
      - Cada linea objetivo debe estar fuera exactamente 'duracion' veces en el horizonte
      - y[i,w] <= sum_{k=0..d-1} x[i, w-k]    (link de duracion)
      - x[i,w] <= y[i,w]                       (si empieza, esta fuera esa sem)
      - sum_i y[i,w] <= K  (max concurrentes)
      - sum_i cuadrilla[i] * y[i,w] <= C  (cuadrillas)
    """
    import pulp

    H = parametros.horizonte_semanas
    I = parametros.elementos_objetivo or []
    if not I:
        return {"factible": False, "mensaje": "sin elementos objetivo"}

    # matriz de costo: cost[i,w] = costo_por_ventana[(i, w)] si existe, sino (i,)
    cost_individual: Dict[Tuple[str, int], float] = {}
    for i in I:
        for w in range(1, H + 1):
            # preferir (i, w); fallback a (i,)
            v = costo_por_ventana.get((i, w))
            if v is None:
                v = costo_por_ventana.get((i,), 0.0)
            cost_individual[(i, w)] = max(0.0, float(v))

    # duracion: truncada a 1 semana para demo
    dur = {p: parametros.duracion_semanas_por_linea.get(p, 1) for p in I}

    # Modelo
    prob = pulp.LpProblem("mantenimiento_min_costo", pulp.LpMinimize)
    x = {(i, w): pulp.LpVariable(f"x_{i}_{w}", cat="Binary") for i in I for w in range(1, H + 1)}
    y = {(i, w): pulp.LpVariable(f"y_{i}_{w}", cat="Binary") for i in I for w in range(1, H + 1)}

    # FO: minimizar congestion total
    prob += pulp.lpSum(cost_individual.get((i, w), 0.0) * y[(i, w)] for i in I for w in range(1, H + 1))

    # Cada linea exactamente 'dur' semanas fuera
    for i in I:
        prob += pulp.lpSum(y[(i, w)] for w in range(1, H + 1)) == dur[i], f"dur_{i}"

    # Link: si y[i,w]=1 entonces hay un x[i, w-k] activo en su ventana
    # (solo semanas validas w-k >= 1; sin clampear hacia x[i,1])
    for i in I:
        d = dur[i]
        for w in range(1, H + 1):
            prob += y[(i, w)] <= pulp.lpSum(x[(i, w - k)]
                                            for k in range(d) if w - k >= 1), f"link_{i}_{w}"

    # Si arranca en w, entonces y[i,w] >= x[i,w]
    for i in I:
        for w in range(1, H + 1):
            prob += y[(i, w)] >= x[(i, w)], f"sync_{i}_{w}"

    # Arrancar exactamente una vez en el horizonte (al menos la primera semana)
    for i in I:
        prob += pulp.lpSum(x[(i, w)] for w in range(1, H + 1)) == 1, f"start_once_{i}"

    # Max concurrentes
    for w in range(1, H + 1):
        prob += pulp.lpSum(y[(i, w)] for i in I) <= parametros.max_concurrentes, f"max_conc_{w}"

    # Cuadrillas: 1 cuadrilla por linea activa
    for w in range(1, H + 1):
        prob += pulp.lpSum(y[(i, w)] for i in I) <= parametros.max_cuadrillas_por_sem, f"cuad_{w}"

    # Resolver
    solver = pulp.PULP_CBC_CMD(msg=0)
    prob.solve(solver)

    if prob.status != 1:
        return {"factible": False, "mensaje": pulp.LpStatus[prob.status], "objetivo": None}

    # extraer plan
    plan: Dict[str, Dict] = {}
    for i in I:
        sem_inicio = next((w for w in range(1, H + 1) if x[(i, w)].value() and x[(i, w)].value() > 0.5), None)
        sems_fuera = [w for w in range(1, H + 1) if y[(i, w)].value() and y[(i, w)].value() > 0.5]
        plan[i] = {"inicio": sem_inicio, "fuera": sems_fuera}

    lineas_fuera_por_semana = {w: [] for w in range(1, H + 1)}
    for i, p in plan.items():
        for w in p["fuera"]:
            lineas_fuera_por_semana[w].append(i)

    return {
        "factible": True,
        "objetivo": float(pulp.value(prob.objective)),
        "plan": plan,
        "lineas_fuera_por_semana": lineas_fuera_por_semana,
    }


def _calcular_costos_por_ventana(
    red: Red,
    demanda_horaria: pd.DataFrame,
    gen_horaria: pd.DataFrame,
    horas_por_sem: int = 168,
) -> Dict[Tuple[str, ...], float]:
    """Evalua DC PF para cada combinacion pequena de lineas fuera (1 o 2 lineas)."""
    costo_cache: Dict[Tuple[str, ...], float] = {}
    elementos = red.lineas["id"].tolist()
    # caso base (sin mantenimientos)
    res0 = simulacion_anual_dc(red, demanda_horaria, gen_horaria, {})
    costo_base = res0["congestion_usd"].sum()
    costo_cache[()] = costo_base

    # combinaciones de tamano 1
    for i in elementos:
        res = simulacion_anual_dc(red, demanda_horaria, gen_horaria,
                                  {1: [i], 2: [i], 3: [i], 4: [i], 5: [i], 6: [i],
                                   7: [i], 8: [i], 9: [i], 10: [i], 11: [i], 12: [i]})
        costo_cache[(i,)] = res["congestion_usd"].sum() - costo_base

    # combinaciones de tamano 2 (limitado a las mas relevantes: pares con
    # cargabilidad alta individual). Para 15 lineas: 105 pares -> ~30 seg.
    pares = [(i, j) for i in elementos for j in elementos if i < j]
    # Solo pares donde i o j tienen costo individual alto (> 50% del max)
    max_cost = max(v for v in costo_cache.values() if isinstance(v, (int, float)))
    pares_relev = [(i, j) for i, j in pares if costo_cache[(i,)] > 0.4 * max_cost
                   or costo_cache[(j,)] > 0.4 * max_cost]
    for i, j in pares_relev:
        res = simulacion_anual_dc(red, demanda_horaria, gen_horaria,
                                  {1: [i, j], 2: [i, j], 3: [i, j], 4: [i, j], 5: [i, j],
                                   6: [i, j], 7: [i, j], 8: [i, j], 9: [i, j],
                                   10: [i, j], 11: [i, j], 12: [i, j]})
        costo_cache[(i, j)] = res["congestion_usd"].sum() - costo_base

    return costo_cache


# ===========================================================================
# 4. Bertsimas-Sim robusto (duracion incierta)
# ===========================================================================
def robustez_bertsimas_sim(
    plan_determinista: Dict[int, List[str]],
    duracion_planificada: Dict[str, int],
    gamma: int = 2,
    max_extension_semanas: int = 1,
    max_concurrentes: int = 2,
) -> Dict:
    """
    Bertsimas-Sim sobre la restriccion de simultaneidad del plan.

    Incertidumbre: la duracion de cada mantenimiento puede extenderse hasta
    `max_extension_semanas` semanas. Presupuesto Gamma: a lo mas `gamma`
    lineas se extienden simultaneamente (peor caso).

    El plan es robusto sii para toda semana w del horizonte extendido:

        |activos(w)| + min(gamma, candidatos(w)) <= max_concurrentes

    donde candidatos(w) = lineas cuya ventana termina en [w-ext, w-1] y no
    estan activas en w (pueden "invadir" la semana w al extenderse).

    Devuelve robusto, el maximo Gamma tolerado y la semana critica.
    """
    if not plan_determinista:
        return {"robusto": False, "gamma": gamma, "gamma_max": 0,
                "semana_critica": None, "slack_por_sem": {},
                "motivo": "plan vacio"}

    H = max(plan_determinista)
    ext = max(1, int(max_extension_semanas))
    K = int(max_concurrentes)

    # ultima semana programada por linea (fin nominal de su ventana)
    fin: Dict[str, int] = {}
    for w in range(1, H + 1):
        for linea in plan_determinista.get(w, []):
            fin[linea] = w

    slack_por_sem: Dict[int, int] = {}
    gamma_max = gamma  # al menos el presupuesto pedido
    semana_critica = None
    for w in range(1, H + ext + 1):
        activos = len(plan_determinista.get(w, []))
        # lineas que podrian invadir w al extenderse: terminan poco antes
        candidatos = sum(
            1 for l, f in fin.items() if w - ext <= f < w
            and l not in plan_determinista.get(w, [])
        )
        slack = K - activos
        slack_por_sem[w] = slack
        # La semana acota Gamma solo si hay mas candidatos que cupo:
        # violacion  <=>  activos + min(Gamma, candidatos) > K
        if candidatos > slack:
            if slack < gamma_max:
                gamma_max = max(0, slack)
                semana_critica = w

    robusto = gamma_max >= gamma
    return {
        "robusto": bool(robusto),
        "gamma": int(gamma),
        "gamma_max": int(gamma_max),
        "max_extension": ext,
        "semana_critica": semana_critica,
        "slack_por_sem": slack_por_sem,
        "motivo": "" if robusto else
                  (f"semana {semana_critica} no tolera Gamma={gamma} "
                   f"(gamma_max={gamma_max})"),
    }


# ===========================================================================
# 5. Sample Average Approximation (SAA)
# ===========================================================================
def simular_escenarios(
    red: Red,
    lambda_falla: Dict[str, float],
    plan: Dict[int, List[str]],
    n_escenarios: int = 200,
    semilla: int = SEED,
) -> pd.DataFrame:
    """
    Genera `n_escenarios` de indisponibilidad forzadas en el horizonte (12 sem).
    Cada escenario = tupla (linea -> [semanas adicionales fuera]).
    """
    rng = np.random.default_rng(semilla)
    H = max(plan.keys())
    filas = []
    for e in range(n_escenarios):
        # numero esperado de fallas por linea en H semanas = lambda * H
        extras_total = 0
        horas_forzadas = 0.0
        for linea in red.lineas["id"].tolist():
            lam = lambda_falla.get(linea, 0.0)
            n_fallas = rng.poisson(lam * H)
            extras_total += n_fallas
            horas_forzadas += n_fallas * 8.0
        filas.append(dict(escenario=e,
                          fallas=extras_total,
                          horas_forzadas=horas_forzadas))
    return pd.DataFrame(filas)


def riesgo_cvar(horas_forzadas: np.ndarray, alpha: float = 0.95) -> Dict[str, float]:
    var = float(np.quantile(horas_forzadas, alpha))
    cola = horas_forzadas[horas_forzadas >= var]
    cvar = float(cola.mean()) if len(cola) else var
    return {"VaR": var, "CVaR": cvar, "media": float(horas_forzadas.mean()),
            "std": float(horas_forzadas.std())}


# ===========================================================================
# 6. NSGA-II (implementacion propia)
# ===========================================================================
@dataclass
class Individuo:
    """Cromosoma: orden en que se programa cada linea objetivo."""
    orden: List[int]                    # permutacion de tamano N_obj
    costo_congestion: float = 1e9
    cvar: float = 1e9
    saidi_horas: float = 1e9
    rank: int = 0
    crowding: float = 0.0
    _id: int = 0

    def __hash__(self):
        return id(self)

    def __eq__(self, other):
        return self is other


def _crossover(padre: Individuo, madre: Individuo, rng: random.Random) -> Individuo:
    """Order crossover (OX): copia un segmento del padre y rellena el resto
    en el orden relativo de la madre."""
    n = len(padre.orden)
    a, c = padre.orden, madre.orden
    i, j = sorted(rng.sample(range(n), 2))
    segmento = a[i:j + 1]
    resto = [g for g in c if g not in segmento]
    hijo_ox = resto[:i] + segmento + resto[i:]
    return Individuo(orden=hijo_ox)


def _mutar(ind: Individuo, rng: random.Random, p_swap: float = 0.1) -> bool:
    n = len(ind.orden)
    orden = ind.orden.copy()
    muto = False
    for i in range(n):
        if rng.random() < p_swap:
            j = rng.randrange(n)
            orden[i], orden[j] = orden[j], orden[i]
            muto = True
    ind.orden = orden
    return muto


def _domina(a: Individuo, b: Individuo) -> bool:
    mejor_en_alguno = False
    for o1, o2 in ((a.costo_congestion, b.costo_congestion),
                   (a.cvar, b.cvar),
                   (a.saidi_horas, b.saidi_horas)):
        if o1 > o2:
            return False
        if o1 < o2:
            mejor_en_alguno = True
    return mejor_en_alguno


def nsga2(
    n_individuos: int,
    n_generaciones: int,
    n_elementos_objetivo: int,
    funcion_evaluar,
    semilla: int = SEED,
    verbose: bool = False,
) -> List[Individuo]:
    """NSGA-II minimalista. `funcion_evaluar(orden) -> (costo, cvar, saidi)`."""
    rng = random.Random(semilla)
    # inicializacion: permutaciones aleatorias
    poblacion: List[Individuo] = []
    base = list(range(n_elementos_objetivo))
    for _ in range(n_individuos):
        orden = base.copy()
        rng.shuffle(orden)
        poblacion.append(Individuo(orden=orden))
    # evaluar
    for ind in poblacion:
        c, cv, sd = funcion_evaluar(ind.orden)
        ind.costo_congestion, ind.cvar, ind.saidi_horas = c, cv, sd

    for gen in range(n_generaciones):
        # generar hijos
        hijos: List[Individuo] = []
        while len(hijos) < n_individuos:
            p1, p2 = rng.sample(poblacion, k=2)
            hijo = _crossover(p1, p2, rng)
            _mutar(hijo, rng)
            c, cv, sd = funcion_evaluar(hijo.orden)
            hijo.costo_congestion, hijo.cvar, hijo.saidi_horas = c, cv, sd
            hijos.append(hijo)
        union = poblacion + hijos
        # non-dominated sorting: asignar rank
        # Construir frentes manualmente (O(N^2) suficiente para N=20)
        S = {ind: [] for ind in union}
        np_ = {ind: 0 for ind in union}
        rank = {ind: -1 for ind in union}
        fronts: Dict[int, List[Individuo]] = {0: []}
        for p in union:
            for q in union:
                if p is q:
                    continue
                if _domina(p, q):
                    S[p].append(q)
                elif _domina(q, p):
                    np_[p] += 1
            if np_[p] == 0:
                rank[p] = 0
                fronts[0].append(p)
        i = 0
        while fronts.get(i):
            prox: List[Individuo] = []
            for p in fronts[i]:
                for q in S[p]:
                    np_[q] -= 1
                    if np_[q] == 0:
                        rank[q] = i + 1
                        prox.append(q)
            i += 1
            fronts[i] = prox
        # crowding distance (frente por frente)
        selected: List[Individuo] = []
        fi = 0
        while len(selected) < n_individuos and fronts.get(fi):
            frente = fronts[fi]
            if len(selected) + len(frente) <= n_individuos:
                selected.extend(frente)
            else:
                # crowding: ordenar por cada objetivo y asignar
                for obj in ("costo_congestion", "cvar", "saidi_horas"):
                    frente.sort(key=lambda x: getattr(x, obj))
                # crowding distance
                for p in frente:
                    p.crowding = 0.0
                for obj in ("costo_congestion", "cvar", "saidi_horas"):
                    vals = [getattr(p, obj) for p in frente]
                    if max(vals) == min(vals):
                        continue
                    frente[0].crowding = float("inf")
                    frente[-1].crowding = float("inf")
                    for k in range(1, len(frente) - 1):
                        frente[k].crowding += (vals[k + 1] - vals[k - 1]) / (max(vals) - min(vals))
                frente.sort(key=lambda p: p.crowding, reverse=True)
                selected.extend(frente[: n_individuos - len(selected)])
            fi += 1
        # asignar rank final
        for ind in selected:
            ind.rank = rank.get(ind, 0)
        poblacion = selected
        if verbose and gen % 5 == 0:
            best = min(poblacion, key=lambda p: p.costo_congestion)
            print(f"  gen {gen:3d} mejor_costo={best.costo_congestion:>10,.0f} "
                  f"cvar={best.cvar:.1f} saidi={best.saidi_horas:.2f}")

    return poblacion


# ===========================================================================
# 7. SAIDI zonal (calculo agregado)
# ===========================================================================
def calcular_saidi_zonal(
    plan: Dict[int, List[str]],
    red: Red,
    lambda_falla: Dict[str, float],
) -> pd.DataFrame:
    """
    SAIDI zonal proxy. NOTA DE UNIDADES: expone semanas-de-linea-fuera por MW
    de demanda zonal (indice proxy, no horas/cliente reales como las define
    el Decreto 4/2018; requiere mapeo a clientes reales para eso).
    """
    if not plan:
        plan = {1: []}
    H = max(plan.keys())
    cargas_por_zona = red.cargas.groupby("zona")["demanda_base_mw"].sum().to_dict()
    lineas_por_zona = {}
    horas_fuera: Dict[str, int] = {l: 0 for l in red.lineas["id"]}
    for w in range(1, H + 1):
        for linea in plan.get(w, []):
            horas_fuera[linea] = horas_fuera.get(linea, 0) + 1

    # mapear linea a zonas atendidas
    zonas_por_linea: Dict[str, set] = {l: set() for l in red.lineas["id"]}
    for _, ln in red.lineas.iterrows():
        zonas_por_linea[ln["id"]].add(ln["zona"])

    zonas = sorted(cargas_por_zona.keys())
    filas = []
    for z in zonas:
        carga_z = cargas_por_zona[z]
        horas_z = 0.0
        for linea in red.lineas["id"]:
            if z in zonas_por_linea[linea]:
                horas_z += horas_fuera.get(linea, 0)
        saidi_h = horas_z / max(1, carga_z)
        filas.append(dict(zona=z, demanda_mw=carga_z,
                          horas_indisp=horas_z,
                          saidi_horas=round(saidi_h, 6)))
    return pd.DataFrame(filas).sort_values("saidi_horas", ascending=False).reset_index(drop=True)