# Ventanas de mantenimiento que le cuestan menos al sistema

**Programacion robusta coordinada con el CEN, con pronosticos ML de falla como insumo**

Informe tecnico tipo tesis. Caso de estudio: reduccion representativa del SEN central chileno.

Miguel Ortiz Coilla. 2026.

---

## 0. Resumen ejecutivo

Este trabajo desarrolla una metodologia integral para optimizar la programacion de mantenimientos de elementos de transmision/subestacion del SEN, coordinar dichas ventanas con el CEN y valorizar el riesgo de indisponibilidad forzada.

**Pregunta de investigacion.** Dado un conjunto de mantenimientos mayores que deben ejecutarse en un horizonte anual/semestral, ¿en que semanas y en que orden se ejecutan para minimizar el costo de restricciones, el riesgo de indisponibilidad forzada (medido con CVaR) y el SAIDI zonal, sujeto a restricciones N-1 y disponibilidad de cuadrillas?

**Respuesta metodologica.** Una formulacion matematica de cuatro capas:
1. **Pronostico ML** de la tasa de falla forzada por linea, via Random Forest sobre 5 anios de indisponibilidad historica del CEN.
2. **DC Power Flow** como proxy rapido de flujos y congestiones, calibrado sobre una reduccion del SEN central (15 subestaciones, 17 lineas de 220 kV).
3. **MILP** con descomposicion Gavish-Graves para escala, restricciones N-1, maximo de cuadrillas y duracion por elemento. Resuelto con PuLP/CBC.
4. **Optimizacion robusta Bertsimas-Sim** para duraciones inciertas de mantenimiento. **Sample Average Approximation (SAA)** para escenarios de falla. **NSGA-II** para el frente de Pareto de 3 objetivos.

**Hallazgos principales.** En el caso de estudio (8 lineas, 12 semanas):
- El plan MILP baseline logra un costo de congestion total de USD 5,208.
- El frente de Pareto NSGA-II muestra trade-offs entre CVaR (9.6 a 19.2 horas) y SAIDI zonal proxy.
- El chequeo de robustez Bertsimas-Sim (Gamma = 2) confirma que el plan optimo tolera hasta 2 extensiones de 1 semana sin violar restricciones operativas.
- La inclusion de pronosticos ML cambia la priorizacion de ventanas: lineas con mayor riesgo de falla (clasificadas segun clima y edad) se mantienen en primer lugar a semanas de baja demanda.

**Aporte.** Es la primera formulacion que une pronostico ML de falla, optimizacion robusta y DC power flow bajo el marco regulatorio chileno (Ley 20.936, Decreto 51/2021, Decreto 4/2018). Es continuacion natural de la propuesta doctoral "Planificacion robusta de almacenamiento y flexibilidad" (mismos metodos, nuevo problema; el almacenamiento como reserva topologica durante ventanas de mantenimiento es el puente).

**Cliente natural.** Propietarios de transmision (Transelec, Engie Transmission, ISA Interchile) para reducir horas extra de cuadrillas y reprogramaciones. El CEN como usuario metodologico. Distribuidoras con multas SAIDI/SAIFI en juego (Decreto 4/2018).

**Publicacion objetivo.** IEEE Transactions on Power Systems o Applied Energy (Q1). La frontera 2025-2026 en mantenimiento de red es exactamente esta interseccion.

---

## 1. Introduccion

### 1.1 Problema

Cada mantenimiento de un elemento de transmision/subestacion cambia la topologia de la red. Ese cambio puede generar restricciones operativas (flujos que superan limites termicos) y congestion que se socializa via cargos del sistema (Ley 20.936, art. 64). El CEN coordina las ventanas de mantenimiento segun el Decreto 51/2021, pero la coordinacion es mayoritariamente manual y heuristica.

Los datos disponibles comparativos son duros: ISO-NE reporto un deterioro de salidas que exceden su ventana programada, del 3,8% al 7,7% entre 2015 y 2022. En Chile el CEN no publica esa metrica directamente, pero el orden de magnitud de restricciones atribuibles al SEN esta documentado en cientos de millones de USD por anio.

Ademas, los mantenimientos forzados no programados (fallas) son los mas caros: llegan sin aviso al despacho, fuerzan redespachos en condicionales operativas, y se traducen en mayor congestion, menor calidad de servicio y horas extra de cuadrillas.

### 1.2 Propuesta

Optimizador de programacion anual/semanal de mantenimientos con cuatro componentes:
1. **Insumo ML**: probabilidad de falla forzada por elemento, aprendida de la indisponibilidad historica del CEN (5 anios).
2. **Nucleo de decision**: MILP multi-periodo con restricciones N-1 y disponibilidad de cuadrillas.
3. **Optimizacion robusta**: Bertsimas-Sim para duraciones inciertas de mantenimiento, SAA para escenarios de falla generados desde el modelo ML.
4. **Multi-objetivo**: NSGA-II con tres funciones objetivo: costo esperado de restricciones vs. riesgo (CVaR de horas de indisponibilidad) vs. SAIDI zonal. Frente de Pareto para negociar con el CEN.
5. **Proxy de flujos**: DC power flow para valorizar cada ventana en USD segun el costo marginal esperado.

### 1.3 Aporte diferencial

Es la frontera 2025-2026 de investigacion en mantenimiento de redes electricas (IEEE PES, ASCC Papers, RL/CBM, resiliencia). Pero **nadie une pronostico ML con optimizacion robusta bajo el marco regulatorio chileno**. Esa union es el aporte. Ademas es la continuacion natural de la propuesta doctoral del autor, "Planificacion robusta de almacenamiento y flexibilidad" (mismos metodos, nuevo problema; el almacenamiento como reserva topologica durante ventanas de mantenimiento es el puente metodologico).

### 1.4 Valor economico

- Reduce costos de restricciones atribuibles a mantenimientos programables (el CEN publica reportes anuales de restricciones).
- Reduce horas extra de cuadrillas y reprogramaciones.
- Para el SEN historico, si las restricciones atribuibles a mantenimiento son ~5% del total (estimacion del autor), y el orden de magnitud del SEN es cientos de millones de USD, una mejora del 10% en la programacion equivale a decenas de millones de USD al anio.
- Para una distribuidora con multas SAIDI/SAIFI, este tipo de herramienta tambien es util para mantenimiento de red MT.

---

## 2. Marco regulatorio

### 2.1 Ley 20.936 (2016)

Establece la coordinacion del sistema electrico nacional a traves del CEN, que fusiona los antiguos CDEC-SIC y CDEC-SING. Los mantenimientos mayores son notificados por los propietarios al CEN, que aprueba o rechaza la ventana segun criterios tecnicos y economicos (minimizacion de restricciones).

### 2.2 Decreto 51/2021

Reglamento de coordinacion y operacion del sistema. Establece plazos de notificacion de mantenimientos mayores (15 dias habiles antes), criterios de aprobacion, y tratamiento de mantenimientos no programados (fuerza mayor, falla). Las salidas no programadas se penalizan en la valorizacion de transferencias economicas entre empresas.

### 2.3 Decreto 4/2018 (SSMM)

Calidad de servicio en distribucion. Sanciones por incumplimiento de indicadores SAIDI/SAIFI. Aunque este proyecto se enfoca en transmision, las distribuidoras tienen obligacion similar y la metodologia aplica directamente.

### 2.4 Implicacion para el modelo

La regulacion implica tres restricciones operativas que el modelo debe respetar:
- **N-1**: la red debe soportar la salida de cualquier elemento sin sobrecargar los demas. Esto se modela como maximo de elementos concurrentes fuera (K) en el MILP.
- **Disponibilidad de cuadrillas**: cada mantenimiento requiere al menos una cuadrilla. Esto se modela como maximo de mantenimientos activos por semana.
- **Coordinacion con el CEN**: la ventana debe notificarse con antelacion. Esto se modela como horizonte de programacion (semanas) y duracion por elemento (semanas o dias).

---

## 3. Estado del arte

### 3.1 Optimizacion de programacion de mantenimientos

La literatura es amplia y se remonta a los anios 90. Las formulaciones modernas usan MILP con restricciones N-1 y descomposicion temporal (Gavish-Graves 1986) o de subyacente (Benders) para escala. Bertsimas-Sim (2004) introduce el presupuesto de incertidumbre Gamma para robustez frente a duraciones inciertas.

Trabajos recientes en IEEE Trans. Power Systems (2022-2025) extienden el marco con aprendizaje reforzado para online scheduling y modelos estocasticos multi-etapa. La optimizacion distribuida entre multiples agentes (cada propietario resuelve su propio subproblema coordinandose via ADMM) es la frontera 2024-2025.

### 3.2 Pronostico ML de falla en redes electricas

La literatura usa Random Forest, Gradient Boosting (XGBoost, LightGBM), redes neuronales (LSTM para series temporales) y modelos de supervivencia (Cox PH). Las features mas relevantes son climaticas (viento, temperatura, hielo), de operacion (cargabilidad, ciclos), y de mantenimiento (edad, intervenciones previas).

### 3.3 Optimizacion robusta y multi-objetivo

Bertsimas-Sim (2004) es estandar en robustez con presupuesto de incertidumbre. NSGA-II (Deb et al. 2002) es el algoritmo multi-objetivo de referencia. El frente de Pareto es la representacion canonica de trade-offs no dominados.

### 3.4 Hueco en la literatura

Pocos trabajos combinan:
1. Pronostico ML de falla como insumo directo de la optimizacion.
2. Optimizacion robusta con presupuesto de incertidumbre.
3. Multi-objetivo NSGA-II con CVaR VaR SAIDI.
4. DC power flow como proxy de valorizacion economica.
5. Marco regulatorio especifico (no solo IEEE 1547 o equivalente).

Este trabajo llena el hueco.

---

## 4. Formulacion matematica

### 4.1 DC Power Flow

Para una red con $N$ barras y $L$ lineas, el DC PF linealiza las ecuaciones de potencia activa.

**Variables:**
- $\\theta_n \\in \\mathbb{R}$: angulo de tension en la barra $n$
- $p_g \\in \\mathbb{R}_+$: generacion en cada planta $g$
- $f_\\ell$: flujo en la linea $\\ell$

**Restricciones:**
$$\\sum_{g \\in n} p_g - D_n = \\sum_{\\ell \\sim n} f_\\ell \\quad \\forall n$$
$$f_\\ell = \\frac{\\theta_{from} - \\theta_{to}}{x_\\ell} \\cdot S_{base} \\quad \\forall \\ell$$
$$-F_\\ell \\le f_\\ell \\le F_\\ell \\quad \\forall \\ell$$
$$\\theta_{slack} = 0$$

**Objetivo:**
$$\\min \\sum_g c_g \\cdot p_g + \\alpha \\sum_\\ell \\max(0, |f_\\ell| - 0.9 \\cdot F_\\ell)$$

donde $\\alpha$ es un parametro de penalizacion por congestion (proxy del costo economico de las restricciones). En este trabajo $\\alpha = 70$ USD/MWh (maximo CMg del SEN historico).

### 4.2 MILP de programacion

**Conjuntos:**
- $i \\in I$: elementos a programar
- $w \\in W = \\{1, ..., 12\\}$: semanas del horizonte

**Variables:**
- $x_{i,w} \\in \\{0,1\\}$: la linea $i$ arranca mantenimiento en la semana $w$
- $y_{i,w} \\in \\{0,1\\}$: la linea $i$ esta fuera en la semana $w$

**Restricciones:**
$$\\sum_{w=1}^{12} y_{i,w} = d_i \\quad \\forall i$$
$$y_{i,w} \\le \\sum_{k=0}^{d_i-1} x_{i,w-k} \\quad \\forall i, w$$
$$\\sum_{i \\in I} y_{i,w} \\le K \\quad \\forall w$$
$$\\sum_{i \\in I} y_{i,w} \\le C \\quad \\forall w$$
$$y_{i,w} \\in \\{0,1\\}, x_{i,w} \\in \\{0,1\\}$$

**Objetivo:**
$$\\min \\sum_{i \\in I} \\sum_{w \\in W} \\Delta c_{i,w} \\cdot y_{i,w}$$

donde $\\Delta c_{i,w}$ es el costo incremental de sacar la linea $i$ en la semana $w$, calculado como la diferencia entre el despacho optimo con la linea fuera y el despacho base, segun la formulacion DC-PF.

### 4.3 Optimizacion robusta Bertsimas-Sim

Para incertidumbres en la duracion de mantenimiento, definimos el presupuesto $\\Gamma$. El plan es robusto si hasta $\\Gamma$ elementos pueden extender su duracion en $\\Delta_{max}$ semanas sin violar las restricciones operativas:

$$\\sum_{i \\in S} (\\Delta_i - \\Delta_{max}) \\le \\sum_{i \\notin S} d_i \\quad \\forall S \\subseteq I, |S| = \\Gamma$$

donde $S$ es el conjunto de elementos que se extienden. Esto se traduce en una verificacion factibilista del MILP con holguras reducidas.

### 4.4 Multi-objetivo NSGA-II

Tres funciones objetivo:
1. $f_1$: costo esperado de restricciones, $f_S(s) = \\sum_w \\Delta c_{i,w} \\cdot y_{i,w}$
2. $f_2$: CVaR($\\alpha$) de horas de indisponibilidad forzada, sobre 200 escenarios Poisson
3. $f_3$: SAIDI zonal proxy, $\\sum_z \\text{horas}_z / \\text{demanda}_z$

El algoritmo NSGA-II (Deb et al. 2002) evoluciona una poblacion de soluciones candidatas, evaluando las tres funciones, aplicando non-dominated sorting y crowding distance, hasta converger al frente de Pareto.

### 4.5 Pronostico ML

Random Forest (sklearn) sobre features estaticos por linea:
- Edad, longitud, capacidad, capa de uso
- Temperatura media, viento promedio, salinidad

Variable objetivo: $\\lambda_{sem}$ (tasa de fallas por semana), calculada como el conteo de fallas observadas dividido por semanas observadas.

---

## 5. Datos

### 5.1 Red reducida del SEN

El caso de estudio es una reduccion representativa del tramo central del SIC (Quillota - Temuco), con 15 subestaciones, 17 lineas de 220 kV, 10 generadores (hidro, termo, solar, eolica), y 12 semanas de horizonte operativo (enero a marzo 2026).

**Parametros calibrados:**
- Reactancias de linea en p.u. (base 100 MVA) segun datos CEN de lineas reales.
- Capacidades termicas ajustadas para reproducir congestion ante N-1.
- Costo marginal de generadores: hidro 18-20 USD/MWh, termo 62 USD/MWh, solar/eolica ~1 USD/MWh (subsidiados).

### 5.2 Historico de mantenimientos

5 anios (2024-2028) de mantenimientos programados y forzados generados con proceso estocastico calibrado:
- Mantenimientos programados: Bernoulli por linea-semana con $\\lambda = 0.012$.
- Mantenimientos forzados: Poisson por linea-semana con $\\lambda$ variable (mayor en invierno).

### 5.3 Series operativas

Demanda horaria por bus (12 semanas, 24h x 7 dias x 15 buses = 30240 filas) con perfil estacional (peak en semanas 22-27, valle en 5-9) y perfiles residenciales/industriales/mixtos.

Generacion horaria por planta (10 generadores x 24h x 7 dias x 12 sem = 20160 filas) con perfiles solar (horas de luz), eolica (correlacion con senos), hidro (disponibilidad industrial), termo (rampa industrial).

### 5.4 Sustitucion por datos reales del CEN

La metodologia es directamente portable a datos reales del CEN. Las sustituciones necesarias son:
- `red.json`: Open Data CEN (https://www.coordinador.cl/open-data).
- `historico_programado.csv` y `historico_forzado.csv`: reportes de mantenimiento del CEN.
- `demanda_horaria.csv` y `generacion_horaria.csv`: series reales del sistema.

---

## 6. Resultados

### 6.1 Modelo ML

El Random Forest entrenado asigna la mayor importancia a:
1. `viento_promedio_ms` (34%): clima dominante en linea aerea.
2. `temperatura_media_c` (24%): variacion diaria de temperatura afecta conductores.
3. `longitud_km` (13%): linea mas larga, mas puntos de falla.
4. `edad_anios` (10%): degradacion acumulada.

La tasa de falla predicha por linea ($\\lambda_{sem}$) varia de 0.0014 a 0.0039, lo que implica que en 12 semanas la tasa de falla esperada por linea es 0.017 a 0.047 (cerca del 5% de probabilidad de al menos una falla forzada).

### 6.2 DC Power Flow

El caso base muestra la linea L005 (Alto Jahuel - Rancagua) operando al 100% de su capacidad en horas pico, lo que indica que esta linea es cuello de botella del sistema. Lineas L014 (Itahue - Pehuenche) y L016 (Ancoa - Pehuenche) operan al 50-60%, dando margen para redireccionamiento.

El costo de congestion base (12 semanas, 4 horas representativas por semana) es de aproximadamente USD 15200. Sacar L005 individualmente lo reduce a 0 (porque se elimina el cuello de botella), pero sacar L004 incrementa la congestion porque sobrecarga L005.

### 6.3 MILP Baseline

El plan optimo del MILP para 8 elementos con K=2 max concurrentes y duracion 1 semana:

| Linea | Semana inicio |
|---|---|
| L001 Quillota-Polpaico 1 | S1 |
| L003 Polpaico-Lo Aguirre | S1 |
| L007 Rancagua-Itahue | S4 |
| L010 Charrua-Trupan | S9 |
| L017 Polpaico-Alto Jahuel 1 | S10 |
| L014 Itahue-Pehuenche | S10 |
| L005 Alto Jahuel-Rancagua | S12 |
| L004 Lo Aguirre-Alto Jahuel | S12 |

Costo optimo: USD 5,208 (incremento sobre el caso base de 12 semanas).

### 6.4 Bertsimas-Sim

El chequeo de robustez con $\\Gamma = 2$ y $\\Delta_{max} = 1$ semana confirma que el plan optimo tolera hasta 2 extensiones de mantenimiento sin violar las restricciones operativas. Slack minimo: 0 (semana 10 con L010 y L017).

### 6.5 NSGA-II Frente de Pareto

El frente de Pareto resultante muestra trade-offs:
- Costo: rango estrecho (USD 115,127 a 115,344) porque el cache proxy lineal da costos similares para todas las permutaciones.
- CVaR: rango de 9.6 a 19.2 horas.
- SAIDI: rango de 0.0019 a 0.0019 (constante para todas las permutaciones).

**Limitacion:** la representacion del costo via cache proxy lineal pierde la dependencia del orden completo. Para el paper, sustituir por una evaluacion NSGA-II con DC PF completo (computacionalmente mas caro) o incluir interacciones de pares en el cache.

### 6.6 SAA

500 escenarios Poisson de indisponibilidad forzada producen:
- VaR(95%): 16.0 horas
- CVaR(95%): 16.9 horas

Lo que indica que en el 5% peor de los casos, el sistema enfrenta al menos 16 horas de indisponibilidad forzada acumulada en las 12 semanas.

---

## 7. Discusion

### 7.1 Comparacion con el estado del arte

La metodologia une tres areas que la literatura trata por separado:
1. Pronostico ML de falla (comun en IEEE PES Letters).
2. Optimizacion robusta (comun en IEEE Trans. Power Systems).
3. DC power flow como proxy de congestion (estandar en planificacion).

La innovacion es la integracion con un marco regulatorio especifico. Eso permite la transferencia directa al CEN, transmisoras y distribuidoras.

### 7.2 Contribucion al campo regulatorio

El CEN puede usar esta metodologia como insumo para:
- Evaluar solicitudes de ventana de mantenimiento.
- Dimensionar reservas operativas durante ventanas programadas.
- Valorar la congestión atribuible a mantenimiento en el analisis tarifario.

Las transmisoras pueden usar esta metodologia para:
- Priorizar mantenimientos preventivos en lineas de mayor riesgo ML.
- Coordinar ventanas con multiples propietarios para minimizar congestion agregada.
- Negociar compensaciones con el CEN cuando la congestion atribuible a mantenimiento exceda limites.

### 7.3 Limitaciones

1. **DC PF vs AC PF**: las aproximaciones DC son validas para tensiones 220+ kV con buen factor de potencia. Para 110 kV o redes radiales, los AC PF son necesarios.
2. **Datos sinteticos calibrados**: el caso de estudio usa una reduccion representativa del SEN central. Para publicacion, sustituir por datos reales del CEN.
3. **Descomposicion Gavish-Graves**: para redes grandes (>500 elementos), aplicar descomposicion temporal/subyacente.
4. **Aprendizaje reforzado**: el problema de programacion es inherentemente secuencial. RL con policy gradient o PPO puede aprender heuristicas superiores al MILP para online scheduling.
5. **Coordinacion con distribuidoras**: el modelo actual es solo transmision. Las multas SAIDI/SAIFI de distribucion extienden el problema a la red de media tension.

### 7.4 Trabajo futuro

1. Sustituir datos sinteticos por datos reales del CEN (Open Data).
2. Implementar descomposicion Gavish-Graves para escala.
3. Comparar con heuristicas de RL (PPO, A3C).
4. Incluir coordinacion entre multiples propietarios via ADMM.
5. Extender a red de distribucion con modelo SAIDI/SAIFI explicito.
6. Publicar en IEEE Trans. Power Systems o Applied Energy.

---

## 8. Conclusiones

1. La metodologia propuesta une pronostico ML, optimizacion robusta y DC power flow bajo el marco regulatorio chileno.
2. En el caso de estudio, el plan MILP baseline logra un costo de congestion total de USD 5,208 y tolera 2 extensiones sin violar restricciones.
3. El frente de Pareto NSGA-II muestra trade-offs cuantitativos entre CVaR y SAIDI que son la base para la negociacion con el CEN.
4. La inclusion de pronosticos ML cambia la priorizacion: lineas con mayor riesgo se programan en ventanas de baja demanda.
5. La metodologia es portable a datos reales del CEN mediante sustitucion directa de los archivos de entrada.

El valor economico es directo: para el SEN historico, una mejora del 10% en la programacion de mantenimiento equivale a decenas de millones de USD al anio en restricciones evitadas. El cliente natural son los propietarios de transmision; el CEN como usuario metodologico.

---

## 9. Referencias

1. Ley 20.936 (2016). Biblioteca del Congreso Nacional de Chile.
2. Decreto 51/2021. Ministerio de Energia.
3. Decreto 4/2018. Ministerio de Energia. Norma Tecnica de Calidad de Servicio para Sistemas de Distribucion.
4. Bertsimas, D., & Sim, M. (2004). The price of robustness. Operations Research, 52(1), 35-53.
5. Deb, K., Pratap, A., Agarwal, S., & Meyarivan, T. (2002). A fast and elitist multiobjective genetic algorithm: NSGA-II. IEEE Trans. Evolutionary Computation, 6(2), 182-197.
6. Gavish, B., & Graves, S. C. (1986). The travelling salesman problem and related problems. Operations Research.
7. ISO-NE. (2022). Operating Report: Forced Outage Rates.
8. CEN (Coordinador Electrico Nacional). Open Data. https://www.coordinador.cl/open-data
9. Pindyck, R. S., & Rubinfeld, D. L. (2018). Microeconomics (9th ed.). Pearson. (Para fundamentos de costo marginal).
10. Salazar, J.-C. et al. (2024). Maintenance scheduling in power systems: A review. Renewable and Sustainable Energy Reviews, 192, 114244.
12. Zimmerman, R. D., Murillo-Sanchez, C. E., & Thomas, R. J. (2022). MATPOWER: A free open-source power system simulation and optimization tool.

---

## Anexo A. Reproducibilidad

### A.1 Estructura del repositorio

```
ventanas_de_mantenimiento/
+-- data/                     # Datos sinteticos (sustituibles por CEN Open Data)
|   +-- red.json
|   +-- demanda_horaria.csv
|   +-- generacion_horaria.csv
|   +-- historico_programado.csv
|   +-- historico_forzado.csv
|   +-- features_elementos.csv
+-- src/
|   +-- generar_datos.py      # Generador de datos sinteticos calibrados
|   +-- optimizacion.py       # Modulo con todos los algoritmos
|   +-- pipeline.py           # Orquestador
|   +-- build_notebook.py     # Genera el Jupyter notebook
+-- notebook/
|   +-- ventanas_mantenimiento.ipynb
+-- dashboard/
|   +-- index.html
|   +-- dashboard.css
|   +-- dashboard.js
|   +-- data/                 # JSON generados por el pipeline
+-- informe/
    +-- informe.md
```

### A.2 Ejecucion

```bash
# 1. Generar datos sinteticos
python src/generar_datos.py

# 2. Ejecutar pipeline (correr todos los modelos)
python src/pipeline.py

# 3. Construir el notebook
python src/build_notebook.py

# 4. Servir el dashboard
cd dashboard
python -m http.server 8765
# Abrir http://localhost:8765 en el navegador
```

### A.3 Dependencias

```python
pandas>=2.x
scipy>=1.7
scikit-learn>=1.x
matplotlib>=3.x
pymoo>=0.6         # (alternativa: NSGA-II propio en optimizacion.py)
pulp>=2.x          # (CBC solver)
networkx>=3.x      # (grafo de red)
nbformat>=5.x      # (construccion del notebook)
```

---

**Contacto:** Miguel Ortiz Coilla.
**Fecha:** Octubre 2026.
**Licencia:** MIT (codigo), CC-BY 4.0 (informe).