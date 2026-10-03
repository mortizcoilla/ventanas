"""
Generador de datos sinteticos calibrados al SEN (Chile).

Construye:
  - Red de transmision reducida (lineas + subestaciones) del SIC central.
  - Series de demanda horaria por zona (12 semanas).
  - Historico de mantenimientos programados y forzados (5 anios).
  - Parametros tecnicos y economicos.

NO usar: baja data real del CEN. Esto es debuggible, repetible y
suficientemente realista para validar el approach tecnico-producto.
La sustitucion por datos reales del coordinador.cl es directa
(mismos `cable-IDs`, misma `topologia` en `data/red.json`).
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

SEED = 20260902
RNG = np.random.default_rng(SEED)


# ---------------------------------------------------------------------------
# 1. Red: 15 lineas de 220 kV del tramo central Chile-SIC.
#    Reactancias en p.u. base 100 MVA. Capacidad termica en MVA.
#    Capacidades calibradas para reproducir congestion ante N-1.
# ---------------------------------------------------------------------------
@dataclass
class Barra:
    id: str
    nombre: str
    zona: str
    tipo: str          # 'generacion' | 'carga' | 'paso' | 'transformacion'
    kv: int
    lat: float         # coordenada geografica aproximada (para el dashboard)
    lon: float


@dataclass
class Linea:
    id: str
    nombre: str
    desde: str
    hasta: str
    kv: int
    r_pu: float
    x_pu: float
    capacidad_mva: float
    longitud_km: float
    zona: str
    propietario: str


@dataclass
class Generador:
    id: str
    nombre: str
    bus: str
    tecnologia: str      # 'hidro' | 'termo' | 'solar' | 'eolica'
    p_max_mw: float
    c_mg_usd_mwh: float   # costo marginal


@dataclass
class Carga:
    bus: str
    zona: str
    demanda_base_mw: float
    perfil: str           # 'industrial' | 'residencial' | 'mixto'


# Coordenadas aproximadas de las SE del tramo central (lat, lon negativos).
BARRAS: List[Barra] = [
    Barra("S001", "Quillota 220",       "Valparaiso",  "paso",          220, -32.88, -71.20),
    Barra("S002", "Polpaico 220",       "RM",          "transformacion", 220, -33.12, -70.74),
    Barra("S003", "Lo Aguirre 220",     "RM",          "paso",          220, -33.38, -70.78),
    Barra("S004", "Alto Jahuel 220",    "RM",          "paso",          220, -33.67, -70.80),
    Barra("S005", "Ancoa 220",          "Maule",       "paso",          220, -35.42, -71.60),
    Barra("S006", "Itahue 220",         "Maule",       "paso",          220, -35.18, -71.68),
    Barra("S007", "Charrúa 220",        "Biobio",      "paso",          220, -37.28, -72.41),
    Barra("S008", "Pangue 220",         "Biobio",      "generacion",    220, -37.38, -71.93),
    Barra("S009", "Trupán 220",         "Biobio",      "transformacion", 220, -37.42, -72.53),
    Barra("S010", "Temuco 220",         "Araucania",   "paso",          220, -38.68, -72.55),
    Barra("S011", "Ciruelos 220",       "Biobio",      "paso",          220, -37.07, -72.42),
    Barra("S012", "Rancagua 220",       "OHiggins",    "paso",          220, -34.16, -70.74),
    Barra("S013", "Maitenes 220",       "RM",          "generacion",    220, -34.02, -70.89),
    Barra("S014", "Rapel 220",          "OHiggins",    "generacion",    220, -34.29, -71.34),
    Barra("S015", "Pehuenche 220",      "Maule",       "generacion",    220, -35.85, -71.13),
]

LINEAS: List[Linea] = [
    # (id, nombre, desde, hasta, kv, r, x, MVA, km, zona, propietario)
    Linea("L001", "Quillota-Polpaico 1",      "S001", "S002", 220, 0.0120, 0.0850, 380, 132, "Valparaiso-RM", "Transelec"),
    Linea("L002", "Quillota-Polpaico 2",      "S001", "S002", 220, 0.0120, 0.0850, 380, 132, "Valparaiso-RM", "Transelec"),
    Linea("L003", "Polpaico-Lo Aguirre",      "S002", "S003", 220, 0.0090, 0.0640, 480, 95,  "RM",            "Transelec"),
    Linea("L004", "Lo Aguirre-Alto Jahuel",   "S003", "S004", 220, 0.0070, 0.0520, 520, 78,  "RM",            "Transelec"),
    Linea("L005", "Alto Jahuel-Rancagua",     "S004", "S012", 220, 0.0140, 0.0980, 380, 145, "RM-OHiggins",   "Transelec"),
    Linea("L006", "Alto Jahuel-Maitenes",     "S004", "S013", 220, 0.0110, 0.0780, 320, 118, "RM",            "Engie"),
    Linea("L007", "Rancagua-Itahue",           "S012", "S006", 220, 0.0180, 0.1240, 380, 178, "OHiggins-Maule","Transelec"),
    Linea("L008", "Itahue-Ancoa",             "S006", "S005", 220, 0.0095, 0.0680, 380, 102, "Maule",         "Transelec"),
    Linea("L009", "Ancoa-Charrúa",            "S005", "S007", 220, 0.0140, 0.0950, 420, 162, "Maule-Biobio",  "Transelec"),
    Linea("L010", "Charrúa-Trupán",           "S007", "S009", 220, 0.0075, 0.0560, 520, 91,  "Biobio",        "Transelec"),
    Linea("L011", "Charrúa-Pangue",           "S007", "S008", 220, 0.0065, 0.0480, 540, 84,  "Biobio",        "Engie"),
    Linea("L012", "Trupán-Ciruelos",          "S009", "S011", 220, 0.0055, 0.0420, 560, 72,  "Biobio",        "Transelec"),
    Linea("L013", "Ciruelos-Temuco",          "S011", "S010", 220, 0.0135, 0.0920, 400, 156, "Biobio-Araucania","Transelec"),
    Linea("L014", "Itahue-Pehuenche",         "S006", "S015", 220, 0.0070, 0.0510, 480, 88,  "Maule",         "Enel"),
    Linea("L015", "Rancagua-Rapel",              "S012", "S014", 220, 0.0085, 0.0620, 440, 96,  "OHiggins",      "Engie"),
    Linea("L016", "Ancoa-Pehuenche",            "S005", "S015", 220, 0.0075, 0.0540, 420, 92,  "Maule",         "Enel"),
    Linea("L017", "Polpaico-Alto Jahuel 1",      "S002", "S004", 220, 0.0060, 0.0450, 560, 65,  "RM",            "Transelec"),
]

GENERADORES: List[Generador] = [
    # Capacidad instalada para la reduccion representativa (~2 GW totales).
    Generador("G01", "Maitenes U1",      "S013", "hidro",  100, 18.5),
    Generador("G02", "Maitenes U2",      "S013", "hidro",  100, 18.5),
    Generador("G03", "Rapel U1",         "S014", "hidro",  220, 20.0),
    Generador("G04", "Pehuenche U1",     "S015", "hidro",  280, 19.0),
    Generador("G05", "Pehuenche U2",     "S015", "hidro",  280, 19.0),
    Generador("G06", "Pangue U1",        "S008", "termo",  170, 62.0),
    Generador("G07", "Pangue U2",        "S008", "termo",  170, 62.0),
    Generador("G08", "Quillota Solar 1", "S001", "solar",  150,  1.0),
    Generador("G09", "Quillota Solar 2", "S001", "solar",  150,  1.0),
    Generador("G10", "Charrúa Eolica",   "S007", "eolica", 120,  0.5),
]

CARGAS: List[Carga] = [
    # Demanda calibrada para una reduccion representativa del SEN central:
    # ~13 GW de pico historico del tramo, mapeado a ~1300 MW en este set.
    Carga("S001", "Valparaiso", 105, "mixto"),
    Carga("S002", "RM",         198, "mixto"),
    Carga("S003", "RM",         145, "industrial"),
    Carga("S004", "RM",         182, "mixto"),
    Carga("S005", "Maule",       58, "industrial"),
    Carga("S006", "Maule",       48, "industrial"),
    Carga("S007", "Biobio",     125, "industrial"),
    Carga("S008", "Biobio",      14, "residencial"),
    Carga("S009", "Biobio",      43, "industrial"),
    Carga("S010", "Araucania",   52, "residencial"),
    Carga("S011", "Biobio",      34, "industrial"),
    Carga("S012", "OHiggins",    76, "mixto"),
    Carga("S013", "RM",            9, "residencial"),
    Carga("S014", "OHiggins",      5, "residencial"),
    Carga("S015", "Maule",          4, "residencial"),
]


# ---------------------------------------------------------------------------
# 2. Perfiles de demanda y generacion ERNC (semanal x horario).
# ---------------------------------------------------------------------------
def _perfil_residencial(hora: int) -> float:
    if hora <= 6:    return 0.55
    if hora <= 9:    return 0.85
    if hora <= 18:   return 0.75
    if hora <= 22:   return 1.00
    return 0.70


def _perfil_industrial(hora: int) -> float:
    if hora <= 6:    return 0.65
    if hora <= 18:   return 1.05
    if hora <= 22:   return 0.95
    return 0.70


def _perfil_mixto(hora: int) -> float:
    return 0.6 * _perfil_residencial(hora) + 0.4 * _perfil_industrial(hora)


def _factor_estacional_semana(semana: int) -> float:
    if semana in (5, 6, 7, 8, 9):                return 0.78
    if semana in (22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34): return 1.18
    return 1.00


def _perfil_solar(hora: int) -> float:
    if hora < 7 or hora > 19: return 0.0
    if hora < 9: return 0.30
    if hora < 12: return 0.85
    if hora < 16: return 1.00
    if hora < 18: return 0.55
    return 0.10


def _perfil_eolica(hora: int) -> float:
    base = 0.55 + 0.25 * math.sin(hora / 24 * 2 * math.pi)
    return max(0.10, min(1.0, base))


# ---------------------------------------------------------------------------
# 3. Historico de mantenimientos programados y forzados.
# ---------------------------------------------------------------------------
def generar_historico_mantenimientos(
    fecha_inicio: datetime,
    n_anios: int,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    elementos = [l.id for l in LINEAS]
    registros_prog: List[Dict] = []
    registros_forz: List[Dict] = []

    for anio in range(n_anios):
        for sem in range(1, 53):
            for linea in LINEAS:
                if RNG.random() < 0.012:
                    duracion_h = int(RNG.choice([4, 8, 12, 16, 24, 36, 48],
                                                 p=[0.18, 0.30, 0.22, 0.14, 0.08, 0.05, 0.03]))
                    if duracion_h <= 4:
                        tipo = "Inspeccion"
                    elif duracion_h <= 16:
                        tipo = "Preventivo"
                    elif duracion_h <= 36:
                        tipo = "Mayor programado"
                    else:
                        tipo = "Cambio equipamiento"
                    fecha = fecha_inicio + timedelta(weeks=(anio * 52) + (sem - 1))
                    costo_usd = 8_000 * duracion_h * RNG.uniform(0.7, 1.4)
                    registros_prog.append(dict(
                        elemento=linea.id,
                        semana=sem,
                        anio=2024 + anio,
                        fecha=fecha.strftime("%Y-%m-%d"),
                        duracion_h=duracion_h,
                        tipo=tipo,
                        costo_usd=round(costo_usd, 2),
                        propietario=linea.propietario,
                    ))
                lam = 0.0015 + 0.0008 * (1 if sem in range(20, 35) else 0)
                n_forz = RNG.poisson(lam)
                for _ in range(n_forz):
                    duracion_h = int(RNG.choice([2, 4, 8, 16, 24, 48, 72],
                                                p=[0.30, 0.25, 0.20, 0.10, 0.08, 0.05, 0.02]))
                    fecha = fecha_inicio + timedelta(weeks=(anio * 52) + (sem - 1),
                                                     days=int(RNG.integers(0, 7)))
                    costo_usd = 35_000 * duracion_h * RNG.uniform(0.8, 1.6)
                    registros_forz.append(dict(
                        elemento=linea.id,
                        semana=sem,
                        anio=2024 + anio,
                        fecha=fecha.strftime("%Y-%m-%d"),
                        duracion_h=duracion_h,
                        costo_usd=round(costo_usd, 2),
                        propietario=linea.propietario,
                        causa=RNG.choice(["Falla mecanica", "Falla electrica",
                                          "Evento climatico", "Desconocida"],
                                         p=[.55, .25, .12, .08]),
                    ))

    return pd.DataFrame(registros_prog), pd.DataFrame(registros_forz)


# ---------------------------------------------------------------------------
# 4. Demanda horaria por bus por 12 semanas.
# ---------------------------------------------------------------------------
def generar_demanda_horaria(
    fecha_inicio: datetime,
    n_semanas: int,
) -> pd.DataFrame:
    filas = []
    buses_por_zona = {c.bus: c for c in CARGAS}
    for sem in range(1, n_semanas + 1):
        factor_sem = _factor_estacional_semana(sem)
        for dia in range(7):
            for hora in range(24):
                ts = fecha_inicio + timedelta(weeks=(sem - 1), days=dia, hours=hora)
                for bus, c in buses_por_zona.items():
                    if c.perfil == "industrial":
                        f_hora = _perfil_industrial(hora)
                    elif c.perfil == "residencial":
                        f_hora = _perfil_residencial(hora)
                    else:
                        f_hora = _perfil_mixto(hora)
                    ruido = RNG.normal(1.0, 0.025)
                    demanda = max(0.0, c.demanda_base_mw * factor_sem * f_hora * ruido)
                    filas.append(dict(
                        timestamp=ts.strftime("%Y-%m-%d %H:%M"),
                        semana=sem,
                        dia=dia,
                        hora=hora,
                        bus=bus,
                        zona=c.zona,
                        demanda_mw=round(demanda, 3),
                    ))
    return pd.DataFrame(filas)


def generar_generacion_horaria(
    fecha_inicio: datetime,
    n_semanas: int,
) -> pd.DataFrame:
    filas = []
    for sem in range(1, n_semanas + 1):
        for dia in range(7):
            for hora in range(24):
                ts = fecha_inicio + timedelta(weeks=(sem - 1), days=dia, hours=hora)
                for g in GENERADORES:
                    if g.tecnologia == "solar":
                        p = g.p_max_mw * _perfil_solar(hora) * RNG.uniform(0.85, 1.00)
                    elif g.tecnologia == "eolica":
                        p = g.p_max_mw * _perfil_eolica(hora) * RNG.uniform(0.80, 1.00)
                    else:
                        p = g.p_max_mw * _perfil_industrial(hora) * RNG.uniform(0.78, 1.00)
                    filas.append(dict(
                        timestamp=ts.strftime("%Y-%m-%d %H:%M"),
                        semana=sem,
                        dia=dia,
                        hora=hora,
                        generador=g.id,
                        tecnologia=g.tecnologia,
                        p_max_mw=round(max(0.0, p), 3),
                    ))
    return pd.DataFrame(filas)


# ---------------------------------------------------------------------------
# 5. Features estaticos para el modelo ML de falla.
# ---------------------------------------------------------------------------
def generar_features_ml() -> pd.DataFrame:
    filas = []
    for l in LINEAS:
        edad = round(8 + l.longitud_km / 18 + RNG.normal(0, 3), 1)
        if edad < 12:                       capa = 90
        elif edad < 20:                     capa = 18
        elif edad < 28:                     capa = 9
        else:                               capa = 3
        filas.append(dict(
            elemento=l.id,
            kv=l.kv,
            longitud_km=l.longitud_km,
            capacidad_mva=l.capacidad_mva,
            edad_anios=max(0.5, edad),
            propietario=l.propietario,
            zona=l.zona,
            capa_uso=capa,
            temperatura_media_c=round(RNG.normal(16, 2.5), 2),
            viento_promedio_ms=round(abs(RNG.normal(5.5, 1.8)), 2),
            salinidad_alta=int(l.zona in ("Valparaiso", "Valparaiso-RM")),
        ))
    return pd.DataFrame(filas)


# ---------------------------------------------------------------------------
# Persistencia
# ---------------------------------------------------------------------------
def main() -> None:
    base = Path(__file__).resolve().parent.parent / "data"
    base.mkdir(parents=True, exist_ok=True)

    red = {
        "buses": [asdict(b) for b in BARRAS],
        "lineas": [asdict(l) for l in LINEAS],
        "generadores": [asdict(g) for g in GENERADORES],
        "cargas": [asdict(c) for c in CARGAS],
        "base_mva": 100,
        "metadata": {
            "fuente": "sintetico calibrado al SEN central Chile",
            "kv_dominante": 220,
            "fecha_origen": "2026-01-01",
            "sustitucion_datos_reales": "http://www.coordinador.cl (Open Data)",
            "semilla": SEED,
        },
    }
    with open(base / "red.json", "w", encoding="utf-8") as f:
        json.dump(red, f, ensure_ascii=False, indent=2)

    fecha_inicio = datetime(2024, 1, 1)
    prog, forz = generar_historico_mantenimientos(fecha_inicio, n_anios=5)
    prog.to_csv(base / "historico_programado.csv", index=False, encoding="utf-8")
    forz.to_csv(base / "historico_forzado.csv", index=False, encoding="utf-8")

    demanda_df = generar_demanda_horaria(datetime(2026, 1, 6), n_semanas=12)
    gen_df = generar_generacion_horaria(datetime(2026, 1, 6), n_semanas=12)
    demanda_df.to_csv(base / "demanda_horaria.csv", index=False, encoding="utf-8")
    gen_df.to_csv(base / "generacion_horaria.csv", index=False, encoding="utf-8")

    feat = generar_features_ml()
    feat.to_csv(base / "features_elementos.csv", index=False, encoding="utf-8")

    print(f"[OK] red.json              : {len(LINEAS)} lineas, {len(BARRAS)} barras, {len(GENERADORES)} gens")
    print(f"[OK] historico_programado  : {len(prog)} registros")
    print(f"[OK] historico_forzado     : {len(forz)} registros")
    print(f"[OK] demanda_horaria       : {len(demanda_df)} filas (12 sem)")
    print(f"[OK] generacion_horaria    : {len(gen_df)} filas (12 sem)")
    print(f"[OK] features_elementos    : {len(feat)} lineas")


if __name__ == "__main__":
    main()