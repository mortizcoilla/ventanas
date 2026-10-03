/* ============================================================
   Ventanas de Mantenimiento — dashboard.js (D3 v7)
   Guía visual editorial: papel, retícula milimétrica, escuadras.
   ============================================================ */
"use strict";

const DATA = "data/";

/* ---------- utilidades ---------- */
const $ = (s) => document.querySelector(s);

const nf0 = new Intl.NumberFormat("es-CL", { maximumFractionDigits: 0 });
const nf1 = new Intl.NumberFormat("es-CL", { maximumFractionDigits: 1 });
const nf2 = new Intl.NumberFormat("es-CL", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const usd = (n) => "USD " + nf0.format(Math.round(n));
const pct = (x, d = 2) => (x * 100).toFixed(d).replace(".", ",") + "%";

const INK = "#1E2A44", INK_SOFT = "#46536F", INK_FAINT = "#7C86A0";
const ORANGE = "#D96C2C", ORANGE_DEEP = "#B04F16";
const GREEN = "#3E7C4F", GREEN_DEEP = "#2C5E3B";
const RED = "#B3403A";
const PAPER = "#F5EEDC";

let _uid = 0;
function uid(p) { return p + (++_uid); }

async function loadJSON(name) {
  const r = await fetch(DATA + name);
  if (!r.ok) throw new Error(`No se pudo cargar ${name}`);
  return r.json();
}

/* ---------- tooltip ---------- */
const tip = d3.select("body").append("div").attr("class", "tip");
function tipShow(html, ev) {
  tip.html(html).classed("on", true);
  tipMove(ev);
}
function tipMove(ev) {
  const node = tip.node();
  const w = node.offsetWidth, h = node.offsetHeight;
  let x = ev.pageX + 16, y = ev.pageY - 14;
  if (x + w > window.innerWidth - 10) x = ev.pageX - w - 16;
  if (y + h > window.innerHeight - 10) y = ev.pageY - h - 14;
  if (y < 6) y = 6;
  tip.style("left", x + "px").style("top", y + "px");
}
function tipHide() { tip.classed("on", false); }

/* ---------- marco de gráfico con retícula mm + escuadras ---------- */
function plotFrame(sel, W, H, M = { l: 52, r: 16, t: 18, b: 40 }) {
  const frame = sel.append("div").attr("class", "plot rv");
  ["tl", "tr", "bl", "br"].forEach((c) => frame.append("span").attr("class", "corner " + c));
  const svg = frame.append("svg").attr("viewBox", `0 0 ${W} ${H}`);
  const pid = uid("mm"), pid5 = uid("mm5");
  const defs = svg.append("defs");
  const p1 = defs.append("pattern").attr("id", pid).attr("width", 8).attr("height", 8)
    .attr("patternUnits", "userSpaceOnUse");
  p1.append("path").attr("d", "M8 0H0V8").attr("fill", "none")
    .attr("stroke", "rgba(30,42,68,0.05)").attr("stroke-width", 0.7);
  const p2 = defs.append("pattern").attr("id", pid5).attr("width", 40).attr("height", 40)
    .attr("patternUnits", "userSpaceOnUse");
  p2.append("path").attr("d", "M40 0H0V40").attr("fill", "none")
    .attr("stroke", "rgba(30,42,68,0.09)").attr("stroke-width", 0.8);
  const area = { x: M.l, y: M.t, w: W - M.l - M.r, h: H - M.t - M.b };
  svg.append("rect").attr("x", area.x).attr("y", area.y)
    .attr("width", area.w).attr("height", area.h)
    .attr("fill", `url(#${pid})`);
  svg.append("rect").attr("x", area.x).attr("y", area.y)
    .attr("width", area.w).attr("height", area.h)
    .attr("fill", `url(#${pid5})`);
  const g = svg.append("g").attr("transform", `translate(${M.l},${M.t})`);
  return { frame, svg, g, area, W, H, M };
}

function axisTitle(svg, frame, text, pos) {
  svg.append("text").attr("class", "axis-title").attr("text-anchor", pos.anchor || "middle")
    .attr("x", pos.x).attr("y", pos.y)
    .attr("transform", pos.rot ? `rotate(-90 ${pos.x} ${pos.y})` : null)
    .text(text);
}

/* ---------- celdas de lectura ---------- */
function readoutCells(sel, cells) {
  sel.selectAll(".cell").data(cells).join("div").attr("class", "cell")
    .html((d) => `<span class="cell-k">${d.k}</span><span class="cell-v ${d.cls || ""}">${d.v}</span>`);
}

/* ============================================================
   § 00 — HERO
   ============================================================ */
function renderHero(S) {
  const cs = S.costos_semanales;
  const cal = S.calendario;
  const semanas = d3.range(1, 13).map((w) => {
    const c = cs[String(w)] || {};
    return {
      w,
      dem: c.demanda_media_mw || 0,
      inc: c.incremental_usd || 0,
      fuera: (c.lineas_fuera && c.lineas_fuera !== "-") ? c.lineas_fuera.split(",") : [],
      total: c.congestion_usd || 0,
    };
  });

  /* tira animada */
  const strip = d3.select("#hero-strip");
  function setStrip(d) {
    $("#hs-sem").textContent = "S" + d.w;
    $("#hs-dem").innerHTML = nf0.format(d.dem) + " <small>MW</small>";
    $("#hs-fuera").innerHTML = d.fuera.length ? d.fuera.join("·") : "—";
    $("#hs-inc").innerHTML = (d.inc > 0.5 ? "+" : "") + nf0.format(d.inc) + " <small>USD</small>";
    $("#hs-fuera").className = "cell-v " + (d.fuera.length ? "warn" : "");
  }

  const W = 520, H = 300, M = { l: 56, r: 14, t: 16, b: 32 };
  const f = plotFrame(d3.select("#hero-plot"), W, H, M);
  const x = d3.scaleLinear().domain([0.5, 12.5]).range([0, f.area.w]);
  const y = d3.scaleLinear().domain([0, d3.max(semanas, (d) => d.dem) * 1.12]).nice().range([f.area.h, 0]);

  /* bandas de mantenimiento */
  const bands = f.g.selectAll("rect.mband").data(semanas.filter((d) => d.fuera.length)).join("rect")
    .attr("class", "mband")
    .attr("x", (d) => x(d.w - 0.5) + 1).attr("width", x(1) - x(0) - 2)
    .attr("y", 0).attr("height", f.area.h)
    .attr("fill", "rgba(217,108,44,0.17)")
    .attr("stroke", "rgba(176,79,22,0.55)").attr("stroke-dasharray", "3 3");

  bands.append("title").remove();

  /* ejes */
  f.g.append("g").attr("class", "axis").attr("transform", `translate(0,${f.area.h})`)
    .call(d3.axisBottom(x).tickValues(d3.range(1, 13)).tickFormat((d) => "S" + d).tickSize(3));
  f.g.append("g").attr("class", "axis")
    .call(d3.axisLeft(y).ticks(5).tickFormat((d) => nf0.format(d)).tickSize(3));

  /* curva de demanda */
  const line = d3.line().x((d) => x(d.w)).y((d) => y(d.dem)).curve(d3.curveCatmullRom.alpha(0.6));
  f.g.append("path").datum(semanas).attr("class", "dem-line")
    .attr("d", line).attr("fill", "none").attr("stroke", INK).attr("stroke-width", 2.2);
  const dots = f.g.selectAll("circle.hdot").data(semanas).join("circle")
    .attr("class", "hdot").attr("cx", (d) => x(d.w)).attr("cy", (d) => y(d.dem))
    .attr("r", 3.2).attr("fill", PAPER).attr("stroke", INK).attr("stroke-width", 1.6)
    .style("cursor", "crosshair")
    .on("mousemove", (ev, d) => tipShow(
      `<b>Semana ${d.w}</b><br>Demanda media: ${nf0.format(d.dem)} MW<br>` +
      `Líneas fuera: ${d.fuera.length ? d.fuera.join(", ") : "—"}<br>` +
      `Congestión incr.: ${nf0.format(d.inc)} USD`, ev))
    .on("mouseleave", tipHide);

  /* barrido animado */
  const sweep = f.g.append("line").attr("class", "sweep")
    .attr("y1", -4).attr("y2", f.area.h)
    .attr("stroke", ORANGE_DEEP).attr("stroke-width", 1.8);
  const sweepDot = f.g.append("circle").attr("r", 4.5)
    .attr("fill", ORANGE).attr("stroke", PAPER).attr("stroke-width", 1.5);
  const P = 11000;
  setStrip(semanas[0]); // estado inicial sin esperar el primer frame
  d3.timer((elapsed) => {
    const p = (elapsed % P) / P;
    const px = x(0.5) + p * (x(12.5) - x(0.5));
    sweep.attr("x1", px).attr("x2", px);
    sweepDot.attr("cx", px).attr("cy", y(demAt(px)));
    const w = Math.min(12, Math.max(1, Math.round(x.invert(px))));
    const d = semanas[w - 1];
    setStrip(d);
    bands.attr("stroke-opacity", (b) => (b.w === w ? 1 : 0.45))
      .attr("fill-opacity", (b) => (b.w === w ? 0.24 : 0.13));
  });
  function demAt(px) {
    const w = x.invert(px);
    const i = Math.min(11, Math.max(0, Math.round(w) - 1));
    return semanas[i].dem;
  }

  /* readouts principales */
  const rob = S.escenarios.robustez;
  const met = S.escenarios.metricas;
  readoutCells(d3.select("#hero-readouts"), [
    { k: "Elementos en plan", v: S.resumen.elementos_objetivo.length },
    { k: "Líneas / SE 220 kV", v: S.resumen.n_lineas_total + " / " + S.resumen.n_buses },
    { k: "Horizonte", v: S.resumen.horizonte_semanas + " <small>sem</small>" },
    { k: "Costo MILP incr.", v: usd(S.resumen.costo_milp_incremental) },
    { k: "VaR(95%) horas", v: nf1.format(met.VaR) },
    { k: "CVaR(95%) horas", v: nf1.format(met.CVaR) },
    {
      k: "Robustez Γ=2", v: rob.gamma_max >= rob.gamma ? "Robusto" : "Γmáx " + rob.gamma_max,
      cls: rob.gamma_max >= rob.gamma ? "ok" : "bad",
    },
  ]);
}

/* ============================================================
   § 01 — RED (topología geográfica)
   ============================================================ */
function renderRed(S) {
  const red = S.red;
  const W = 560, H = 800, M = { l: 96, r: 40, t: 26, b: 26 };
  const f = plotFrame(d3.select("#red-plot"), W, H, M);

  const lats = red.nodos.map((n) => n.lat), lons = red.nodos.map((n) => n.lon);
  const x = d3.scaleLinear().domain([d3.min(lons) - 0.14, d3.max(lons) + 0.14]).range([0, f.area.w]);
  const y = d3.scaleLinear().domain([d3.min(lats) - 0.16, d3.max(lats) + 0.16]).range([f.area.h, 0]);

  const propColors = { Transelec: INK, Engie: GREEN, Enel: ORANGE };
  const propOf = (p) => propColors[p] || INK_SOFT;

  /* separadores de zona */
  const zonas = d3.rollups(red.nodos, (v) => d3.mean(v, (n) => n.lat), (n) => n.zona)
    .map(([z, lat]) => ({ z, lat })).sort((a, b) => b.lat - a.lat);
  const zonaG = f.g.append("g");
  zonas.forEach((z, i) => {
    zonaG.append("text").attr("x", -12).attr("y", y(z.lat))
      .attr("text-anchor", "end").attr("dominant-baseline", "middle")
      .attr("font-family", "JetBrains Mono, monospace").attr("font-size", "9.5px")
      .attr("fill", INK_FAINT).attr("letter-spacing", "0.08em")
      .text(z.z.toUpperCase());
    if (i > 0) zonaG.append("line")
      .attr("x1", -6).attr("x2", f.area.w).attr("y1", y(z.lat)).attr("y2", y(z.lat))
      .attr("stroke", "rgba(30,42,68,0.14)").attr("stroke-dasharray", "2 4");
  });

  let selected = null;

  /* líneas */
  const link = f.g.selectAll("line.netlink").data(red.aristas).join("line")
    .attr("class", "netlink")
    .attr("x1", (d) => x(red.nodos.find((n) => n.id === d.source).lon))
    .attr("y1", (d) => y(red.nodos.find((n) => n.id === d.source).lat))
    .attr("x2", (d) => x(red.nodos.find((n) => n.id === d.target).lon))
    .attr("y2", (d) => y(red.nodos.find((n) => n.id === d.target).lat))
    .attr("stroke", (d) => propOf(d.propietario))
    .attr("stroke-width", (d) => (d.objetivo ? 3.2 : 2))
    .attr("stroke-opacity", 0.85)
    .attr("stroke-dasharray", (d) => (d.objetivo ? "7 4" : null))
    .style("cursor", "pointer")
    .on("mousemove", (ev, d) => {
      d3.select(ev.currentTarget).attr("stroke-width", (d.objetivo ? 4.6 : 3.4));
      const enPlan = S.calendario[d.id];
      tipShow(
        `<b>${d.nombre}</b> (${d.id})<br>${d.kv} kV · ${nf0.format(d.capacidad_mva)} MVA · ${nf0.format(d.longitud_km)} km<br>` +
        `${d.propietario} · zona ${d.zona}<br>` +
        `λ falla: ${pct(d.lambda_sem, 3)}/sem<br>` +
        (d.objetivo
          ? `<b style="color:#F8B98A">En plan — semana ${enPlan ? enPlan.inicio : "?"}</b>`
          : "Sin mantenimiento en el horizonte"), ev);
    })
    .on("mouseleave", (ev, d) => {
      d3.select(ev.currentTarget).attr("stroke-width", (d.objetivo ? 3.2 : 2));
      tipHide();
    })
    .on("click", (ev, d) => {
      selected = selected === d.id ? null : d.id;
      updateSel();
      renderRedDetail(S, selected);
    });

  /* nodos */
  const node = f.g.selectAll("circle.senode").data(red.nodos).join("circle")
    .attr("class", "senode")
    .attr("cx", (d) => x(d.lon)).attr("cy", (d) => y(d.lat))
    .attr("r", (d) => (d.tipo === "generacion" ? 8 : 6.5))
    .attr("fill", (d) => (d.tipo === "generacion" ? GREEN : PAPER))
    .attr("stroke", INK).attr("stroke-width", 1.6)
    .style("cursor", "crosshair")
    .on("mousemove", (ev, d) => tipShow(
      `<b>${d.nombre}</b> (${d.id})<br>${d.zona} · ${d.kv} kV · ${d.tipo}`, ev))
    .on("mouseleave", tipHide);

  /* etiquetas */
  f.g.selectAll("text.nlabel").data(red.nodos).join("text")
    .attr("class", "nlabel").attr("font-family", "JetBrains Mono, monospace")
    .attr("font-size", "9.5px").attr("fill", INK_SOFT).attr("pointer-events", "none")
    .attr("x", (d) => x(d.lon) + 11)
    .attr("y", (d) => y(d.lat) + 3)
    .text((d) => d.nombre.replace(" 220", ""));

  function updateSel() {
    link.attr("stroke-opacity", (d) => (!selected || d.id === selected ||
      red.aristas.find((a) => a.id === selected)?.source === d.source) ? 0.85 : 0.18)
      .attr("stroke-width", (d) => (d.id === selected ? 4.8 : d.objetivo ? 3.2 : 2));
    node.attr("fill-opacity", 1);
  }

  /* leyenda */
  const props = [...new Set(red.aristas.map((a) => a.propietario))];
  const lg = d3.select("#red-legend");
  lg.html("");
  props.forEach((p) => {
    lg.append("div").attr("class", "lg-row")
      .html(`<span class="lg-swatch" style="border-color:${propOf(p)}"></span>${p}`);
  });
  lg.append("div").attr("class", "lg-row")
    .html(`<span class="lg-swatch dash" style="border-color:${INK}"></span>Línea en plan de mantenimiento`);
  lg.append("div").attr("class", "lg-row")
    .html(`<span class="lg-dot" style="background:${GREEN}"></span>Subestación generadora`);

  renderRedDetail(S, null);
}

function renderRedDetail(S, id) {
  const card = d3.select("#red-detail");
  if (!id) {
    card.html('<p class="detail-empty">Sin selección.<br>Haga clic en una línea.</p>');
    return;
  }
  const a = S.red.aristas.find((d) => d.id === id);
  const cal = S.calendario[id];
  card.html(`
    <p class="dc-title">${a.nombre}</p>
    <p class="dc-sub">${a.id} · ${a.zona}</p>
    <table>
      <tr><td>Tensión</td><td>${a.kv} kV</td></tr>
      <tr><td>Capacidad</td><td>${nf0.format(a.capacidad_mva)} MVA</td></tr>
      <tr><td>Longitud</td><td>${nf0.format(a.longitud_km)} km</td></tr>
      <tr><td>Propietario</td><td>${a.propietario}</td></tr>
      <tr><td>λ falla (ML)</td><td>${pct(a.lambda_sem, 3)}/sem</td></tr>
      <tr><td>En plan</td><td>${a.objetivo ? "Sí — semana " + (cal ? cal.inicio : "?") : "No"}</td></tr>
    </table>`);
}

/* ============================================================
   § 02 — CALENDARIO (Gantt + costos semanales vinculados)
   ============================================================ */
function renderCalendario(S) {
  const cal = S.calendario;
  const cs = S.costos_semanales;
  const semanas = d3.range(1, 13).map((w) => ({
    w,
    inc: cs[String(w)] ? cs[String(w)].incremental_usd : 0,
    fuera: cs[String(w)] && cs[String(w)].lineas_fuera !== "-"
      ? cs[String(w)].lineas_fuera.split(",") : [],
    dem: cs[String(w)] ? cs[String(w)].demanda_media_mw : 0,
  }));

  const lineas = Object.keys(cal).sort((a, b) => cal[a].inicio - cal[b].inicio);
  const rowH = 26, gap = 26, costH = 96;
  const W = 1020, H = 34 + lineas.length * rowH + gap + costH + 30;
  const M = { l: 178, r: 24, t: 30, b: 14 };
  const f = plotFrame(d3.select("#cal-plot"), W, H, M);
  const x = d3.scaleLinear().domain([0, 12]).range([0, f.area.w]);
  const colW = f.area.w / 12;

  /* encabezado de semanas */
  const head = f.g.append("g");
  semanas.forEach((s) => {
    head.append("text").attr("x", x(s.w - 0.5) + colW / 2).attr("y", -12)
      .attr("text-anchor", "middle").attr("font-family", "JetBrains Mono, monospace")
      .attr("font-size", "10px").attr("fill", INK_SOFT).text("S" + s.w);
  });

  /* filas */
  const yBand = d3.scaleBand().domain(lineas).range([0, lineas.length * rowH]).padding(0.18);

  lineas.forEach((l, i) => {
    if (i % 2 === 1) f.g.append("rect")
      .attr("x", 0).attr("y", yBand(l) - yBand.step() * 0.0)
      .attr("width", f.area.w).attr("height", yBand.step())
      .attr("fill", "rgba(30,42,68,0.035)");
  });

  /* etiquetas de fila */
  const lab = f.g.selectAll("text.rowlab").data(lineas).join("text")
    .attr("x", -10).attr("y", (l) => yBand(l) + yBand.bandwidth() / 2 + 3.5)
    .attr("text-anchor", "end").attr("font-family", "JetBrains Mono, monospace")
    .attr("font-size", "10px").attr("fill", INK_SOFT)
    .text((l) => {
      const a = S.red.aristas.find((r) => r.id === l);
      return l + " · " + (a ? a.nombre : "").replace(" 1", "").slice(0, 20);
    });

  /* barras del Gantt */
  const bars = f.g.selectAll("rect.gantt").data(lineas).join("rect")
    .attr("class", "gantt")
    .attr("x", (l) => x(cal[l].inicio - 0.5) + 1.5)
    .attr("y", (l) => yBand(l))
    .attr("width", colW - 3)
    .attr("height", (l) => yBand.bandwidth())
    .attr("rx", 2)
    .attr("fill", ORANGE).attr("fill-opacity", 0.9)
    .style("cursor", "pointer")
    .on("mousemove", (ev, l) => {
      const a = S.red.aristas.find((r) => r.id === l);
      tipShow(`<b>${a ? a.nombre : l}</b> (${l})<br>` +
        `Ventana: semana ${cal[l].inicio}<br>` +
        `λ falla: ${a ? pct(a.lambda_sem, 3) : "—"}/sem<br>` +
        `${a ? a.propietario : ""}`, ev);
    })
    .on("mouseleave", tipHide);

  /* eje de costos (incremental con signo: el proxy puede reducir congestión) */
  const costTop = lineas.length * rowH + gap;
  const maxInc = d3.max(semanas, (s) => Math.abs(s.inc)) || 1;
  const yCost = d3.scaleLinear()
    .domain([Math.min(0, -maxInc * 0.35), maxInc * 1.15]).range([costH, 0]);

  f.g.append("line").attr("x1", 0).attr("x2", f.area.w)
    .attr("y1", costTop).attr("y2", costTop)
    .attr("stroke", "rgba(30,42,68,0.25)");

  f.g.append("text").attr("x", 0).attr("y", costTop - costH - 6)
    .attr("font-family", "JetBrains Mono, monospace").attr("font-size", "9.5px")
    .attr("fill", INK_FAINT).text("COSTO INCREMENTAL DE CONGESTIÓN (USD, PROXY)");

  const zeroY = costTop + yCost(0);
  f.g.append("line").attr("x1", 0).attr("x2", f.area.w)
    .attr("y1", zeroY).attr("y2", zeroY)
    .attr("stroke", "rgba(30,42,68,0.3)");

  f.g.selectAll("rect.incbar").data(semanas).join("rect")
    .attr("class", "incbar")
    .attr("x", (s) => x(s.w - 0.5) + colW * 0.22)
    .attr("width", colW * 0.56)
    .attr("y", (s) => (s.inc >= 0 ? costTop + yCost(s.inc) : zeroY))
    .attr("height", (s) => Math.max(s.inc >= 0 ? zeroY - (costTop + yCost(s.inc)) : 0,
                                    s.inc < 0 ? (costTop + yCost(s.inc)) - zeroY : 0))
    .attr("fill", (s) => (s.inc >= 0 ? GREEN : RED))
    .attr("fill-opacity", 0.8)
    .attr("rx", 1.5);

  /* hover compartido por columna */
  const hl = f.g.append("rect").attr("class", "colhl")
    .attr("y", -20).attr("height", H - M.t - M.b + 20)
    .attr("width", colW)
    .attr("fill", "rgba(30,42,68,0.07)").attr("opacity", 0);

  const overlay = f.g.selectAll("rect.colzone").data(semanas).join("rect")
    .attr("class", "colzone")
    .attr("x", (s) => x(s.w - 0.5)).attr("width", colW)
    .attr("y", -20).attr("height", H - M.t - M.b + 20)
    .attr("fill", "transparent").style("cursor", "crosshair")
    .on("mousemove", (ev, s) => {
      hl.attr("x", x(s.w - 0.5)).attr("opacity", 1);
      const nombres = s.fuera.map((l) => {
        const a = S.red.aristas.find((r) => r.id === l);
        return a ? a.nombre : l;
      });
      tipShow(`<b>Semana ${s.w}</b><br>` +
        (s.fuera.length ? `Fuera: ${nombres.join(", ")}<br>` : "Sin mantenimientos<br>") +
        `Demanda media: ${nf0.format(s.dem)} MW<br>` +
        `Costo incremental: ${nf0.format(s.inc)} USD`, ev);
    })
    .on("mouseleave", () => { hl.attr("opacity", 0); tipHide(); });
}

/* ============================================================
   § 03 — MATRIZ DE COSTOS POR VENTANA
   ============================================================ */
function renderCostos(S) {
  const cv = S.costos_ventana;
  const objetivo = S.resumen.elementos_objetivo;
  const W = 900, H = 60 + objetivo.length * 44;
  const M = { l: 208, r: 118, t: 40, b: 44 };
  const f = plotFrame(d3.select("#costos-plot"), W, H, M);
  const weeks = d3.range(1, 13);
  const cellW = f.area.w / 12, cellH = Math.min(40, (f.area.h - 6) / objetivo.length);

  const val = (l, w) => cv[`${l},${w}`] ?? 0;
  const maxV = d3.max(objetivo, (l) => d3.max(weeks, (w) => val(l, w))) || 1;
  const color = d3.scaleSequential(d3.interpolateRgb("#FBF6E9", ORANGE_DEEP))
    .domain([0, maxV]);

  /* encabezado semanas */
  weeks.forEach((w) => {
    f.g.append("text").attr("x", (w - 0.5) * cellW).attr("y", -14)
      .attr("text-anchor", "middle").attr("font-family", "JetBrains Mono, monospace")
      .attr("font-size", "10px").attr("fill", INK_SOFT).text("S" + w);
  });

  objetivo.forEach((l, i) => {
    const y0 = i * (cellH + 5);
    const a = S.red.aristas.find((r) => r.id === l);
    f.g.append("text").attr("x", -10).attr("y", y0 + cellH / 2 + 3.5)
      .attr("text-anchor", "end").attr("font-family", "JetBrains Mono, monospace")
      .attr("font-size", "10px").attr("fill", INK_SOFT)
      .text(l + " · " + (a ? a.nombre : "").slice(0, 24));
    weeks.forEach((w) => {
      const v = val(l, w);
      const chosen = S.calendario[l] && S.calendario[l].inicio === w;
      f.g.append("rect")
        .attr("x", (w - 1) * cellW + 1.5).attr("y", y0)
        .attr("width", cellW - 3).attr("height", cellH)
        .attr("rx", 2)
        .attr("fill", color(v)).attr("stroke", chosen ? INK : "rgba(30,42,68,0.14)")
        .attr("stroke-width", chosen ? 2.6 : 1)
        .style("cursor", "crosshair")
        .on("mousemove", (ev) => tipShow(
          `<b>${l}</b> · semana ${w}<br>` +
          `Costo incremental: <b>${usd(v)}</b><br>` +
          (v === 0 ? "Sin impacto de congestión detectado" :
            v > 0.6 * maxV ? "Alto impacto — evitar semanas de punta" : "") +
          (chosen ? "<br><b style='color:#F8B98A'>◉ Ventana elegida por el MILP</b>" : ""), ev))
        .on("mouseleave", tipHide);
    });
    /* promedio a la derecha */
    const avg = cv[l] ?? 0;
    f.g.append("text").attr("x", f.area.w + 10).attr("y", y0 + cellH / 2 + 3.5)
      .attr("font-family", "JetBrains Mono, monospace").attr("font-size", "10px")
      .attr("fill", INK_FAINT).attr("text-anchor", "start")
      .text("⌀ " + nf0.format(avg));
  });

  f.g.append("text").attr("x", f.area.w + 10).attr("y", -14)
    .attr("font-family", "JetBrains Mono, monospace").attr("font-size", "9px")
    .attr("fill", INK_FAINT).text("PROM.");

  axisTitle(f.svg, f, "semana del horizonte", { x: M.l + f.area.w / 2, y: H - 12 });
}

/* ============================================================
   § 04 — FRENTE DE PARETO
   ============================================================ */
function renderPareto(S) {
  const pts = S.pareto;
  const W = 640, H = 440;
  const M = { l: 66, r: 20, t: 20, b: 56 };
  const f = plotFrame(d3.select("#pareto-plot"), W, H, M);

  const x = d3.scaleLinear()
    .domain(d3.extent(pts, (d) => d.costo_congestion)).nice().range([0, f.area.w]);
  const y = d3.scaleLinear()
    .domain([d3.min(pts, (d) => d.cvar) * 0.96, d3.max(pts, (d) => d.cvar) * 1.04]).nice()
    .range([f.area.h, 0]);
  const r = d3.scaleSqrt().domain(d3.extent(pts, (d) => d.saidi)).range([5.5, 15]);
  const cSaidi = d3.scaleSequential(d3.interpolateRdYlGn)
    .domain([d3.max(pts, (d) => d.saidi), d3.min(pts, (d) => d.saidi)]);

  f.g.append("g").attr("class", "axis").attr("transform", `translate(0,${f.area.h})`)
    .call(d3.axisBottom(x).ticks(6).tickFormat((d) => nf0.format(d)).tickSize(3));
  f.g.append("g").attr("class", "axis")
    .call(d3.axisLeft(y).ticks(6).tickFormat((d) => nf1.format(d)).tickSize(3));

  axisTitle(f.svg, f, "costo incremental de congestión (USD, proxy)",
    { x: M.l + f.area.w / 2, y: H - 14 });
  axisTitle(f.svg, f, "CVaR(95%) · horas forzadas", { x: 16, y: M.t + f.area.h / 2, rot: true });

  /* referencia MILP */
  const milp = { x: S.resumen.costo_milp_incremental, y: S.escenarios.metricas.CVaR };
  const milpG = f.g.append("g").style("cursor", "help")
    .on("mousemove", (ev) => tipShow(
      `<b>Plan MILP determinista</b><br>Costo incremental: ${usd(milp.x)}<br>` +
      `CVaR(95%): ${nf2.format(milp.y)} h<br>Punto de referencia (no es solución NSGA-II).`, ev))
    .on("mouseleave", tipHide);
  milpG.append("path")
    .attr("transform", `translate(${x(milp.x)},${y(milp.y)})`)
    .attr("d", d3.symbol().type(d3.symbolStar).size(190))
    .attr("fill", PAPER).attr("stroke", INK).attr("stroke-width", 1.8);
  milpG.append("text").attr("x", x(milp.x) + 12).attr("y", y(milp.y) + 4)
    .attr("font-family", "JetBrains Mono, monospace").attr("font-size", "10px")
    .attr("fill", INK_SOFT).text("MILP");

  let selected = null;
  const dot = f.g.selectAll("circle.pdot").data(pts).join("circle")
    .attr("class", "pdot")
    .attr("cx", (d) => x(d.costo_congestion)).attr("cy", (d) => y(d.cvar))
    .attr("r", (d) => r(d.saidi))
    .attr("fill", (d) => cSaidi(d.saidi)).attr("fill-opacity", 0.88)
    .attr("stroke", INK).attr("stroke-width", 1)
    .style("cursor", "pointer")
    .on("mousemove", (ev, d) => tipShow(
      `<b>Solución del frente</b><br>` +
      `Costo: ${usd(d.costo_congestion)}<br>` +
      `CVaR(95%): ${nf2.format(d.cvar)} h<br>` +
      `SAIDI proxy: ${d.saidi.toFixed(3)}<br>` +
      `<span style="color:#9CA6BF">clic → calendario</span>`, ev))
    .on("mouseleave", tipHide)
    .on("click", (ev, d) => select(d));

  function select(d) {
    selected = d;
    dot.attr("stroke-width", (p) => (p === d ? 3 : 1))
      .attr("stroke", (p) => (p === d ? INK : INK));
    readoutCells(d3.select("#pareto-readouts"), [
      { k: "Costo incr.", v: usd(d.costo_congestion) },
      { k: "CVaR(95%)", v: nf2.format(d.cvar) + " <small>h</small>" },
      { k: "SAIDI proxy", v: d.saidi.toFixed(3) },
      { k: "Líneas", v: Object.keys(d.semanas).length },
    ]);
    renderMiniGantt(d.semanas);
  }

  /* seleccion inicial: menor costo */
  select(pts.reduce((a, b) => (a.costo_congestion <= b.costo_congestion ? a : b)));

  function renderMiniGantt(semanas) {
    const obj = S.resumen.elementos_objetivo;
    const mg = d3.select("#pareto-gantt");
    mg.html("");
    const W2 = 250, rowH2 = 15, H2 = obj.length * rowH2 + 16;
    const svg = mg.append("svg").attr("viewBox", `0 0 ${W2} ${H2}`).attr("width", "100%");
    const x2 = d3.scaleLinear().domain([0, 12]).range([64, W2 - 4]);
    obj.forEach((l, i) => {
      svg.append("text").attr("x", 58).attr("y", i * rowH2 + 11)
        .attr("text-anchor", "end").attr("font-family", "JetBrains Mono, monospace")
        .attr("font-size", "8.5px").attr("fill", INK_SOFT).text(l);
      for (let w = 1; w <= 12; w++) {
        svg.append("rect").attr("x", x2(w - 1) + 0.5).attr("y", i * rowH2 + 2.5)
          .attr("width", x2(1) - x2(0) - 1).attr("height", rowH2 - 6)
          .attr("rx", 1.5)
          .attr("fill", semanas[l] === w ? ORANGE : "rgba(30,42,68,0.08)");
      }
    });
    svg.append("text").attr("x", 64).attr("y", H2 - 1)
      .attr("font-family", "JetBrains Mono, monospace").attr("font-size", "8px")
      .attr("fill", INK_FAINT).text("S1 ────────────────── S12");
  }
}

/* ============================================================
   § 05 — MODELO ML
   ============================================================ */
function renderML(S) {
  const ml = S.ml;
  const featLabels = {
    edad_anios: "Edad (años)", longitud_km: "Longitud (km)",
    capacidad_mva: "Capacidad (MVA)", capa_uso: "Capa de uso",
    temperatura_media_c: "Temperatura media (°C)", viento_promedio_ms: "Viento promedio (m/s)",
    salinidad_alta: "Salinidad alta", uso_intensivo: "Uso intensivo",
  };

  /* --- importancias --- */
  {
    const data = [...ml.importancias].sort((a, b) => a.importancia - b.importancia);
    const W = 520, H = 300, M = { l: 172, r: 56, t: 14, b: 40 };
    const f = plotFrame(d3.select("#ml-importancia"), W, H, M);
    const x = d3.scaleLinear().domain([0, d3.max(data, (d) => d.importancia) * 1.08])
      .range([0, f.area.w]);
    const y = d3.scaleBand().domain(data.map((d) => d.feature))
      .range([0, f.area.h]).padding(0.22);

    f.g.append("g").attr("class", "axis")
      .call(d3.axisBottom(x).ticks(5).tickFormat((d) => nf0.format(d * 100) + "%").tickSize(3))
      .attr("transform", `translate(0,${f.area.h})`);
    f.g.append("g").attr("class", "axis")
      .call(d3.axisLeft(y).tickSize(0).tickFormat((d) => featLabels[d] || d));

    f.g.selectAll("rect.fbar").data(data).join("rect")
      .attr("class", "fbar")
      .attr("x", 0).attr("y", (d) => y(d.feature))
      .attr("width", (d) => x(d.importancia))
      .attr("height", y.bandwidth())
      .attr("fill", GREEN).attr("fill-opacity", 0.85).attr("rx", 1.5)
      .style("cursor", "crosshair")
      .on("mousemove", (ev, d) => tipShow(
        `<b>${featLabels[d.feature] || d.feature}</b><br>Importancia: ${pct(d.importancia, 1)}`, ev))
      .on("mouseleave", tipHide);

    axisTitle(f.svg, f, "importancia Gini (RF, 300 árboles)", { x: M.l + f.area.w / 2, y: H - 10 });
  }

  /* --- observado vs predicho --- */
  {
    const data = ml.predicciones;
    const W = 520, H = 300, M = { l: 62, r: 20, t: 16, b: 46 };
    const f = plotFrame(d3.select("#ml-scatter"), W, H, M);
    const dom = [0, d3.max(data, (d) => Math.max(d.lambda_sem, d.lambda_hist)) * 1.15];
    const x = d3.scaleLinear().domain(dom).range([0, f.area.w]);
    const y = d3.scaleLinear().domain(dom).range([f.area.h, 0]);

    f.g.append("g").attr("class", "axis").attr("transform", `translate(0,${f.area.h})`)
      .call(d3.axisBottom(x).ticks(5).tickFormat((d) => (d * 100).toFixed(1) + "%").tickSize(3));
    f.g.append("g").attr("class", "axis")
      .call(d3.axisLeft(y).ticks(5).tickFormat((d) => (d * 100).toFixed(1) + "%").tickSize(3));

    /* línea y=x */
    f.g.append("line")
      .attr("x1", x(dom[0])).attr("y1", y(dom[0])).attr("x2", x(dom[1])).attr("y2", y(dom[1]))
      .attr("stroke", ORANGE_DEEP).attr("stroke-dasharray", "5 4").attr("stroke-width", 1.4);
    f.g.append("text").attr("x", x(dom[1]) - 6).attr("y", y(dom[1]) + 14)
      .attr("text-anchor", "end").attr("font-family", "JetBrains Mono, monospace")
      .attr("font-size", "9.5px").attr("fill", ORANGE_DEEP).text("y = x");

    f.g.selectAll("circle.mdot").data(data).join("circle")
      .attr("class", "mdot")
      .attr("cx", (d) => x(d.lambda_hist)).attr("cy", (d) => y(d.lambda_sem))
      .attr("r", (d) => (d.en_plan ? 6 : 4.5))
      .attr("fill", (d) => (d.en_plan ? ORANGE : INK))
      .attr("fill-opacity", 0.85).attr("stroke", PAPER).attr("stroke-width", 1.2)
      .style("cursor", "crosshair")
      .on("mousemove", (ev, d) => tipShow(
        `<b>${d.elemento}</b>${d.en_plan ? " · en plan" : ""}<br>` +
        `λ observada: ${pct(d.lambda_hist, 3)}/sem<br>` +
        `λ predicha: ${pct(d.lambda_sem, 3)}/sem`, ev))
      .on("mouseleave", tipHide);

    axisTitle(f.svg, f, "λ observada (5 años de historia)", { x: M.l + f.area.w / 2, y: H - 12 });
    axisTitle(f.svg, f, "λ predicha (RF)", { x: 14, y: M.t + f.area.h / 2, rot: true });
  }

  const eventos = ml.predicciones.filter((d) => d.lambda_hist > 0.0015).length;
  const chips = d3.select("#ml-chips");
  chips.html("");
  [
    `R² in-sample = <b>${nf2.format(ml.r2_insample)}</b>`,
    `n = <b>${ml.n_muestras}</b> líneas`,
    `líneas con historia de falla = <b>${eventos}</b>`,
    `modelo = <b>RF 300 est. · prof. 6</b>`,
  ].forEach((t) => chips.append("span").attr("class", "chip").html(t));
}

/* ============================================================
   § 06 — RIESGO (VaR/CVaR interactivo + Bertsimas-Sim)
   ============================================================ */
function renderRiesgo(S) {
  const horas = S.escenarios.escenarios.map((e) => e.horas_forzadas).sort(d3.ascending);
  const met = S.escenarios.metricas;

  const W = 620, H = 300, M = { l: 56, r: 18, t: 18, b: 46 };
  const f = plotFrame(d3.select("#riesgo-plot"), W, H, M);
  const x = d3.scaleLinear().domain([0, d3.max(horas) * 1.05]).range([0, f.area.w]);

  const bins = d3.bin().domain(x.domain()).thresholds(16)(horas);
  const y = d3.scaleLinear().domain([0, d3.max(bins, (b) => b.length) * 1.12]).nice()
    .range([f.area.h, 0]);

  /* cola sombreada (se recalcula) */
  const tailRect = f.g.append("rect").attr("y", 0).attr("height", f.area.h)
    .attr("fill", "rgba(217,108,44,0.14)").attr("x", f.area.w).attr("width", 0);

  f.g.append("g").attr("class", "axis").attr("transform", `translate(0,${f.area.h})`)
    .call(d3.axisBottom(x).ticks(7).tickFormat((d) => nf0.format(d)).tickSize(3));
  f.g.append("g").attr("class", "axis")
    .call(d3.axisLeft(y).ticks(5).tickFormat((d) => nf0.format(d)).tickSize(3));

  f.g.selectAll("rect.hbar").data(bins).join("rect")
    .attr("class", "hbar")
    .attr("x", (b) => x(b.x0) + 1).attr("width", (b) => Math.max(0, x(b.x1) - x(b.x0) - 2))
    .attr("y", (b) => y(b.length)).attr("height", (b) => f.area.h - y(b.length))
    .attr("fill", INK).attr("fill-opacity", 0.72)
    .style("cursor", "crosshair")
    .on("mousemove", (ev, b) => tipShow(
      `<b>${nf1.format(b.x0)}–${nf1.format(b.x1)} h</b><br>` +
      `${b.length} escenarios (${pct(b.length / horas.length, 1)})`, ev))
    .on("mouseleave", tipHide);

  /* líneas VaR / CVaR */
  const varLine = f.g.append("line").attr("class", "varline")
    .attr("y1", -6).attr("y2", f.area.h)
    .attr("stroke", ORANGE_DEEP).attr("stroke-width", 2).attr("stroke-dasharray", "6 4");
  const varText = f.g.append("text").attr("font-family", "JetBrains Mono, monospace")
    .attr("font-size", "10px").attr("fill", ORANGE_DEEP);
  const cvarLine = f.g.append("line")
    .attr("y1", -6).attr("y2", f.area.h)
    .attr("stroke", RED).attr("stroke-width", 2).attr("stroke-dasharray", "2 3");
  const cvarText = f.g.append("text").attr("font-family", "JetBrains Mono, monospace")
    .attr("font-size", "10px").attr("fill", RED);

  axisTitle(f.svg, f, "horas de indisponibilidad forzada en 12 semanas",
    { x: M.l + f.area.w / 2, y: H - 12 });

  function cvarOf(alpha) {
    const v = d3.quantile(horas, alpha);
    const cola = horas.filter((h) => h >= v);
    return { var: v, cvar: cola.length ? d3.mean(cola) : v };
  }

  function update(alpha) {
    $("#alpha-val").textContent = alpha.toFixed(3);
    const { var: varV, cvar } = cvarOf(alpha);
    varLine.attr("x1", x(varV)).attr("x2", x(varV));
    cvarLine.attr("x1", x(cvar)).attr("x2", x(cvar));
    varText.attr("x", x(varV) + 5).attr("y", 8).text(`VaR = ${nf1.format(varV)} h`);
    cvarText.attr("x", x(cvar) + 5).attr("y", 22).text(`CVaR = ${nf1.format(cvar)} h`);
    tailRect.attr("x", x(varV)).attr("width", Math.max(0, f.area.w - x(varV)));
    readoutCells(d3.select("#riesgo-readouts"), [
      { k: "α", v: alpha.toFixed(3).replace("0.", "0,") },
      { k: "VaR(α)", v: nf1.format(varV) + " <small>h</small>", cls: "warn" },
      { k: "CVaR(α)", v: nf1.format(cvar) + " <small>h</small>", cls: "bad" },
      { k: "media", v: nf1.format(met.media) + " <small>h</small>" },
      { k: "desv. estándar", v: nf1.format(met.std) + " <small>h</small>" },
      { k: "escenarios", v: horas.length },
    ]);
  }
  d3.select("#alpha-slider").on("input", function () { update(+this.value); });
  update(0.95);

  /* ---------- Bertsimas-Sim interactivo ---------- */
  const cal = S.calendario;
  const rob = S.escenarios.robustez;
  const K = S.resumen.max_concurrentes || 2;
  const EXT = 1;
  const fin = {};
  Object.entries(cal).forEach(([l, p]) => { fin[l] = Math.max(...p.fuera); });
  const activos = (w) => Object.keys(cal).filter((l) => cal[l].fuera.includes(w));
  const candidatos = (w) => Object.keys(cal).filter(
    (l) => fin[l] >= w - EXT && fin[l] < w && !cal[l].fuera.includes(w));

  const Wg = 620, rowHg = 13, weeksG = 13;
  const Hg = 120 + 34;
  const fg = plotFrame(d3.select("#gamma-plot"), Wg, Hg, { l: 56, r: 18, t: 26, b: 30 });
  const xg = d3.scaleLinear().domain([0, weeksG]).range([0, fg.area.w]);
  const colWg = fg.area.w / weeksG;

  /* nombres de semanas */
  d3.range(1, 13).forEach((w) => {
    fg.g.append("text").attr("x", xg(w - 0.5)).attr("y", -10)
      .attr("text-anchor", "middle").attr("font-family", "JetBrains Mono, monospace")
      .attr("font-size", "9.5px").attr("fill", INK_SOFT).text("S" + w);
  });

  const colRects = [];
  d3.range(1, weeksG + 1).forEach((w) => {
    const g = fg.g.append("g");
    const base = activos(w).length;
    const cand = candidatos(w).length;
    const bg = g.append("rect")
      .attr("x", xg(w - 1) + 1).attr("width", colWg - 2)
      .attr("y", 0).attr("height", fg.area.h - 8)
      .attr("fill", "rgba(30,42,68,0.03)").attr("stroke", "rgba(30,42,68,0.12)");
    /* barras base (navy) */
    for (let i = 0; i < base; i++) {
      g.append("rect").attr("x", xg(w - 1) + 4).attr("width", colWg - 8)
        .attr("y", fg.area.h - 18 - i * (rowHg + 3)).attr("height", rowHg)
        .attr("fill", INK).attr("rx", 2);
    }
    /* extensiones (naranjas, punteadas) — se activan segun Gamma */
    const exts = [];
    for (let i = 0; i < cand; i++) {
      const r = g.append("rect").attr("x", xg(w - 1) + 4).attr("width", colWg - 8)
        .attr("y", fg.area.h - 18 - (base + i) * (rowHg + 3)).attr("height", rowHg)
        .attr("fill", "rgba(217,108,44,0.5)").attr("stroke", ORANGE_DEEP)
        .attr("stroke-dasharray", "3 2").attr("rx", 2)
        .attr("opacity", 0);
      exts.push(r);
    }
    colRects.push({ w, bg, base, cand, exts });
  });

  fg.g.append("text").attr("x", 0).attr("y", fg.area.h + 2)
    .attr("font-family", "JetBrains Mono, monospace").attr("font-size", "9px")
    .attr("fill", INK_FAINT)
    .text("▮ plan MILP   ▯ extensión por dureza (1 sem)   límite N-1 = " + K + " líneas");

  function updateGamma(gamma) {
    $("#gamma-val").textContent = gamma;
    /* gamma maximo tolerado */
    let gmax = gamma;
    let semCrit = null;
    for (const c of colRects) {
      if (c.cand > (K - c.base)) {
        const tol = Math.max(0, K - c.base);
        if (tol < gmax) { gmax = tol; semCrit = c.w; }
      }
    }
    const robusto = gmax >= gamma;
    colRects.forEach((c) => {
      const viol = c.base + Math.min(gamma, c.cand) > K;
      c.bg.attr("fill", viol ? "rgba(179,64,58,0.16)" : "rgba(30,42,68,0.03)")
        .attr("stroke", viol ? RED : "rgba(30,42,68,0.12)")
        .attr("stroke-width", viol ? 1.8 : 1);
      c.exts.forEach((r, i) => r.attr("opacity", i < gamma ? 1 : 0));
    });
    readoutCells(d3.select("#gamma-readouts"), [
      { k: "Γ solicitado", v: gamma },
      { k: "Γ máx tolerado", v: gmax, cls: gmax >= gamma ? "ok" : "bad" },
      { k: "Semana crítica", v: semCrit ? "S" + semCrit : "—" },
      { k: "Veredicto", v: robusto ? "Robusto" : "Vulnerable", cls: robusto ? "ok" : "bad" },
    ]);
  }
  d3.select("#gamma-slider").on("input", function () { updateGamma(+this.value); });
  updateGamma(rob.gamma != null ? rob.gamma : 2);
}

/* ============================================================
   § 07 — SAIDI ZONAL
   ============================================================ */
function renderSAIDI(S) {
  const data = S.saidi;
  const W = 820, H = data.length * 42 + 58;
  const M = { l: 148, r: 130, t: 20, b: 44 };
  const f = plotFrame(d3.select("#saidi-plot"), W, H, M);
  const y = d3.scaleBand().domain(data.map((d) => d.zona))
    .range([0, f.area.h]).padding(0.24);
  const x = d3.scaleLinear()
    .domain([0, d3.max(data, (d) => d.saidi_horas) * 1.12]).range([0, f.area.w]);

  f.g.append("g").attr("class", "axis")
    .call(d3.axisLeft(y).tickSize(0));
  f.g.append("g").attr("class", "axis").attr("transform", `translate(0,${f.area.h})`)
    .call(d3.axisBottom(x).ticks(6).tickFormat((d) => d.toFixed(2)).tickSize(3));

  const maxS = d3.max(data, (d) => d.saidi_horas) || 1;
  f.g.selectAll("rect.sbar").data(data).join("rect")
    .attr("class", "sbar")
    .attr("x", 0).attr("y", (d) => y(d.zona)).attr("height", y.bandwidth())
    .attr("width", (d) => x(d.saidi_horas))
    .attr("rx", 2)
    .attr("fill", (d) => d3.interpolateRgb("#BFD8C4", ORANGE_DEEP)(d.saidi_horas / maxS))
    .attr("fill-opacity", 0.9)
    .style("cursor", "crosshair")
    .on("mousemove", (ev, d) => tipShow(
      `<b>${d.zona}</b><br>` +
      `SAIDI proxy: ${d.saidi_horas.toFixed(4)}<br>` +
      `Horas·línea indisp.: ${nf1.format(d.horas_indisp)}<br>` +
      `Demanda zonal: ${nf0.format(d.demanda_mw)} MW`, ev))
    .on("mouseleave", tipHide);

  f.g.selectAll("text.sval").data(data).join("text")
    .attr("class", "sval").attr("x", (d) => x(d.saidi_horas) + 8)
    .attr("y", (d) => y(d.zona) + y.bandwidth() / 2 + 3.5)
    .attr("font-family", "JetBrains Mono, monospace").attr("font-size", "10.5px")
    .attr("fill", INK_SOFT).text((d) => d.saidi_horas.toFixed(3));

  axisTitle(f.svg, f, "SAIDI proxy (semanas·línea / MW de demanda zonal)",
    { x: M.l + f.area.w / 2, y: H - 12 });
}

/* ============================================================
   Navegación activa + reveals
   ============================================================ */
function setupNavAndReveals() {
  const links = [...document.querySelectorAll(".banner-nav a")];
  const sections = [...document.querySelectorAll("main section, .hero")];
  const io = new IntersectionObserver((entries) => {
    entries.forEach((e) => {
      if (e.isIntersecting) {
        const id = e.target.id;
        links.forEach((l) => l.classList.toggle("active", l.getAttribute("href") === "#" + id));
      }
    });
  }, { rootMargin: "-40% 0px -55% 0px" });
  sections.forEach((s) => io.observe(s));

  const ro = new IntersectionObserver((entries) => {
    entries.forEach((e) => { if (e.isIntersecting) e.target.classList.add("in"); });
  }, { threshold: 0.12 });
  document.querySelectorAll(".rv").forEach((el) => ro.observe(el));
}

/* ============================================================
   Init
   ============================================================ */
(async () => {
  const note = d3.select("#load-note");
  try {
    const [resumen, red, calendario, costos_ventana, costos_semanales,
      pareto, ml, escenarios, saidi] = await Promise.all([
      loadJSON("resumen.json"), loadJSON("red.json"), loadJSON("calendario.json"),
      loadJSON("costos_ventana.json"), loadJSON("costos_semanales.json"),
      loadJSON("pareto.json"), loadJSON("ml.json"), loadJSON("escenarios.json"),
      loadJSON("saidi.json"),
    ]);
    const S = { resumen, red, calendario, costos_ventana, costos_semanales, pareto, ml, escenarios, saidi };

    renderHero(S);
    renderRed(S);
    renderCalendario(S);
    renderCostos(S);
    renderPareto(S);
    renderML(S);
    renderRiesgo(S);
    renderSAIDI(S);
    setupNavAndReveals();
    note.classed("hidden", true);
  } catch (err) {
    console.error("Error cargando dashboard:", err);
    note.classed("err", true).text(
      "error: " + err.message + " — los datos deben servirse por HTTP (local: python -m http.server desde dashboard/)");
  }
})();
