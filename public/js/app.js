/* Liveable Melbourne — map, audience modes, one-click presets, scorecards. */
(async function () {
  const [geo, data] = await Promise.all([
    fetch("data/melbourne.geojson").then(r => r.json()),
    fetch("data/scores.json").then(r => r.json()),
  ]);
  const A = data.areas;
  const MODE_PRESETS = data.mode_presets || { live: 0.85, balanced: 0.5, invest: 0.2 };
  const PRESETS = data.presets || [];

  // ---- state ------------------------------------------------------------
  let mode = "balanced";          // live | balanced | invest  (palette + liveability weighting)
  let colorBy = "overall";        // overall | live | dev | family
  let wLive = 0.5;                // blend weight (liveability)
  let minScore = 0;
  let activePreset = null;        // preset key or null (custom)
  let activeBest = null;          // "live" | "invest" | "develop" | null
  let selected = null;

  // Colour-by options (one-tap toggles): overall/live/dev/family + raw layers.
  const COLORBY = [
    ["overall", "Overall"], ["live", "Liveability"], ["dev", "Development"],
    ["safety", "Safety"], ["seifa", "Socio-economic"], ["family", "Family"],
    ["growth", "Price growth"], ["grid", "Grid"],
  ];

  const MODE_LABEL = { live: "Live", balanced: "Balanced", invest: "Invest / Develop" };
  const MODE_COPY = {
    live: "Optimised for a safe, stable place to live or rent — personal safety and family signals lead; property crime is down-weighted.",
    balanced: "A balanced 50/50 view with full transparency across liveability and development.",
    invest: "Optimised for investors/developers — redevelopment headroom, turnover and low density.",
  };
  const MODE_RAMP = { live: "live", balanced: "balanced", invest: "invest" };
  const MODE_COLORBY = { live: "live", balanced: "overall", invest: "dev" };

  // ---- colour ramps -----------------------------------------------------
  const RAMPS = {
    balanced: [[0, [215, 38, 61]], [35, [240, 140, 46]], [55, [243, 198, 19]], [72, [91, 191, 58]], [100, [31, 138, 59]]],
    live: [[0, [203, 124, 120]], [45, [214, 208, 150]], [70, [120, 194, 120]], [100, [19, 122, 62]]],
    invest: [[0, [44, 74, 110]], [45, [110, 140, 180]], [72, [217, 164, 65]], [100, [242, 196, 0]]],
  };
  function rampColor(score, ramp) {
    const stops = RAMPS[ramp]; score = Math.max(0, Math.min(100, score));
    let a = stops[0], b = stops[stops.length - 1];
    for (let i = 0; i < stops.length - 1; i++) if (score >= stops[i][0] && score <= stops[i + 1][0]) { a = stops[i]; b = stops[i + 1]; break; }
    const t = b[0] === a[0] ? 0 : (score - a[0]) / (b[0] - a[0]);
    const c = j => Math.round(a[1][j] + t * (b[1][j] - a[1][j]));
    return `rgb(${c(0)},${c(1)},${c(2)})`;
  }
  const cssGradient = ramp => "linear-gradient(90deg," + RAMPS[ramp].map(s => `${rampColor(s[0], ramp)} ${s[0]}%`).join(",") + ")";
  const col = s => rampColor(s, MODE_RAMP[mode]);
  const pct = x => x == null ? "—" : Math.round(x * 100) + "%";

  // ---- score accessors (mode-aware Liveability) -------------------------
  const liveOf = a => mode === "live" ? a.live_family : a.live;     // family weighting in Live mode
  const overallOf = a => Math.round((wLive * liveOf(a) + (1 - wLive) * a.dev) * 10) / 10;
  function metricOf(a) {
    switch (colorBy) {
      case "live": return liveOf(a);
      case "dev": return a.dev;
      case "family": return a.family.score;
      case "safety": return a.pillars.person_safety.score;     // higher = safer (inverse crime)
      case "seifa": return a.pillars.seifa.score;
      case "growth": return a.market.growth_score;
      case "grid": return a.infra.score;
      default: return overallOf(a);
    }
  }

  // ---- map --------------------------------------------------------------
  const map = L.map("map", { zoomControl: true }).setView([-37.84, 145.05], 10);
  const tilesFor = dark => L.tileLayer(
    `https://{s}.basemaps.cartocdn.com/${dark ? "dark_nolabels" : "light_nolabels"}/{z}/{x}/{y}{r}.png`,
    { subdomains: "abcd", maxZoom: 19, attribution: '&copy; <a href="https://openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/attributions">CARTO</a> · Data: ABS, CSA Vic' });
  let base = tilesFor(document.documentElement.dataset.theme === "dark").addTo(map);
  const labels = L.tileLayer("https://{s}.basemaps.cartocdn.com/light_only_labels/{z}/{x}/{y}{r}.png",
    { subdomains: "abcd", pane: "markerPane", opacity: .85 });

  const style = f => {
    const a = A[f.properties.sa2_code]; if (!a) return { fillColor: "#bbb", fillOpacity: .25, weight: .5, color: "#fff" };
    const v = metricOf(a), sel = f.properties.sa2_code === selected;
    return { weight: sel ? 2.6 : .5, color: sel ? "#0a84ff" : "#ffffff", fillColor: col(v), fillOpacity: v >= minScore ? .84 : .08 };
  };
  const layer = L.geoJSON(geo, {
    style,
    onEachFeature: (f, lyr) => lyr.on({
      mouseover: e => { hover(f.properties.sa2_code); e.target.setStyle({ weight: 2, color: "#1c1c1e" }); },
      mouseout: e => { hideHover(); layer.resetStyle(e.target); if (f.properties.sa2_code === selected) e.target.setStyle({ weight: 2.6, color: "#0a84ff" }); },
      click: () => select(f.properties.sa2_code, true),
    }),
  }).addTo(map);
  layer.bringToBack(); labels.addTo(map);
  const byCode = {}; layer.eachLayer(l => byCode[l.feature.properties.sa2_code] = l);
  const repaint = () => layer.setStyle(style);

  // ---- hover ------------------------------------------------------------
  const hc = document.getElementById("hovercard");
  function hover(code) {
    const a = A[code]; if (!a) return;
    hc.innerHTML = `<b>${a.name}</b> · ${a.lga || ""}
      <div class="hg"><span>Live ${liveOf(a)}</span><span>Dev ${a.dev}</span><span>Overall ${overallOf(a)}</span></div>`;
    hc.classList.remove("hidden");
  }
  const hideHover = () => hc.classList.add("hidden");

  // ---- scorecard --------------------------------------------------------
  const gradeColor = g => ({ "A+": "#248a3d", "A": "#34c759", "B": "#ffcc00", "C": "#ff9500", "D": "#ff3b30" }[g] || "#8e8e93");
  const sc = document.getElementById("scorecard");
  const PILL_TIPS = {
    "Personal safety": "Rate of crimes against the person (assault, robbery, sexual offences). Greener = lower than most suburbs.",
    "Socio-economic": "ABS SEIFA decile — relative socio-economic advantage (10 = most advantaged).",
    "Children 0–14": "Share of residents aged 0–14 — a family-area signal.",
    "Owner-occupied": "Share of homes lived in by their owners — a housing-stability signal.",
    "Property safety": "Property-crime rate (theft, break-ins). Shown separately and weighted lightly.",
    "Low social housing": "Share of social / public housing, shown for transparency.",
    "Detached headroom": "Share of low-density detached houses — room to rebuild or subdivide.",
    "Recent growth": "3-year change in median house price — recent momentum, not a forecast.",
    "Grid support": "How well the nearby electricity network can support larger development.",
    "Rental turnover": "Share of rented dwellings — investor / tenant activity.",
    "Low density": "People per km² (inverted, so fewer people = more headroom).",
  };
  const bar = (label, score, valText, sub) =>
    `<div class="pill${sub ? " sub" : ""}" title="${PILL_TIPS[label] || ""}"><span class="pl">${label}</span>
      <span class="bar"><i style="width:${score}%;background:${col(score)}"></i></span>
      <span class="pv">${valText}</span></div>`;

  // "Best for…" — preset-specific copy first, else mode-based.
  function bestFor(a) {
    const t = a.tags, safe = t.includes("Very safe") || t.includes("Safe");
    const headroom = t.includes("Redevelopment headroom") || t.includes("Growth corridor");
    if (activePreset === "family") return safe ? "<b>raising kids</b> somewhere safe and settled" : "families willing to <b>trade some safety for space</b>";
    if (activePreset === "safety") return a.pillars.person_safety.score >= 80 ? "<b>near-total peace of mind</b> on personal safety" : "putting <b>personal safety first</b>";
    if (activePreset === "balanced") return a.overall >= 62 ? "a <b>buy-and-hold that's genuinely liveable</b>" : "<b>weighing livability against upside</b>";
    if (activePreset === "value") return headroom ? "<b>value-add / subdivision &amp; redevelopment</b> upside" : "an <b>established hold</b> rather than development";
    if (mode === "live") return safe && a.family.score >= 65 ? "a <b>safe family base</b>" : "<b>settling somewhere calm</b>";
    if (mode === "invest") return headroom ? "<b>redevelopment / growth-corridor</b> upside" : "an <b>established hold</b>";
    return a.overall >= 65 ? "a <b>strong all-round</b> live-or-invest pick" : "<b>weighing safety against upside</b>";
  }

  const money = v => v == null ? "—" : v >= 1e6 ? `$${(v / 1e6).toFixed(2)}M` : `$${Math.round(v / 1e3)}k`;
  function marketBlock(a, prominent) {
    const m = a.market;
    const sig = (label, cls) => `<span class="sig sig-${cls}">${label}</span>`;
    if (!m.median_house)
      return `<div class="market mini"><div class="market-h">Market &amp; Price</div>
        <p class="market-note">No Valuer-General sale medians for this area.</p></div>`;
    const up = (m.house_12m ?? 0) >= 0;
    return `<div class="market${prominent ? "" : " mini"}">
      <div class="market-h">Market &amp; Price <span class="src">VG ${m.house_year}</span></div>
      <div class="market-row">
        <div class="price"><span class="ml">Median house</span><span class="pv-big">${money(m.median_house)}</span></div>
        <div class="growth" style="color:${up ? "var(--good)" : "#ff3b30"}">${up ? "▲" : "▼"} ${m.house_12m ?? "–"}% <small>12m</small></div>
      </div>
      <div class="market-sub">
        ${m.median_unit ? `Unit ${money(m.median_unit)} · ` : ""}3-yr ${m.house_3yr_cagr ?? "–"}%/yr
        ${sig(m.growth_signal + " growth", m.growth_signal.toLowerCase())}${m.value_signal ? sig(m.value_signal, "val") : ""}
      </div>
      ${prominent ? `<p class="market-note">${a.explanation_invest}</p>` : ""}</div>`;
  }

  const IC = {
    fam: '<svg class="ic ic-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="9" cy="8" r="3"/><path d="M3.6 19a5.4 5.4 0 0 1 10.8 0"/><path d="M16 6.6a3 3 0 0 1 0 5.8M17.4 14a5 5 0 0 1 3 4.6"/></svg>',
    bolt: '<svg class="ic ic-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round" aria-hidden="true"><path d="M13 3 5 13h5l-1 8 8-11h-5z"/></svg>',
  };
  function infraBlock(a, prominent) {
    const i = a.infra, adv = i.advantage.toLowerCase();
    const advCls = adv === "strong" ? "strong" : adv === "moderate" ? "moderate" : "soft";
    return `<div class="market${prominent ? "" : " mini"}">
      <div class="market-h">Infrastructure &amp; Electricity <span class="src">Geoscience Australia</span></div>
      <div class="market-sub">
        <span class="sig sig-${advCls}">${i.advantage} grid support</span>
        ${i.nearest_line_kv ? `<span class="sig sig-val">${i.nearest_line_kv} kV nearby</span>` : ""}</div>
      <div class="market-sub icrow">${IC.bolt}${i.nearest_transmission_km != null ? i.nearest_transmission_km + " km to transmission" : "—"} · ${i.substation_count_10km} substations &lt;10 km</div>
      ${prominent ? `<p class="market-note">${a.explanation_infra}</p>` : ""}</div>`;
  }

  function renderCard(code) {
    const a = A[code]; if (!a) return;
    const p = a.pillars, m = a.market, lv = liveOf(a), ov = overallOf(a);
    const prominent = mode !== "live";          // price leads in Balanced/Invest, light in Live
    const chips = [`<span class="chip fam">${IC.fam} ${a.family.label} ${a.family.score}</span>`]
      .concat(a.tags.map(t => `<span class="chip">${t}</span>`)).join("");
    const liveLab = mode === "live" ? "Liveability ·family" : "Liveability";
    sc.classList.remove("empty");
    sc.innerHTML = `
      <div class="sc-head">
        <div><h2 class="sc-name">${a.name}</h2>
          <p class="sc-sub">${a.sa3 || ""} · ${a.lga || ""}${a.population ? " · pop " + a.population.toLocaleString() : ""}</p></div>
        <span class="grade" style="background:${gradeColor(a.grade)}">${a.grade}</span>
      </div>
      <div class="chips">${chips}</div>
      <p class="bestfor"><b>Best for:</b> ${bestFor(a)}.</p>
      <div class="bigrow">
        <div class="big" style="background:${rampColor(lv, "live")}"><div class="lab">${liveLab}</div><div class="num">${lv}</div></div>
        <div class="big" style="background:${rampColor(a.dev, "invest")}"><div class="lab">Development</div><div class="num">${a.dev}</div></div>
        <div class="big" style="background:${col(ov)}"><div class="lab">Overall</div><div class="num">${ov}</div></div>
      </div>
      ${prominent ? marketBlock(a, true) + infraBlock(a, true) : ""}
      <div class="pgroup-h">Liveability — safety &amp; stability</div>
      ${bar("Personal safety", p.person_safety.score, p.person_safety.raw == null ? "—" : Math.round(p.person_safety.raw).toLocaleString() + "/100k")}
      ${bar("Socio-economic", p.seifa.score, "decile " + (p.seifa.decile ?? "—") + "/10")}
      ${bar("Children 0–14", p.child.score, pct(p.child.raw))}
      ${bar("Owner-occupied", p.owner_occ.score, pct(p.owner_occ.raw))}
      ${bar("Property safety", p.property_safety.score, p.property_safety.raw == null ? "—" : Math.round(p.property_safety.raw).toLocaleString() + "/100k", true)}
      ${bar("Low social housing", p.low_social.score, pct(p.low_social.raw) + " social", true)}
      <div class="pgroup-h">Development potential <span class="prelim">preliminary</span></div>
      ${bar("Detached headroom", p.detached.score, pct(p.detached.raw))}
      ${bar("Recent growth", m.growth_score, m.house_3yr_cagr == null ? "n/a" : m.house_3yr_cagr + "%/yr")}
      ${bar("Grid support", a.infra.score, a.infra.advantage)}
      ${bar("Rental turnover", p.rental.score, pct(p.rental.raw))}
      ${bar("Low density", p.low_density.score, p.low_density.raw == null ? "—" : Math.round(p.low_density.raw).toLocaleString() + "/km²")}
      <p class="summary">${a.explanation_live}</p>
      <p class="summary dev">${a.explanation_dev}</p>
      ${prominent ? "" : marketBlock(a, false) + infraBlock(a, false)}`;
    sc.classList.remove("pop"); void sc.offsetWidth; sc.classList.add("pop");  // re-trigger fade-in
  }

  function select(code, fly) {
    selected = code; repaint(); renderCard(code);
    infopanel.classList.remove("peek");       // picking a suburb re-opens a pushed-down sheet
    if (fly && byCode[code]) map.fitBounds(byCode[code].getBounds(), { maxZoom: 13, padding: [40, 40] });
  }

  // ---- mobile bottom sheets: drag the grab pill to push down / pull up ----
  const infopanel = document.getElementById("infopanel");
  function sheetDrag(el, grabEl, isDown, setDown) {
    let y0 = 0, t0 = 0, on = false;
    const span = () => el.getBoundingClientRect().height - 52;   // collapse leaves a 52px strip
    grabEl.addEventListener("touchstart", e => {
      on = true; y0 = e.touches[0].clientY; t0 = isDown() ? span() : 0; el.classList.add("dragging");
    }, { passive: true });
    grabEl.addEventListener("touchmove", e => {
      if (!on) return;
      const dy = Math.max(0, Math.min(span(), t0 + e.touches[0].clientY - y0));
      el.style.transform = `translateY(${dy}px)`;
    }, { passive: true });
    grabEl.addEventListener("touchend", e => {
      if (!on) return; on = false;
      el.classList.remove("dragging"); el.style.transform = "";
      const dy = e.changedTouches[0].clientY - y0;
      setDown(Math.abs(dy) < 12 ? !isDown() : t0 + dy > span() / 2);   // small movement = tap toggle
    });
  }
  sheetDrag(infopanel, document.getElementById("ipGrab"),
    () => infopanel.classList.contains("peek"), d => infopanel.classList.toggle("peek", d));
  const dock = document.getElementById("dock");
  sheetDrag(dock, document.getElementById("dockGrab"),
    () => dock.classList.contains("collapsed"), d => dock.classList.toggle("collapsed", d));

  // ---- modes + presets --------------------------------------------------
  function highlightModes() {
    document.querySelectorAll("#modeSeg button").forEach(b => b.classList.toggle("on", b.dataset.mode === mode));
    document.getElementById("modeCopy").textContent = MODE_COPY[mode];
  }
  function setMode(m, keepPreset) {
    mode = m; if (!keepPreset) activePreset = null;
    activeBest = null; minScore = 0;
    wLive = MODE_PRESETS[m]; colorBy = MODE_COLORBY[m];
    setSlider(); setMinSlider(); highlightModes(); refresh();
  }
  document.querySelectorAll("#modeSeg button").forEach(b => b.onclick = () => setMode(b.dataset.mode));

  const presetRow = document.getElementById("presetRow");
  presetRow.innerHTML = PRESETS.map(p =>
    `<button class="preset p-${p.key}" data-key="${p.key}" title="${p.blurb}">
       <span class="pt">${p.label}</span><span class="pp">${p.live}% liveability</span></button>`).join("");
  presetRow.querySelectorAll(".preset").forEach(btn => btn.onclick = () => {
    const p = PRESETS.find(x => x.key === btn.dataset.key);
    activePreset = p.key; activeBest = null; minScore = 0;
    mode = p.mode; wLive = p.live / 100; colorBy = p.colorBy;
    setSlider(); setMinSlider(); highlightModes(); refresh();
  });
  const highlightPresets = () =>
    presetRow.querySelectorAll(".preset").forEach(b => b.classList.toggle("on", b.dataset.key === activePreset));

  // ---- controls ---------------------------------------------------------
  const blend = document.getElementById("blend");
  const minScore$ = document.getElementById("minScore");
  function setSlider() {
    blend.value = Math.round(wLive * 100);
    document.getElementById("wLive").textContent = blend.value;
    document.getElementById("wDev").textContent = 100 - blend.value;
  }
  function setMinSlider() {
    minScore$.value = Math.max(0, Math.min(90, Math.round(minScore)));
    document.getElementById("minVal").textContent = Math.round(minScore);
  }
  blend.oninput = () => { wLive = blend.value / 100; activePreset = null; activeBest = null; setSlider(); refresh(); };
  minScore$.oninput = () => { minScore = +minScore$.value; activeBest = null; document.getElementById("minVal").textContent = minScore; repaint(); highlightBest(); };

  // colour-by toggle chips (one tap to colour the map by a single layer)
  const CBY_TIPS = {
    overall: "Blend of Liveability and Development (set by the slider).",
    live: "How good it is to live or rent here now.", dev: "Room to invest, build or subdivide.",
    safety: "Personal-crime rate — greener = lower.", seifa: "ABS socio-economic advantage.",
    family: "Family-suitability score.", growth: "Recent 3-year price growth.",
    grid: "Electricity-network support.",
  };
  const cbyRow = document.getElementById("colorByChips");
  cbyRow.innerHTML = COLORBY.map(([k, lab]) => `<button data-cby="${k}" title="${CBY_TIPS[k] || ""}">${lab}</button>`).join("");
  cbyRow.querySelectorAll("button").forEach(b => b.onclick = () => { colorBy = b.dataset.cby; activeBest = null; refresh(); });
  const highlightColorBy = () => cbyRow.querySelectorAll("button").forEach(b => b.classList.toggle("on", b.dataset.cby === colorBy));

  // "Show me the best" quick actions — set the lens AND isolate the top ~20.
  const BEST = {
    live: { mode: "live", colorBy: "live", wLive: 0.85 },        // safest, most liveable
    invest: { mode: "invest", colorBy: "growth", wLive: 0.35 },  // strongest recent capital growth
    develop: { mode: "invest", colorBy: "dev", wLive: 0.20 },    // most room to build / subdivide
  };
  function showBest(kind) {
    const b = BEST[kind];
    mode = b.mode; colorBy = b.colorBy; wLive = b.wLive; activePreset = null; activeBest = kind;
    setSlider();
    const ranked = entries.slice().sort((x, y) => metricOf(y[1]) - metricOf(x[1]));
    minScore = Math.max(0, Math.min(90, Math.floor(metricOf(ranked[Math.min(19, ranked.length - 1)][1]))));
    setMinSlider(); highlightModes(); refresh();
    select(ranked[0][0], true);
  }
  const bestRow = document.getElementById("bestRow");
  bestRow.querySelectorAll(".best-btn").forEach(b => b.onclick = () => showBest(b.dataset.kind));
  const highlightBest = () => bestRow.querySelectorAll(".best-btn").forEach(b => b.classList.toggle("on", b.dataset.kind === activeBest));

  function refresh() {
    repaint(); updateLegend(); updateLists();
    highlightPresets(); highlightColorBy(); highlightBest();
    updateActiveCaption();
    if (selected) renderCard(selected);
  }

  const BEST_LABEL = { live: "Best to live", invest: "Best to invest", develop: "Best to develop" };
  function updateActiveCaption() {
    const el = document.getElementById("activePreset");
    const p = PRESETS.find(x => x.key === activePreset);
    el.innerHTML = activeBest ? `Showing <b>${BEST_LABEL[activeBest]}</b> — top ~20 areas highlighted`
      : p ? `Preset: <b>${p.label}</b> — ${p.blurb}`
        : `Custom blend · <b>${Math.round(wLive * 100)}%</b> liveability`;
  }

  // ---- legend + lists ---------------------------------------------------
  const LABELS = {
    overall: "Overall", live: "Liveability", dev: "Development", family: "Family suitability",
    safety: "Safety (low crime)", seifa: "Socio-economic", growth: "Price growth", grid: "Grid support",
  };
  const LEGEND_DESC = {
    overall: "Blend of liveability & development", live: "How good it is to live or rent here",
    dev: "Room to build, invest or subdivide", safety: "Lower personal-crime rate",
    seifa: "Socio-economic advantage", family: "How suitable for families",
    growth: "Recent 3-year price growth", grid: "Electricity-network support",
  };
  function updateLegend() {
    const el = document.getElementById("legend");
    el.innerHTML =
      `<div class="lt"><span>Colour&nbsp;=&nbsp;${LABELS[colorBy]}</span>
         <button class="lg-help" type="button" title="Open the full guide">?</button></div>
       <div class="ramp" style="background:${cssGradient(MODE_RAMP[mode])}"></div>
       <div class="scalex"><span>lower</span><span>higher</span></div>
       <div class="lg-desc"><b>${LEGEND_DESC[colorBy]}.</b> Higher is better — tap a suburb for the full story.</div>`;
    el.querySelector(".lg-help").onclick = () => openGuide("map");
  }
  const entries = Object.entries(A);
  function updateLists() {
    document.getElementById("listLabel").textContent = LABELS[colorBy];
    const top = entries.slice().sort((x, y) => metricOf(y[1]) - metricOf(x[1])).slice(0, 12);
    const list = document.getElementById("topList");
    list.innerHTML = top.map(([code, a], i) =>
      `<li data-code="${code}"><span class="rk">${i + 1}</span><span class="nm">${a.name}</span>
        <span class="sv" style="color:${col(metricOf(a))}">${metricOf(a)}</span></li>`).join("");
    list.querySelectorAll("li").forEach(li => li.onclick = () => select(li.dataset.code, true));
  }

  // ---- footer build line ------------------------------------------------
  document.getElementById("genline").textContent = `${data.count} suburbs · built ${data.generated}`;

  // ---- search -----------------------------------------------------------
  const search = document.getElementById("search"), results = document.getElementById("results");
  const topbar = document.getElementById("topbar");
  const closeSearch = () => { topbar.classList.remove("search-open"); results.innerHTML = ""; search.blur(); };
  search.oninput = () => {
    const q = search.value.trim().toLowerCase(); results.innerHTML = "";
    if (!q) return;
    entries.filter(([, a]) => a.name.toLowerCase().includes(q)).slice(0, 8).forEach(([code, a]) => {
      const d = document.createElement("div"); d.className = "res";
      d.innerHTML = `<span>${a.name}</span><small>${a.lga || ""}</small>`;
      d.onclick = () => { select(code, true); search.value = a.name; closeSearch(); };
      results.appendChild(d);
    });
  };
  // mobile: the topbar magnifier expands the search into a full-width bar
  document.getElementById("searchTog").onclick = () => {
    if (topbar.classList.toggle("search-open")) { search.value = ""; results.innerHTML = ""; search.focus(); }
    else closeSearch();
  };
  map.on("click", closeSearch);

  // ---- electricity network overlay (the "AEMO map" layer) ---------------
  let elecLayer = null;
  const kvColor = kv => kv >= 350 ? "#e5484d" : kv >= 200 ? "#f76808" : kv >= 100 ? "#a855f7" : "#0a84ff";
  const kvWeight = kv => kv >= 350 ? 3 : kv >= 200 ? 2.2 : kv >= 100 ? 1.6 : 1.1;
  async function ensureElec() {
    if (elecLayer) return elecLayer;
    const gj = await fetch("data/electricity.geojson").then(r => r.json());
    elecLayer = L.geoJSON(gj, {
      style: f => f.geometry.type === "LineString"
        ? { color: kvColor(f.properties.kv || 0), weight: kvWeight(f.properties.kv || 0), opacity: .85 } : {},
      pointToLayer: (f, ll) => L.circleMarker(ll, { radius: 3, color: "#fff", weight: 1, fillColor: "#ffd60a", fillOpacity: .95 }),
      onEachFeature: (f, l) => l.bindTooltip(`${f.properties.name ? f.properties.name + " · " : ""}${f.properties.kv || "?"} kV`),
    });
    return elecLayer;
  }
  document.getElementById("elecToggle").onchange = async e => {
    const lyr = await ensureElec();
    if (e.target.checked) lyr.addTo(map); else map.removeLayer(lyr);
  };

  // ---- theme ------------------------------------------------------------
  function setTheme(t) {
    document.documentElement.dataset.theme = t; localStorage.setItem("theme", t);
    map.removeLayer(base); base = tilesFor(t === "dark").addTo(map); base.bringToBack();
  }
  document.getElementById("theme").onclick = () => setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");

  // ---- guide modal (tabbed) ---------------------------------------------
  const modal = document.getElementById("aboutModal");
  const aboutTabs = [...modal.querySelectorAll(".about-tab")];
  function switchTab(name) {
    aboutTabs.forEach(b => b.classList.toggle("active", b.dataset.tab === name));
    modal.querySelectorAll(".about-panel").forEach(p => p.classList.toggle("active", p.id === "tab-" + name));
    const box = modal.querySelector(".modal-content"); if (box) box.scrollTop = 0;
  }
  aboutTabs.forEach(b => b.onclick = () => switchTab(b.dataset.tab));
  function openGuide(tab) {
    if (tab) switchTab(tab);
    modal.classList.remove("hidden"); modal.setAttribute("aria-hidden", "false");
  }
  const closeGuide = () => { modal.classList.add("hidden"); modal.setAttribute("aria-hidden", "true"); };
  document.getElementById("aboutBtn").onclick = () => openGuide();
  document.getElementById("howtoBtn").onclick = () => openGuide("start");
  modal.querySelectorAll("#closeAbout, #closeAbout2").forEach(b => b.onclick = closeGuide);
  modal.onclick = e => { if (e.target === modal) closeGuide(); };
  document.addEventListener("keydown", e => { if (e.key === "Escape") { closeGuide(); closeSearch(); } });

  // ---- init -------------------------------------------------------------
  setTheme(localStorage.getItem("theme") || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"));
  setMode("balanced");
  if (!localStorage.getItem("seenGuide")) { openGuide("start"); localStorage.setItem("seenGuide", "1"); }
})();
