"""
Pipeline del proyecto Ventanas de Mantenimiento.

Orquesta todos los modelos y produce los artefactos que el notebook consume
y que el dashboard D3 visualiza.

Modulos ejecutados en orden:
  1. Carga de datos.
  2. Calculo de costos por ventana individual (DC PF incremental).
  3. Modelo ML de probabilidad de falla forzada (Random Forest).
  4. MILP determinista (baseline).
  5. SAA: 200 escenarios de falla.
  6. NSGA-II multi-objetivo: costo vs CVaR vs SAIDI.
  7. Bertsimas-Sim: chequeo de robustez para el plan optimo.
  8. Exporta JSON para dashboard.

Uso:
    python -m src.pipeline
o:
    python src/pipeline.py
"""
from __future__ import annotations

import json
import math
import sys
import time
import warnings
import zlib
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
from sklearn.metrics import r2_score

# Permitir import desde src/
sys.path.insert(0, str(Path(__file__).resolve().parent))
from optimizacion import (
    SEED,
    Red,
    ParametrosMantenimiento,
    construir_features,
    entrenar_modelo_falla,
    predecir_lambda_semanal,
    resolver_milp_mantenimiento,
    robustez_bertsimas_sim,
    simular_escenarios,
    riesgo_cvar,
    nsga2,
    Individuo,
    calcular_saidi_zonal,
    simulacion_anual_dc,
)


BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"
OUT = BASE / "dashboard" / "data"
OUT.mkdir(parents=True, exist_ok=True)

MAX_CONCURRENTES = 2   # N-1: a lo sumo K lineas en mantenimiento simultaneo


# ===========================================================================
# 1. Carga
# ===========================================================================
def cargar() -> Tuple[Red, pd.DataFrame, pd.DataFrame, pd.DataFrame,
                     pd.DataFrame, pd.DataFrame]:
    red = Red.cargar(str(DATA / "red.json"))
    demanda = pd.read_csv(DATA / "demanda_horaria.csv")
    gen = pd.read_csv(DATA / "generacion_horaria.csv")
    hist_prog = pd.read_csv(DATA / "historico_programado.csv")
    hist_forz = pd.read_csv(DATA / "historico_forzado.csv")
    feats = pd.read_csv(DATA / "features_elementos.csv")
    return red, demanda, gen, hist_prog, hist_forz, feats


# ===========================================================================
# 2. Optimizacion
# ===========================================================================
def orden_a_plan(
    orden: List[int],
    elementos: List[str],
    horizonte_semanas: int = 12,
    max_por_semana: int = MAX_CONCURRENTES,
) -> Dict[int, List[str]]:
    """
    Decodifica un cromosoma (permutacion) a un plan semana -> lineas.

    A diferencia del truncamiento, SIEMPRE asigna ventana a cada elemento:
    si la semana sugerida esta llena, busca la siguiente con cupo.
    """
    plan_s: Dict[int, List[str]] = {}
    ocupacion: Dict[int, int] = {w: 0 for w in range(1, horizonte_semanas + 1)}
    for idx, pos in enumerate(orden):
        elem = elementos[pos]
        w = (idx % horizonte_semanas) + 1
        for _ in range(horizonte_semanas):
            if ocupacion[w] < max_por_semana:
                break
            w = (w % horizonte_semanas) + 1
        plan_s.setdefault(w, []).append(elem)
        ocupacion[w] += 1
    return plan_s


def ejecutar_optimizacion(
    red: Red,
    demanda: pd.DataFrame,
    gen: pd.DataFrame,
    lambda_falla: Dict[str, float],
    elementos_objetivo: List[str],
    horizonte_semanas: int = 12,
) -> Dict:
    """Ejecuta MILP baseline + NSGA-II para los elementos seleccionados."""
    t0 = time.time()
    print("[CACHE] Construyendo cache de costos por (linea, semana)...")
    cache_costos = _cache_costos_rapido(red, demanda, gen, elementos_objetivo,
                                        horizonte_semanas)
    print(f"[CACHE] {len(cache_costos)} entradas ({time.time()-t0:.1f}s)")

    # Coste proxy lineal a partir del cache semanal.
    base_cost = cache_costos[()]

    def _costo_plan(plan_s: Dict[int, List[str]]) -> float:
        total = 0.0
        for w, lineas in plan_s.items():
            for ln in lineas:
                total += cache_costos.get((ln, w), cache_costos.get((ln,), 0.0))
        return base_cost + total

    t0 = time.time()
    print("[MILP] Resolviendo MILP determinista (baseline)...")
    p = ParametrosMantenimiento(
        horizonte_semanas=horizonte_semanas,
        max_concurrentes=MAX_CONCURRENTES,
        max_cuadrillas_por_sem=2,
        elementos_objetivo=elementos_objetivo,
        duracion_semanas_por_linea={l: 1 for l in elementos_objetivo},
    )
    plan_baseline = resolver_milp_mantenimiento(red, cache_costos, p)
    print(f"[MILP] baseline objetivo={plan_baseline.get('objetivo')} ({time.time()-t0:.1f}s)")

    # NSGA-II rapido: costo via cache proxy, CVaR via SAA rapido, SAIDI via
    # exposicion de la linea en la semana asignada.
    t0 = time.time()
    print("[NSGA2] Optimizando Pareto (costo vs CVaR vs SAIDI)...")

    rng_nsga = np.random.default_rng(SEED)
    n_esc_saa = 80

    # demanda semanal total del dataset -> factor estacional REAL
    dem_sem = (demanda.groupby("semana")["demanda_mw"].sum() / 15.0)  # MW por hora promedio
    dem_sem = dem_sem / dem_sem.mean()

    # exposicion zonal por linea: lambda * demanda de la zona que atiende
    carga_zona = red.cargas.groupby("zona")["demanda_base_mw"].sum().to_dict()
    dem_linea: Dict[str, float] = {}
    for _, ln in red.lineas.iterrows():
        dem_linea[ln["id"]] = sum(carga_zona.get(z.strip(), 0.0)
                                  for z in str(ln["zona"]).split("-"))

    def evaluar(orden):
        plan_s = orden_a_plan(orden, elementos_objetivo, horizonte_semanas,
                              MAX_CONCURRENTES)
        costo = _costo_plan(plan_s)
        # CVaR: escenarios Poisson de falla + castigo por clustering de ventanas
        horas_total = []
        for _ in range(n_esc_saa):
            h = 0.0
            for linea in red.lineas["id"]:
                lam = lambda_falla.get(linea, 0.0)
                n = rng_nsga.poisson(lam * horizonte_semanas)
                h += n * 8
            max_conc = max((len(v) for v in plan_s.values()), default=0)
            h *= (1.0 + 0.2 * max_conc)
            horas_total.append(h)
        cvar = float(np.quantile(horas_total, 0.95))
        # SAIDI proxy: exposicion de cada linea en la semana que le toco
        # (lambda * 8h * demanda de su zona * factor estacional de la semana)
        saidi = 0.0
        for w, lineas in plan_s.items():
            f_sem = float(dem_sem.get(w, 1.0))
            for ln in lineas:
                saidi += (lambda_falla.get(ln, 0.0) * 8.0
                          * dem_linea.get(ln, 0.0) * f_sem)
        return costo, cvar, saidi

    poblacion = nsga2(
        n_individuos=20,
        n_generaciones=12,
        n_elementos_objetivo=len(elementos_objetivo),
        funcion_evaluar=evaluar,
        semilla=SEED,
        verbose=True,
    )
    print(f"[NSGA2] {len(poblacion)} individuos ({time.time()-t0:.1f}s)")

    pareto = [pp for pp in poblacion if pp.rank == 0]
    return {
        "cache_costos": cache_costos,
        "base_cost": base_cost,
        "plan_baseline": plan_baseline,
        "pareto": pareto,
        "elementos_objetivo": elementos_objetivo,
    }


def _demanda_semanal_normalizada(demanda: pd.DataFrame) -> pd.Series:
    """Demanda media (MW por instante) de cada semana, normalizada a la media."""
    por_ts = demanda.groupby(["semana", "timestamp"])["demanda_mw"].sum()
    dem = por_ts.groupby("semana").mean()
    return dem / dem.mean()


def _cache_costos_rapido(
    red: Red,
    demanda: pd.DataFrame,
    gen: pd.DataFrame,
    elementos: List[str],
    horizonte_semanas: int = 12,
) -> Dict[Tuple[str, ...], float]:
    """
    Cache de costos (linea, semana) calibrado con DC PF.

    Evalua DC PF en la semana pico y la semana valle REALES del dataset y
    interpola el resto segun la demanda semanal observada. El jitter es
    deterministico entre procesos (crc32, no hash() aleatorizado).

    Para portafolio: velocidad > exactitud. La sustitucion por DC PF
    exhaustivo es directa (8 lineas x 12 semanas = 96 evals).
    """
    cache: Dict[Tuple[str, ...], float] = {}

    res_base = simulacion_anual_dc(red, demanda, gen, {})
    base = float(res_base["congestion_usd"].sum())
    cache[()] = base

    # semanas pico / valle segun demanda real del dataset
    dem_sem = _demanda_semanal_normalizada(demanda)
    dem_sem = dem_sem[dem_sem.index <= horizonte_semanas]
    sem_peak = int(dem_sem.idxmax())
    sem_valle = int(dem_sem.idxmin())
    dem_peak = float(dem_sem.loc[sem_peak])
    dem_valle = float(dem_sem.loc[sem_valle])

    for elem in elementos:
        # DC PF: solo peak y valle
        for w in (sem_peak, sem_valle):
            fuera = {w: [elem]}
            res = simulacion_anual_dc(red, demanda, gen, fuera)
            cache[(elem, w)] = max(0.0, float(res["congestion_usd"].sum()) - base)
        v_peak = cache[(elem, sem_peak)]
        v_valle = cache[(elem, sem_valle)]
        for w in range(1, horizonte_semanas + 1):
            if (elem, w) in cache:
                continue
            # posicion relativa de la demanda de la semana entre valle y pico
            d_w = float(dem_sem.get(w, dem_valle))
            alpha = 0.0 if dem_peak == dem_valle else (d_w - dem_valle) / (dem_peak - dem_valle)
            alpha = min(1.0, max(0.0, alpha))
            valor = v_valle + alpha * (v_peak - v_valle)
            # jitter deterministico entre procesos (crc32 en vez de hash())
            valor *= (1.0 + 0.10 * math.sin((w * zlib.crc32(elem.encode("utf-8"))) % 10))
            cache[(elem, w)] = max(0.0, valor)
        cache[(elem,)] = float(np.mean([cache[(elem, w)] for w in range(1, horizonte_semanas + 1)]))
    return cache


# ===========================================================================
# 3. Exportar
# ===========================================================================
def exportar_para_dashboard(
    red: Red,
    demanda: pd.DataFrame,
    gen: pd.DataFrame,
    cache_costos: Dict[Tuple[str, ...], float],
    plan_baseline: Dict,
    pareto: List[Individuo],
    saidi: pd.DataFrame,
    lambda_falla: Dict[str, float],
    lambda_hist: Dict[str, float],
    ml_importancias: pd.DataFrame,
    ml_r2: float,
    escenarios: pd.DataFrame,
    riesgo: Dict,
    riesgo_por_alpha: Dict[str, Dict],
    robust: Dict,
    elementos_objetivo: List[str],
    horizonte_semanas: int = 12,
) -> None:
    # 1. Red (nodos + aristas) para visualizacion topologica
    nodos = []
    for _, b in red.buses.iterrows():
        nodo = {
            "id": b["id"], "nombre": b["nombre"], "zona": b["zona"],
            "tipo": b["tipo"], "kv": int(b["kv"]),
        }
        if "lat" in red.buses.columns and pd.notna(b.get("lat")):
            nodo["lat"] = float(b["lat"])
            nodo["lon"] = float(b["lon"])
        nodos.append(nodo)
    aristas = []
    for _, l in red.lineas.iterrows():
        aristas.append({
            "source": l["desde"], "target": l["hasta"],
            "id": l["id"], "nombre": l["nombre"],
            "capacidad_mva": float(l["capacidad_mva"]),
            "longitud_km": float(l["longitud_km"]),
            "kv": int(l["kv"]),
            "propietario": l["propietario"],
            "zona": l["zona"],
            "objetivo": l["id"] in elementos_objetivo,
            "lambda_sem": float(lambda_falla.get(l["id"], 0.0)),
        })
    with open(OUT / "red.json", "w", encoding="utf-8") as f:
        json.dump({"nodos": nodos, "aristas": aristas}, f, ensure_ascii=False, indent=2)

    # 2. Calendario Gantt (semana x linea)
    calendario = {}
    if plan_baseline.get("factible"):
        for linea, plan in plan_baseline["plan"].items():
            calendario[linea] = {
                "inicio": plan["inicio"],
                "fuera": plan["fuera"],
            }
    with open(OUT / "calendario.json", "w", encoding="utf-8") as f:
        json.dump(calendario, f, ensure_ascii=False, indent=2)

    # 3. Frente de Pareto (costo INCREMENTAL sobre la base, + plan decodificado)
    base = cache_costos[()]
    pareto_json = []
    for ind in pareto[:30]:  # cap a 30 puntos para el chart
        plan_s = orden_a_plan(ind.orden, elementos_objetivo, horizonte_semanas,
                              MAX_CONCURRENTES)
        semanas = {ln: w for w, lns in plan_s.items() for ln in lns}
        pareto_json.append({
            "costo_congestion": float(ind.costo_congestion - base),
            "cvar": float(ind.cvar),
            "saidi": float(ind.saidi_horas),
            "semanas": semanas,
            "orden": list(ind.orden),
            "rank": int(ind.rank),
        })
    with open(OUT / "pareto.json", "w", encoding="utf-8") as f:
        json.dump(pareto_json, f, ensure_ascii=False, indent=2)

    # 4. SAIDI por zona
    with open(OUT / "saidi.json", "w", encoding="utf-8") as f:
        json.dump(saidi.to_dict(orient="records"), f, ensure_ascii=False, indent=2)

    # 5. ML importancias + predicciones (predicho vs observado)
    ml_data = {
        "importancias": ml_importancias.to_dict(orient="records"),
        "predicciones": [
            {
                "elemento": k,
                "lambda_sem": float(v),
                "lambda_hist": float(lambda_hist.get(k, 0.0)),
                "en_plan": k in elementos_objetivo,
            }
            for k, v in lambda_falla.items()
        ],
        "r2_insample": float(ml_r2),
        "n_muestras": int(len(lambda_falla)),
        "nota": "Prediccion in-sample (n pequeno, datos sinteticos).",
    }
    with open(OUT / "ml.json", "w", encoding="utf-8") as f:
        json.dump(ml_data, f, ensure_ascii=False, indent=2)

    # 6. Escenarios SAA + metricas de riesgo (95% y por alpha)
    with open(OUT / "escenarios.json", "w", encoding="utf-8") as f:
        json.dump({
            "escenarios": escenarios.head(500).to_dict(orient="records"),
            "metricas": riesgo,
            "metricas_por_alpha": riesgo_por_alpha,
            "robustez": {
                "robusto": bool(robust.get("robusto", False)),
                "gamma": int(robust.get("gamma", 0)),
                "gamma_max": int(robust.get("gamma_max", 0)),
                "semana_critica": robust.get("semana_critica"),
                "motivo": robust.get("motivo", ""),
                "slack_por_sem": {str(k): int(v)
                                  for k, v in robust.get("slack_por_sem", {}).items()},
            },
        }, f, ensure_ascii=False, indent=2)

    # 7. Costos por ventana individual (cache) - matriz linea x semana
    cache_str = {}
    for k, v in cache_costos.items():
        clave = "base" if len(k) == 0 else ",".join(str(x) for x in k)
        cache_str[clave] = round(float(v), 2)
    with open(OUT / "costos_ventana.json", "w", encoding="utf-8") as f:
        json.dump(cache_str, f, ensure_ascii=False, indent=2)

    # 8. Costos semanales del plan: total vs base (para incremental honesto)
    if plan_baseline.get("factible"):
        res_base = simulacion_anual_dc(red, demanda, gen, {})
        base_por_sem = {int(r["sem"]): float(r["congestion_usd"])
                        for _, r in res_base.iterrows()}
        # demanda media real (MW por instante) por semana — sin normalizar
        por_ts = demanda.groupby(["semana", "timestamp"])["demanda_mw"].sum()
        dem_sem = por_ts.groupby("semana").mean()
        res_full = simulacion_anual_dc(red, demanda, gen,
                                        plan_baseline["lineas_fuera_por_semana"])
        sem_congestion = {}
        for _, row in res_full.iterrows():
            w = int(row["sem"])
            sem_congestion[w] = {
                "cargabilidad_max": float(row["cargabilidad_max"]),
                "linea_cargada": str(row["linea_cargada"]),
                "congestion_usd": float(row["congestion_usd"]),
                "congestion_base_usd": base_por_sem.get(w, 0.0),
                "incremental_usd": float(row["congestion_usd"]) - base_por_sem.get(w, 0.0),
                "congestion_horas": float(row["congestion_horas"]),
                "lineas_fuera": str(row["lineas_fuera"]),
                "demanda_media_mw": float(dem_sem.get(w, 0.0)),
                "generacion_total_mwh": float(row["generacion_total_mwh"]),
            }
        with open(OUT / "costos_semanales.json", "w", encoding="utf-8") as f:
            json.dump(sem_congestion, f, ensure_ascii=False, indent=2)

    # 9. Resumen ejecutivo
    resumen = {
        "elementos_objetivo": elementos_objetivo,
        "n_lineas_total": len(red.lineas),
        "n_buses": len(red.buses),
        "n_generadores": len(red.generadores),
        "horizonte_semanas": horizonte_semanas,
        "fecha_origen": "2026-01-05",
        "costo_base_proxy": float(cache_costos[()]),
        "costo_milp_incremental": float(plan_baseline.get("objetivo") or 0.0),
        "max_concurrentes": MAX_CONCURRENTES,
        "metodologia": [
            "DC Power Flow con despacho economico (proxy de congestiones, 4 h representativas/sem).",
            "MILP determinista (PuLP/CBC) para programacion de mantenimientos.",
            "Bertsimas-Sim robusto para duraciones inciertas.",
            "Sample Average Approximation (SAA) para escenarios de falla.",
            "NSGA-II multi-objetivo (costo vs CVaR vs SAIDI).",
            "Random Forest para probabilidad de falla forzada.",
        ],
        "version": "2.0",
        "fecha_ejecucion": pd.Timestamp.now().isoformat(),
    }
    with open(OUT / "resumen.json", "w", encoding="utf-8") as f:
        json.dump(resumen, f, ensure_ascii=False, indent=2)

    print(f"\n[OK] {len(list(OUT.glob('*.json')))} archivos JSON exportados a {OUT}")


# ===========================================================================
# Main
# ===========================================================================
def main() -> int:
    print("=" * 60)
    print("VENTANAS DE MANTENIMIENTO - Pipeline completo")
    print("=" * 60)

    t0 = time.time()
    red, demanda, gen, hist_prog, hist_forz, feats = cargar()
    print(f"[1] Datos cargados ({time.time()-t0:.1f}s)")

    # Subset a lineas que requieren mantenimiento en el horizonte:
    # criterio: >= 2 mantenimientos programados historicos (mayor uso).
    target = hist_prog.groupby("elemento").size().sort_values(ascending=False).head(8).index.tolist()
    print(f"[2] Elementos objetivo: {target}")

    # Features ML
    t0 = time.time()
    feats_full = construir_features(red, hist_forz, feats)
    mdl, df_pred = entrenar_modelo_falla(feats_full, hist_forz)
    lambda_falla = predecir_lambda_semanal(mdl, feats_full).to_dict()
    lambda_hist = df_pred.set_index("elemento")["lambda_sem"].to_dict()
    r2 = float(r2_score(df_pred["lambda_sem"], df_pred["lambda_pred_sem"]))
    importancias = pd.DataFrame({
        "feature": ["edad_anios", "longitud_km", "capacidad_mva", "capa_uso",
                    "temperatura_media_c", "viento_promedio_ms", "salinidad_alta", "uso_intensivo"],
        "importancia": mdl.feature_importances_,
    }).sort_values("importancia", ascending=False)
    print(f"[3] ML: R2 in-sample={r2:.3f}, lambda_sem L001="
          f"{lambda_falla.get('L001', 0):.4f} ({time.time()-t0:.1f}s)")
    print(f"    Top features ML:\n{importancias.head(3).to_string(index=False)}")

    # Optimizacion
    t0 = time.time()
    opt = ejecutar_optimizacion(red, demanda, gen, lambda_falla, target,
                                horizonte_semanas=12)
    print(f"[4] Optimizacion total ({time.time()-t0:.1f}s)")

    # SAIDI del plan baseline
    saidi_df = calcular_saidi_zonal(
        opt["plan_baseline"].get("lineas_fuera_por_semana", {w: [] for w in range(1, 13)}),
        red, lambda_falla,
    )

    # SAA escenarios (200) via modulo optimizacion (sin duplicar logica)
    df_esc = simular_escenarios(
        red, lambda_falla,
        opt["plan_baseline"].get("lineas_fuera_por_semana", {w: [] for w in range(1, 13)}),
        n_escenarios=200,
    )
    riesgo_dict = riesgo_cvar(df_esc["horas_forzadas"].values, alpha=0.95)
    riesgo_por_alpha = {
        f"{int(a * 100)}": riesgo_cvar(df_esc["horas_forzadas"].values, alpha=a)
        for a in (0.90, 0.95, 0.99)
    }

    # Bertsimas-Sim (chequeo real: Gamma maximo tolerado)
    robust = robustez_bertsimas_sim(
        opt["plan_baseline"].get("lineas_fuera_por_semana", {}),
        duracion_planificada={l: 1 for l in target},
        gamma=2,
        max_extension_semanas=1,
        max_concurrentes=MAX_CONCURRENTES,
    )
    print(f"[5] Robustez: gamma_max={robust['gamma_max']} "
          f"(pedido Gamma={robust['gamma']}) semana_critica={robust['semana_critica']}")

    # Exportar
    exportar_para_dashboard(
        red, demanda, gen, opt["cache_costos"], opt["plan_baseline"],
        opt["pareto"], saidi_df, lambda_falla, lambda_hist, importancias,
        r2, df_esc, riesgo_dict, riesgo_por_alpha, robust, target,
        horizonte_semanas=12,
    )
    return 0


if __name__ == "__main__":
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        sys.exit(main())
