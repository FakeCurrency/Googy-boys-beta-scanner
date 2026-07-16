/* Melbourne Property — map, audience modes, one-click presets, scorecards. */
(async function () {
  // These two run before data loads (they used to be inline, moved here for CSP).
  if (window.innerWidth < 900) document.getElementById("dock").classList.add("collapsed");
  document.getElementById("dockTog").addEventListener("click",
    () => document.getElementById("dock").classList.toggle("collapsed"));

  // Versioned data URLs: keeps code + data cache-coherent on GitHub Pages
  // (bump together with the ?v= asset versions in index.html; the deploy
  // workflow overwrites both with the run number).
  const DATA_V = "25";
  const boot = document.getElementById("boot");
  const fetchJson = url => fetch(url).then(r => {
    if (!r.ok) throw new Error(url.split("?")[0] + " → HTTP " + r.status);
    return r.json();
  });
  // Cities manifest: each city's files live under data/<slug>/. Pick the city
  // from the URL hash, then the saved choice, then the manifest default.
  let CITIES = { default: "melbourne", cities: [{ slug: "melbourne", name: "Melbourne" }] };
  try { CITIES = await fetchJson("data/cities.json?v=" + DATA_V); } catch (e) {}
  const wantCity = new URLSearchParams(location.hash.replace(/^#/, "")).get("city");
  let savedCity = null; try { savedCity = localStorage.getItem("city"); } catch (e) {}
  const citySlug = [wantCity, savedCity, CITIES.default]
    .find(s => s && CITIES.cities.some(c => c.slug === s)) || CITIES.cities[0].slug;
  const CITY_BASE = "data/" + citySlug + "/";
  let geo, data;
  try {
    [geo, data] = await Promise.all([
      fetchJson(CITY_BASE + "boundaries.geojson?v=" + DATA_V),
      fetchJson(CITY_BASE + "scores.json?v=" + DATA_V),
    ]);
  } catch (err) {
    boot.innerHTML = `<div class="boot-inner">
      <div class="boot-t">Couldn't load the suburb data</div>
      <div class="boot-s">${(err && err.message) || err}<br>Check your connection and try again.</div>
      <button class="btn boot-retry" id="bootRetry">Retry</button></div>`;
    document.getElementById("bootRetry").addEventListener("click", () => location.reload());
    return;
  }
  // Previous refresh's grades (for trend arrows) — optional, never blocks boot.
  let PREV = null;
  fetchJson(CITY_BASE + "prev-scores.json?v=" + DATA_V)
    .then(p => { PREV = p; if (selected) renderCard(selected); }).catch(() => {});
  // Per-suburb explanation paragraphs — split out of scores.json so first
  // paint doesn't pay for ~250 KB of prose. Loaded lazily, never blocks boot.
  let EXPL = null;
  fetchJson(CITY_BASE + "explanations.json?v=" + DATA_V)
    .then(x => { EXPL = x; if (selected) renderCard(selected); }).catch(() => { EXPL = {}; });
  // works with both the split file and legacy inline explanation_* fields
  const explOf = a => (EXPL && EXPL[a._c]) || {
    live: a.explanation_live, dev: a.explanation_dev, invest: a.explanation_invest,
  };
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
  let askSet = null;              // Set of sa2 codes matched by the Ask feature
  // shortlist must exist before the map layer is built — style() reads it
  let shortlist = new Set(JSON.parse(localStorage.getItem("shortlist") || "[]"));
  const saveShortlist = () => localStorage.setItem("shortlist", JSON.stringify([...shortlist]));

  // Colour-by options (one-tap toggles): composites, sub-lenses + raw layers.
  const COLORBY = [
    ["overall", "Overall"], ["live", "Liveability"], ["dev", "Development"],
    ["greenfield", "Greenfield"], ["infill", "Infill"],
    ["safety", "Safety"], ["seifa", "Socio-economic"], ["family", "Family"],
    ["growth", "Price growth"], ["yield", "Yield"], ["zoning", "Zoning"],
    ["transport", "Trains"], ["schools", "Schools"],
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
    invest: [[0, [96, 122, 156]], [45, [148, 168, 196]], [72, [217, 164, 65]], [100, [242, 196, 0]]],
  };
  // Colour-blind-safe alternative (viridis-like): monotonic lightness, no
  // red/green axis. One ramp replaces all three when the toggle is on.
  const CB_RAMP = [[0, [68, 1, 84]], [30, [59, 82, 139]], [55, [33, 145, 140]], [78, [94, 201, 98]], [100, [253, 231, 37]]];
  let cbPalette = localStorage.getItem("cbPalette") === "1";
  function rampColor(score, ramp) {
    const stops = cbPalette ? CB_RAMP : RAMPS[ramp]; score = Math.max(0, Math.min(100, score));
    let a = stops[0], b = stops[stops.length - 1];
    for (let i = 0; i < stops.length - 1; i++) if (score >= stops[i][0] && score <= stops[i + 1][0]) { a = stops[i]; b = stops[i + 1]; break; }
    const t = b[0] === a[0] ? 0 : (score - a[0]) / (b[0] - a[0]);
    const c = j => Math.round(a[1][j] + t * (b[1][j] - a[1][j]));
    return `rgb(${c(0)},${c(1)},${c(2)})`;
  }
  const cssGradient = ramp => "linear-gradient(90deg," + (cbPalette ? CB_RAMP : RAMPS[ramp]).map(s => `${rampColor(s[0], ramp)} ${s[0]}%`).join(",") + ")";
  const col = s => rampColor(s, MODE_RAMP[mode]);
  const pct = x => x == null ? "—" : Math.round(x * 100) + "%";

  // ---- inline toast (replaces alert(): non-blocking, auto-dismisses) -----
  let toastTimer = 0;
  function toast(msg) {
    let el = document.getElementById("toast");
    if (!el) { el = document.createElement("div"); el.id = "toast"; document.body.appendChild(el); }
    el.textContent = msg; el.classList.add("show");
    clearTimeout(toastTimer); toastTimer = setTimeout(() => el.classList.remove("show"), 4200);
  }

  // ---- score accessors (mode-aware Liveability, custom-weight aware) -----
  Object.entries(A).forEach(([c, a]) => a._c = c);   // stamp codes for custom-score maps
  let customW = null;                                 // {live:{k:0-100}, dev:{k:0-100}} | null
  let custLive = null, custDev = null;                // Map code -> stretched 0-100
  const liveOf = a => customW ? custLive.get(a._c) : (mode === "live" ? a.live_family : a.live);
  const devOf = a => customW ? custDev.get(a._c) : a.dev;
  const overallOf = a => Math.round((wLive * liveOf(a) + (1 - wLive) * devOf(a)) * 10) / 10;
  function metricOf(a) {
    switch (colorBy) {
      case "live": return liveOf(a);
      case "dev": return devOf(a);
      case "greenfield": return a.dev_green;
      case "infill": return a.dev_infill;
      case "family": return a.family.score;
      case "safety": return a.pillars.person_safety.score;     // higher = safer (inverse crime)
      case "seifa": return a.pillars.seifa.score;
      case "growth": return a.market.growth_score;
      case "yield": return a.pillars.yield.score;
      case "zoning": return a.pillars.zoning.score;
      case "transport": return a.transit.score;
      case "schools": return a.schools.score;
      default: return overallOf(a);
    }
  }

  // ---- map --------------------------------------------------------------
  // City-agnostic initial view: derive the study-area bounds from the loaded
  // boundaries instead of hardcoding a centre, so a second city "just works".
  let bW = 180, bS = 90, bE = -180, bN = -90;
  for (const f of geo.features) {
    const g = f.geometry, polys = g.type === "Polygon" ? [g.coordinates] : g.coordinates;
    for (const poly of polys) for (const [x, y] of poly[0]) {
      if (x < bW) bW = x; if (x > bE) bE = x; if (y < bS) bS = y; if (y > bN) bN = y;
    }
  }
  const CITY_BOUNDS = L.latLngBounds([bS, bW], [bN, bE]);
  // Canvas renderer: one bitmap instead of 361+ SVG nodes — much smoother pan/zoom
  const map = L.map("map", { zoomControl: true, preferCanvas: true,
    renderer: L.canvas({ padding: 0.4 }) }).fitBounds(CITY_BOUNDS, { padding: [10, 10] });
  const tilesFor = dark => L.tileLayer(
    `https://{s}.basemaps.cartocdn.com/${dark ? "dark_nolabels" : "light_nolabels"}/{z}/{x}/{y}{r}.png`,
    { subdomains: "abcd", maxZoom: 19, attribution: '&copy; <a href="https://openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/attributions">CARTO</a> · Data: ABS, CSA Vic' });
  let base = tilesFor(document.documentElement.dataset.theme === "dark").addTo(map);
  const labelsFor = dark => L.tileLayer(
    `https://{s}.basemaps.cartocdn.com/${dark ? "dark_only_labels" : "light_only_labels"}/{z}/{x}/{y}{r}.png`,
    { subdomains: "abcd", pane: "markerPane", opacity: .85 });
  let labels = labelsFor(document.documentElement.dataset.theme === "dark");

  const style = f => {
    const code = f.properties.sa2_code;
    const a = A[code]; if (!a) return { fillColor: "#bbb", fillOpacity: .25, weight: .6, color: "rgba(255,255,255,.5)" };
    const v = metricOf(a), sel = code === selected, star = shortlist.has(code);
    // shortlisted suburbs wear a dashed gold outline so they stay findable
    const edge = sel ? { weight: 2.4, color: "#0a84ff" }
      : star ? { weight: 1.8, color: "#ffd60a", dashArray: "4 3" }
      : { weight: .6, color: "rgba(255,255,255,.5)" };
    if (v == null) return { ...edge, fillColor: "#9a9aa0", fillOpacity: .18 };
    // Ask results: matched suburbs paint, everything else fades right back
    const dim = askSet ? !askSet.has(code) : v < minScore;
    return { ...edge, fillColor: col(v), fillOpacity: (sel || !dim) ? .8 : .12 };
  };
  const layer = L.geoJSON(geo, {
    style,
    onEachFeature: (f, lyr) => lyr.on({
      mouseover: e => { hover(f.properties.sa2_code); e.target.setStyle({ weight: 2, color: document.documentElement.dataset.theme === "dark" ? "#f2f2f7" : "#1c1c1e" }); },
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
      <div class="hg"><span>Live ${liveOf(a)}</span><span>Dev ${devOf(a)}</span><span>Overall ${overallOf(a)}</span></div>`;
    hc.classList.remove("hidden");
  }
  const hideHover = () => hc.classList.add("hidden");

  // ---- shortlist (starred suburbs, persisted locally) ---------------------
  function toggleStar(code) {
    shortlist.has(code) ? shortlist.delete(code) : shortlist.add(code);
    saveShortlist(); repaint(); updateLists();
    if (selected === code) renderCard(code);
  }

  // grade movement since the previous data refresh (needs prev-scores.json)
  const GRADE_ORD = { "A+": 5, "A": 4, "B": 3, "C": 2, "D": 1 };
  function gradeTrend(code, g) {
    const was = PREV && PREV.grades && PREV.grades[code];
    if (!was || was === g) return "";
    const up = GRADE_ORD[g] > GRADE_ORD[was];
    return `<span class="gtrend ${up ? "gup" : "gdown"}" title="Was ${was} at the previous data refresh (${PREV.generated || "earlier"})">${up ? "▲" : "▼"}</span>`;
  }

  // ---- scorecard --------------------------------------------------------
  // tinted grade capsule (iOS style): soft background, saturated readable text
  const GRADE_TINT = {
    "A+": ["rgba(52,199,89,.18)", "#1d9a44"], "A": ["rgba(52,199,89,.15)", "#28a04d"],
    "B": ["rgba(255,204,0,.22)", "#9a7b00"], "C": ["rgba(255,149,0,.16)", "#c07000"],
    "D": ["rgba(255,59,48,.14)", "#d63a30"],
  };
  const gradeStyle = g => { const t = GRADE_TINT[g] || ["rgba(142,142,147,.16)", "#8e8e93"]; return `background:${t[0]};color:${t[1]}`; };
  // Apple-style ring gauges for the three headline scores
  const RING_C = 2 * Math.PI * 26;
  const ring = (label, val, color) => `
    <div class="ring" title="${label} ${val} — rank-based: higher than ${Math.round(val)}% of ${data.city}">
      <div class="ring-g"><svg viewBox="0 0 64 64" aria-hidden="true">
        <circle class="ring-track" cx="32" cy="32" r="26"/>
        <circle class="ring-fill" cx="32" cy="32" r="26" stroke="${color}"
          stroke-dasharray="${Math.max(2.5, val / 100 * RING_C).toFixed(1)} ${RING_C.toFixed(1)}"
          transform="rotate(-90 32 32)"/>
      </svg><span class="ring-num">${Math.round(val)}</span></div>
      <span class="ring-lab">${label}</span>
    </div>`;
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
    "Rental turnover": "Share of rented dwellings — investor / tenant activity.",
    "Low density": "People per km² (inverted, so fewer people = more headroom).",
    "Train access": "Distance to the nearest metro/V-Line station, plus how many are within 3 km.",
    "School access": "Distance to the nearest primary and secondary schools, plus choice within 3 km.",
    "Zoning upside": "Share of land zoned for intensification (RGZ, MUZ, ACZ, HCTZ, commercial) vs protective zoning — from Vicmap Planning.",
    "Rental yield": "Gross yield: annual rent ÷ median price. Uses the 2-bed-unit figures where units dominate the stock, else 3-bed house vs house median (which reads low in premium suburbs).",
    "Heritage freedom": "Inverse of Heritage Overlay coverage — heritage controls constrain redevelopment.",
    "Hazard-free": "Inverse of flood (LSIO/SBO/FO) + bushfire (BMO) overlay coverage.",
  };
  const bar = (label, score, valText, sub) =>
    score == null
      ? `<div class="pill${sub ? " sub" : ""} nodata" title="${PILL_TIPS[label] || ""} No data for this area — excluded from the score (weights renormalised).">
          <span class="pl">${label}</span><span class="bar"></span><span class="pv">no data</span></div>`
      : `<div class="pill${sub ? " sub" : ""}" title="${PILL_TIPS[label] || ""}"><span class="pl">${label}</span>
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

  // tiny inline price-history sparkline (VG yearly medians)
  function spark(series) {
    if (!series || series.length < 4) return "";
    const w = 110, h = 30, xs = series.map(p => p[0]), ys = series.map(p => p[1]);
    const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
    const pts = series.map(([x, y]) =>
      `${((x - x0) / (x1 - x0 || 1) * (w - 4) + 2).toFixed(1)},${(h - 3 - (y - y0) / (y1 - y0 || 1) * (h - 8)).toFixed(1)}`).join(" ");
    const up = ys[ys.length - 1] >= ys[0];
    return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" role="img">
      <title>${x0}–${x1} median house price</title><polyline points="${pts}" fill="none"
      stroke="${up ? "var(--good)" : "var(--bad)"}" stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round"/></svg>`;
  }

  function marketBlock(a, prominent) {
    const m = a.market;
    const sig = (label, cls) => `<span class="sig sig-${cls}">${label}</span>`;
    const rentLine = m.rent_weekly ? `Rent ~$${Math.round(m.rent_weekly)}/wk${
        m.rent_12m ? ` (${m.rent_12m >= 0 ? "+" : ""}${m.rent_12m}% 12m)` : ""}${
        m.yield_headline ? ` · ${m.yield_basis === "unit" ? "unit " : ""}yield ≈${m.yield_headline}%` : ""}${
        a.coverage.rent === "lga" ? ` <span class="cov" title="No suburb-level rent series for this area — figure is the ${a.lga} LGA median">LGA-level</span>` : ""}` : "";
    if (!m.median_house)
      return `<div class="market mini"><div class="market-h">Market &amp; Price</div>
        <p class="market-note">No Valuer-General sale medians for this area (often non-residential).</p>
        ${rentLine ? `<div class="market-sub">${rentLine}</div>` : ""}</div>`;
    const up = (m.house_12m ?? 0) >= 0;
    return `<div class="market${prominent ? "" : " mini"}">
      <div class="market-h">Market &amp; Price <span class="src">${[
        m.house_year ? `VG ${m.house_year}` : "",
        m.rent_quarter ? `${data.state === "VIC" ? "DFFH" : "Bonds"} ${m.rent_quarter}` : "",
      ].filter(Boolean).join(" · ")}</span></div>
      <div class="market-row">
        <div class="price"><span class="ml">Median house</span><span class="pv-big">${money(m.median_house)}</span></div>
        ${spark(m.house_series)}
        <div class="growth" style="color:${up ? "var(--good)" : "var(--bad)"}">${up ? IC.up : IC.down} ${m.house_12m ?? "–"}% <small>12m</small></div>
      </div>
      <div class="market-sub">
        ${m.median_unit ? `Unit ${money(m.median_unit)}${m.unit_12m != null ? ` (${m.unit_12m >= 0 ? "+" : ""}${m.unit_12m}% 12m)` : ""} · ` : ""}3-yr ${m.house_3yr_cagr ?? "–"}%/yr
        ${sig(m.growth_signal + " growth", m.growth_signal.toLowerCase())}${m.value_signal ? sig(m.value_signal, "val") : ""}${m.yield_signal ? sig(m.yield_signal, m.yield_house >= 4.2 ? "strong" : m.yield_house >= 3.2 ? "moderate" : "soft") : ""}
      </div>
      ${m.afford_ratio ? `<div class="market-sub" title="Median house price ÷ median annual household income for this suburb (ABS Census 2021 income, indexed). ${data.city} median is around ${data.afford_median || 10}×.">Affordability ≈ <b>${m.afford_ratio}×</b> local household income${m.income_weekly ? ` · income ~$${Math.round(m.income_weekly).toLocaleString()}/wk` : ""}</div>` : ""}
      ${rentLine ? `<div class="market-sub">${rentLine}</div>` : ""}
      ${prominent && explOf(a).invest ? `<p class="market-note">${explOf(a).invest}</p>` : ""}</div>`;
  }

  const IC = {
    fam: '<svg class="ic ic-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="9" cy="8" r="3"/><path d="M3.6 19a5.4 5.4 0 0 1 10.8 0"/><path d="M16 6.6a3 3 0 0 1 0 5.8M17.4 14a5 5 0 0 1 3 4.6"/></svg>',
    train: '<svg class="ic ic-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="6" y="3" width="12" height="13" rx="2.5"/><path d="M6 10h12M9.5 16 7 20M14.5 16 17 20"/><circle cx="9.5" cy="13" r=".6" fill="currentColor"/><circle cx="14.5" cy="13" r=".6" fill="currentColor"/></svg>',
    school: '<svg class="ic ic-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m12 4 9 4.5-9 4.5-9-4.5z"/><path d="M6.5 10.8V16c0 1.2 2.5 2.5 5.5 2.5s5.5-1.3 5.5-2.5v-5.2"/></svg>',
    drop: '<svg class="ic ic-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round" aria-hidden="true"><path d="M12 3.5c3.1 4.1 6 7.4 6 10.5a6 6 0 1 1-12 0c0-3.1 2.9-6.4 6-10.5Z"/></svg>',
    flame: '<svg class="ic ic-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3c.5 3-1.4 4.7-2.9 6.3C7.7 10.8 7 12.3 7 14a5 5 0 0 0 10 0c0-1.5-.5-2.9-1.4-4.1-.5 1-1.2 1.7-2.1 2.1.5-2.8-.2-6.2-1.5-9Z"/></svg>',
    cmp: '<svg class="ic ic-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 7H7M10 4 7 7l3 3M4 17h13M14 14l3 3-3 3"/></svg>',
    up: '<svg class="ic ic-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 19V5M6 11l6-6 6 6"/></svg>',
    down: '<svg class="ic ic-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 5v14M6 13l6 6 6-6"/></svg>',
  };

  const paxFmt = p => p == null ? "" : p >= 1e6 ? `${(p / 1e6).toFixed(1)}M trips/yr` : `${Math.round(p / 1e3)}k trips/yr`;
  function transitBlock(a, prominent) {
    const t = a.transit, s = a.schools;
    if (t.nearest_station_km == null && s.nearest_primary_km == null) return "";
    const line = (badge, cls, nm, km, pax, cap) => (nm && km != null && km <= cap)
      ? `<div class="trow"><span class="tbadge ${cls}">${badge}</span>
          <span class="tnm">${nm}</span>
          <span class="tkm">${km} km</span>
          <span class="tpax">${paxFmt(pax)}</span></div>` : "";
    const metro = line("M", "tb-m", t.metro && t.metro.station, t.metro && t.metro.km, t.metro && t.metro.pax, 30);
    const vline = line("V", "tb-v", t.vline && t.vline.station, t.vline && t.vline.km, t.vline && t.vline.pax, 45);
    const near = t.stations_3km > 1 ? `<div class="market-sub">${t.stations_3km} stations within 3 km</div>` : "";
    const sch = s.nearest_primary_km != null
      ? `<div class="market-sub icrow">${IC.school} primary ~${s.nearest_primary_km} km · secondary ~${s.nearest_secondary_km ?? "—"} km · ${s.schools_3km} schools &lt;3 km</div>`
      : "";
    return `<div class="market${prominent ? "" : " mini"}">
      <div class="market-h">Trains &amp; Schools <span class="src">DTP FY24-25 · DE 2025</span></div>
      ${metro}${vline}${near}${sch}</div>`;
  }

  function zoningBlock(a, prominent) {
    const z = a.zoning;
    if (!z) return `<div class="market mini"><div class="market-h">Planning &amp; Zoning</div>
      <p class="market-note">No zoning sample for this area.</p></div>`;
    const mix = (z.zone_mix || []).slice(0, 3).map(([c, s]) =>
      `<span class="sig sig-val" title="${ZONE_NAMES[c] || c}">${c} ${Math.round(s * 100)}%</span>`).join("");
    const her = z.heritage_share >= 0.03
      ? `<span class="sig ${z.heritage_share >= 0.25 ? "sig-soft" : "sig-moderate"}">Heritage ${Math.round(z.heritage_share * 100)}%</span>` : "";
    const flood = (z.flood_share || 0) >= 0.03
      ? `<span class="sig sig-risk" title="Share of sampled land under a flood overlay (LSIO / SBO / FO) — check before buying or building">${IC.drop} Flood ${Math.round(z.flood_share * 100)}%</span>` : "";
    const fire = (z.bushfire_share || 0) >= 0.03
      ? `<span class="sig sig-risk" title="Share of sampled land under the Bushfire Management Overlay">${IC.flame} Bushfire ${Math.round(z.bushfire_share * 100)}%</span>` : "";
    return `<div class="market${prominent ? "" : " mini"}">
      <div class="market-h">Planning, Zoning &amp; Hazards <span class="src">VicPlan</span></div>
      <div class="market-sub"><span class="sig sig-${z.growth_share >= 0.2 ? "strong" : z.restrict_share >= 0.5 ? "soft" : "moderate"}">${z.label}</span>${mix}${her}</div>
      ${flood || fire ? `<div class="market-sub">${flood}${fire}</div>` : ""}
      ${prominent && z.growth_share >= 0.2 ? `<p class="market-note">${Math.round(z.growth_share * 100)}% of sampled land is zoned for intensification — a genuine planning tailwind.</p>` : ""}</div>`;
  }
  const ZONE_NAMES = {
    GRZ: "General Residential", NRZ: "Neighbourhood Residential (restrictive)",
    RGZ: "Residential Growth", MUZ: "Mixed Use", ACZ: "Activity Centre",
    HCTZ: "Housing Choice & Transport (new activity-centre zone)", UGZ: "Urban Growth precinct",
    LDRZ: "Low Density Residential", TZ: "Township", C1Z: "Commercial 1", CCZ: "Capital City",
    PPRZ: "Public Park & Recreation", PUZ: "Public Use", TRZ: "Transport", SUZ: "Special Use",
    GWZ: "Green Wedge", GWAZ: "Green Wedge A", RCZ: "Rural Conservation", FZ: "Farming",
    PCRZ: "Public Conservation", IN1Z: "Industrial 1", IN2Z: "Industrial 2", IN3Z: "Industrial 3",
  };
  function renderCard(code) {
    const a = A[code]; if (!a) return;
    if (compareWith) {
      const others = compareWith.filter(c => c !== code);
      if (others.length) return renderCompare(code, others);
      compareWith = null;                  // compared against itself — drop out
    }
    const p = a.pillars, m = a.market, lv = liveOf(a), ov = overallOf(a);
    const prominent = mode !== "live";          // price leads in Balanced/Invest, light in Live
    const chips = [`<span class="chip fam">${IC.fam} ${a.family.label} ${a.family.score}</span>`]
      .concat(a.tags.filter(t => t !== "Grid-ready").map(t => `<span class="chip">${t}</span>`)).join("");
    const liveLab = mode === "live" ? "Liveability ·family" : "Liveability";
    sc.classList.remove("empty");
    sc.innerHTML = `
      <div class="sc-head">
        <div><h2 class="sc-name">${a.name}</h2>
          <p class="sc-sub">${a.sa3 || ""} · ${a.lga || ""}${a.population ? " · pop " + a.population.toLocaleString() +
            (a.pop_growth_pct != null ? ` <span class="popg" title="Estimated resident population change over the last year (ABS ERP)">${a.pop_growth_pct >= 0 ? "+" : ""}${a.pop_growth_pct}%/yr</span>` : "") : ""}</p></div>
        <div class="sc-badges">
          <button class="star-btn${shortlist.has(code) ? " on" : ""}" id="starBtn"
            title="${shortlist.has(code) ? "Remove from" : "Add to"} your shortlist (saved on this device; outlined in gold on the map)"
            aria-label="Toggle shortlist">${shortlist.has(code) ? "★" : "☆"}</button>
          <span class="grade" title="Relative tier of the Overall score at the default blend: A+ = top ~10% of ${data.city}.${customW ? " Grades keep the default weighting — your custom weights change the scores, not the letter." : ""}" style="${gradeStyle(a.grade)}">${a.grade}${gradeTrend(code, a.grade)}</span>
        </div>
      </div>
      <div class="chips">${chips}</div>
      <p class="bestfor"><b>Best for:</b> ${bestFor(a)}.
        <button class="cmp-btn" id="cmpBtn" title="Compare this suburb side-by-side with another">${IC.cmp} Compare</button></p>
      ${comparePicking ? `<p class="cmp-hint">Now tap a second suburb on the map, list or search…
        <button class="cmp-x" id="cmpCancel">cancel</button></p>` : ""}
      <div class="rings">
        ${ring(liveLab + (customW ? " · custom" : ""), lv, rampColor(lv, "balanced"))}
        ${ring("Development" + (customW ? " · custom" : ""), devOf(a), rampColor(devOf(a), "balanced"))}
        ${ring("Overall", ov, rampColor(ov, "balanced"))}
      </div>
      ${prominent ? `<div class="sublens" title="Two different development stories: Greenfield = estate-scale corridor build-out (UGZ precincts); Infill = upzoned, station-centred redevelopment in established suburbs.">
        <span>Greenfield <b style="color:${col(a.dev_green)}">${a.dev_green}</b></span>
        <span>Infill <b style="color:${col(a.dev_infill)}">${a.dev_infill}</b></span></div>` : ""}
      ${prominent ? marketBlock(a, true) + zoningBlock(a, true) + transitBlock(a, false) : ""}
      <div class="pgroup-h">Liveability — safety &amp; stability</div>
      ${bar("Personal safety", p.person_safety.score, p.person_safety.raw == null ? "—" : Math.round(p.person_safety.raw).toLocaleString() + "/100k")}
      ${bar("Socio-economic", p.seifa.score, "decile " + (p.seifa.decile ?? "—") + "/10")}
      ${bar("Train access", p.transport.score, p.transport.raw == null ? "—" : p.transport.raw + " km")}
      ${bar("School access", p.schools.score, p.schools.raw == null ? "—" : p.schools.raw + " km")}
      ${bar("Children 0–14", p.child.score, pct(p.child.raw))}
      ${bar("Owner-occupied", p.owner_occ.score, pct(p.owner_occ.raw))}
      ${bar("Property safety", p.property_safety.score, p.property_safety.raw == null ? "—" : Math.round(p.property_safety.raw).toLocaleString() + "/100k", true)}
      ${bar("Low social housing", p.low_social.score, pct(p.low_social.raw) + " social", true)}
      <div class="pgroup-h">Development potential</div>
      ${bar("Detached headroom", p.detached.score, pct(p.detached.raw))}
      ${bar("Zoning upside", p.zoning.score, a.zoning ? a.zoning.label : "n/a")}
      ${bar("Recent growth", m.growth_score, m.house_3yr_cagr == null ? "n/a" : m.house_3yr_cagr + "%/yr")}
      ${bar("Rental yield", p.yield.score, p.yield.raw == null ? "n/a" : p.yield.raw + "%" + (m.yield_basis === "unit" ? " unit" : ""))}
      ${bar("Rental turnover", p.rental.score, pct(p.rental.raw), true)}
      ${bar("Low density", p.low_density.score, p.low_density.raw == null ? "—" : Math.round(p.low_density.raw).toLocaleString() + "/km²", true)}
      ${bar("Heritage freedom", p.heritage_free.score, p.heritage_free.raw == null ? "n/a" : Math.round(p.heritage_free.raw * 100) + "% HO", true)}
      ${bar("Hazard-free", p.hazard_free.score, p.hazard_free.raw == null ? "n/a" : Math.round(p.hazard_free.raw * 100) + "% overlay", true)}
      ${explOf(a).live ? `<p class="summary">${explOf(a).live}</p>` : ""}
      ${explOf(a).dev ? `<p class="summary dev">${explOf(a).dev}</p>` : ""}
      ${prominent ? "" : marketBlock(a, false) + zoningBlock(a, false) + transitBlock(a, false)}
      ${coverageNote(a)}`;
    const cb = document.getElementById("cmpBtn");
    if (cb) cb.onclick = () => { comparePicking = true; renderCard(code); };
    const cc = document.getElementById("cmpCancel");
    if (cc) cc.onclick = () => { comparePicking = false; renderCard(code); };
    const sb = document.getElementById("starBtn");
    if (sb) sb.onclick = () => toggleStar(code);
    sc.classList.remove("pop"); void sc.offsetWidth; sc.classList.add("pop");  // re-trigger fade-in
  }

  // ---- compare mode (2- or 3-way) ------------------------------------------
  let compareWith = null;          // array of 1-2 other SA2 codes, or null
  let comparePicking = false;      // next map/list tap becomes a comparison column
  function renderCompare(codeA, others) {
    const cols = [codeA, ...others].map(c => A[c]).filter(Boolean);
    if (cols.length < 2) return;
    const three = cols.length === 3;
    // winner class per column: best numeric value wins (lowerBetter flips it)
    const win = (vals, lowerBetter) => {
      const nums = vals.map(v => (v == null ? null : +v));
      const ok = nums.filter(v => v != null);
      if (ok.length < 2) return vals.map(() => "");
      const best = lowerBetter ? Math.min(...ok) : Math.max(...ok);
      if (ok.every(v => v === best)) return vals.map(() => "");
      return nums.map(v => (v === best ? "win" : ""));
    };
    const row = (label, vals, cls, tip = "") =>
      `<div class="cmp-row${three ? " c3" : ""}" title="${tip}"><span class="cmp-l">${label}</span>` +
      vals.map((v, i) => `<span class="cmp-v ${(cls || [])[i] || ""}">${(cls || [])[i] === "win" ? "✓ " : ""}${v ?? "—"}</span>`).join("") + `</div>`;
    const nrow = (label, raw, fmt, lowerBetter, tip) =>
      row(label, raw.map(v => (v == null ? null : fmt(v))), win(raw, lowerBetter), tip);
    const lv = cols.map(liveOf), dv = cols.map(devOf), ov = cols.map(overallOf);
    sc.classList.remove("empty");
    sc.innerHTML = `
      <div class="sc-head cmp-head">
        <div><h2 class="sc-name">Compare</h2>
          <p class="sc-sub">${cols.map(c => c.name).join(" vs ")}</p></div>
        <button class="cmp-x big" id="cmpExit" title="Exit compare">×</button>
      </div>
      <div class="cmp-row cmp-titles${three ? " c3" : ""}"><span class="cmp-l"></span>
        ${cols.map(c => `<span class="cmp-v"><b>${c.name}</b><span class="grade gmini" style="${gradeStyle(c.grade)}">${c.grade}</span></span>`).join("")}</div>
      <div class="cmp-row${three ? " c3" : ""}"><span class="cmp-l">Price history</span>
        ${cols.map(c => `<span class="cmp-v">${spark(c.market.house_series) || "—"}</span>`).join("")}</div>
      ${nrow("Liveability", lv, v => v)}
      ${nrow("Development", dv, v => v)}
      ${row("Greenfield / Infill", cols.map(c => `${c.dev_green} / ${c.dev_infill}`))}
      ${nrow("Overall (your blend)", ov, v => v)}
      ${nrow("Family suitability", cols.map(c => c.family.score), v => v)}
      ${nrow("Personal safety", cols.map(c => c.pillars.person_safety.score), v => v, false, "percentile — higher = safer")}
      ${nrow("SEIFA decile", cols.map(c => c.pillars.seifa.decile), v => v)}
      ${nrow("Median house", cols.map(c => c.market.median_house), money)}
      ${nrow("Rent / week", cols.map(c => c.market.rent_weekly), v => "$" + Math.round(v))}
      ${(() => {                       // per-column basis, no winner across mixed bases
        const yv = cols.map(c => c.market.yield_headline ?? c.market.yield_house);
        const unit = cols.map(c => c.market.yield_basis === "unit");
        const cls = unit.every(u => u === unit[0]) ? win(yv, false) : yv.map(() => "");
        return row("Gross yield", yv.map((v, i) => v == null ? null : v + "%" + (unit[i] ? " unit" : "")),
          cls, "same basis as the scorecard — unit yield where units dominate the stock; no winner is marked when columns use different bases");
      })()}
      ${nrow("3-yr growth", cols.map(c => c.market.house_3yr_cagr), v => v + "%/yr")}
      ${nrow("Affordability", cols.map(c => c.market.afford_ratio), v => v + "× income", true, "median house ÷ median household income — lower is more affordable")}
      ${nrow("Nearest station", cols.map(c => c.transit.nearest_station_km), v => v + " km", true)}
      ${row("Zoning", cols.map(c => (c.zoning ? c.zoning.label : null)))}
      ${!three ? `<button class="cmp-btn cmp-add" id="cmpAdd" title="Add a third column">+ Add a third suburb</button>` : ""}
      ${comparePicking ? `<p class="cmp-hint">Now tap another suburb on the map, list or search…
        <button class="cmp-x" id="cmpCancel2">cancel</button></p>` : ""}
      <p class="covnote">✓ marks the strongest column in each row. Tap × to go back to the full scorecard.</p>`;
    document.getElementById("cmpExit").onclick = () => { compareWith = null; comparePicking = false; renderCard(selected); writeHash(); };
    const ca = document.getElementById("cmpAdd");
    if (ca) ca.onclick = () => { comparePicking = true; renderCompare(codeA, others); };
    const cc2 = document.getElementById("cmpCancel2");
    if (cc2) cc2.onclick = () => { comparePicking = false; renderCompare(codeA, others); };
    sc.classList.remove("pop"); void sc.offsetWidth; sc.classList.add("pop");
  }

  function coverageNote(a) {
    const c = a.coverage, notes = [];
    notes.push(c.crime === "suburb" ? "crime: suburb-level" : "crime: LGA-level");
    if (c.rent === "lga") notes.push("rent: LGA-level");
    else if (!c.rent) notes.push("rent: no data");
    if (!c.price) notes.push("price: no VG match");
    if (!c.zoning) notes.push("zoning: no sample");
    const li = c.live_inputs, di = c.dev_inputs;
    if (li && li[0] < li[1]) notes.push(`liveability scored on ${li[0]}/${li[1]} inputs`);
    if (di && di[0] < di[1]) notes.push(`development scored on ${di[0]}/${di[1]} inputs`);
    return `<p class="covnote" title="How fine-grained each source is for this exact area. Missing inputs are excluded and the remaining weights renormalised — they never count as 'average'.">Data coverage — ${notes.join(" · ")}</p>`;
  }

  function select(code, fly) {
    infopanel.classList.remove("peek");       // picking a suburb re-opens a pushed-down sheet
    if (comparePicking && selected && code !== selected) {
      comparePicking = false;
      compareWith = [...(compareWith || []), code]
        .filter((c, i, arr) => c !== selected && arr.indexOf(c) === i).slice(0, 2);
      repaint(); renderCompare(selected, compareWith); writeHash();
      document.getElementById("srlive").textContent =
        `Comparing ${A[selected].name} with ${compareWith.map(c => A[c].name).join(" and ")}.`;
      return;
    }
    // navigating to a suburb the min-score filter is hiding: drop the filter so
    // the searched area and its surroundings show their colours
    const mv = A[code] ? metricOf(A[code]) : null;
    if (fly && minScore > 0 && mv != null && mv < minScore) {
      minScore = 0; activeBest = null; setMinSlider(); highlightBest();
    }
    selected = code; repaint();
    renderCard(code);                       // delegates to compare view if active
    const a = A[code];                      // announce for screen readers (map polygons aren't focusable)
    if (a) document.getElementById("srlive").textContent =
      `${a.name} selected. Liveability ${Math.round(liveOf(a))}, development ${Math.round(devOf(a))}, overall ${Math.round(overallOf(a))}, grade ${a.grade}.`;
    document.title = A[code] ? `${A[code].name} — Melbourne Property` : "Melbourne Property";
    writeHash();
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
    activeBest = null; minScore = 0; askSet = null;
    wLive = MODE_PRESETS[m]; colorBy = MODE_COLORBY[m];
    setSlider(); setMinSlider(); highlightModes(); refresh();
  }
  document.querySelectorAll("#modeSeg button").forEach(b => b.onclick = () => setMode(b.dataset.mode));

  // presets live in a collapsed-by-default disclosure; remember the choice
  const presetsBox = document.getElementById("presetsBox");
  presetsBox.open = localStorage.getItem("presetsOpen") === "1";
  presetsBox.addEventListener("toggle",
    () => localStorage.setItem("presetsOpen", presetsBox.open ? "1" : "0"));

  const presetRow = document.getElementById("presetRow");
  presetRow.innerHTML = PRESETS.map(p =>
    `<button class="preset p-${p.key}" data-key="${p.key}" title="${p.blurb}">
       <span class="pt">${p.label}</span><span class="pp">${p.live}% liveability</span></button>`).join("");
  presetRow.querySelectorAll(".preset").forEach(btn => btn.onclick = () => {
    const p = PRESETS.find(x => x.key === btn.dataset.key);
    activePreset = p.key; activeBest = null; minScore = 0; askSet = null;
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
  // rAF throttle: sliders fire dozens of events per second — repaint at most once a frame
  let rafId = 0;
  const scheduleRefresh = () => { if (!rafId) rafId = requestAnimationFrame(() => { rafId = 0; refresh(); }); };
  let rafPaint = 0;
  const schedulePaint = () => { if (!rafPaint) rafPaint = requestAnimationFrame(() => { rafPaint = 0; repaint(); highlightBest(); writeHash(); }); };
  blend.oninput = () => { wLive = blend.value / 100; activePreset = null; activeBest = null; setSlider(); scheduleRefresh(); };
  minScore$.oninput = () => { minScore = +minScore$.value; activeBest = null; askSet = null; document.getElementById("minVal").textContent = minScore; schedulePaint(); };

  // colour-by toggle chips (one tap to colour the map by a single layer)
  const CBY_TIPS = {
    overall: "Blend of Liveability and Development (set by the slider).",
    live: "How good it is to live or rent here now.", dev: "Room to invest, build or subdivide.",
    greenfield: "Estate-scale corridor development: UGZ precincts, land headroom, momentum.",
    infill: "Established-area uplift: upzoned land (RGZ/HCTZ/ACZ) near stations, heritage-light.",
    safety: "Personal-crime rate — greener = lower.", seifa: "ABS socio-economic advantage.",
    family: "Family-suitability score.", growth: "Recent 3-year price growth.",
    yield: "Gross rental yield (unit yield where units dominate).",
    zoning: "Zoned-for-growth share vs protective zoning (Vicmap).",
    transport: "Train-station access from residential land.",
    schools: "Primary/secondary school access from residential land.",
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
    mode = b.mode; colorBy = b.colorBy; wLive = b.wLive; activePreset = null; activeBest = kind; askSet = null;
    setSlider();
    const ranked = entries.slice().sort((x, y) => metricRank(y[1]) - metricRank(x[1]));
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
    document.getElementById("weightsBtn").classList.toggle("on", !!customW);
    if (selected) renderCard(selected);
    writeHash();
  }

  const BEST_LABEL = { live: "Best to live", invest: "Best to invest", develop: "Best to develop" };
  function updateActiveCaption() {
    const el = document.getElementById("activePreset");
    const p = PRESETS.find(x => x.key === activePreset);
    const cw = customW ? ` · <b>custom weights</b>` : "";
    el.innerHTML = (askSet ? `Showing <b>${askSet.size} Ask matches</b> <button class="cmp-x" id="askClear">clear</button>`
      : activeBest ? `Showing <b>${BEST_LABEL[activeBest]}</b> — top ~20 areas highlighted`
      : p ? `Preset: <b>${p.label}</b> — ${p.blurb}`
        : `Custom blend · <b>${Math.round(wLive * 100)}%</b> liveability`) + cw;
    const ac = el.querySelector("#askClear");
    if (ac) ac.onclick = () => { askSet = null; refresh(); };
  }

  // ---- legend + lists ---------------------------------------------------
  const LABELS = {
    overall: "Overall", live: "Liveability", dev: "Development", family: "Family suitability",
    greenfield: "Greenfield potential", infill: "Infill potential",
    safety: "Safety (low crime)", seifa: "Socio-economic", growth: "Price growth",
    yield: "Rental yield", zoning: "Zoning upside", transport: "Train access",
    schools: "School access",
  };
  const LEGEND_DESC = {
    overall: "Blend of liveability & development", live: "How good it is to live or rent here",
    dev: "Room to build, invest or subdivide", safety: "Lower personal-crime rate",
    greenfield: "Estate-scale corridor development potential",
    infill: "Upzoned, station-centred redevelopment potential",
    seifa: "Socio-economic advantage", family: "How suitable for families",
    growth: "Recent 3-year price growth", yield: "Gross rental yield",
    zoning: "Land zoned to grow vs protected", transport: "Train-station access",
    schools: "School access",
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
  const metricRank = a => { const v = metricOf(a); return v == null ? -1 : v; };  // null sorts last
  function updateLists() {
    document.getElementById("listLabel").textContent = LABELS[colorBy];
    const top = entries.slice().sort((x, y) => metricRank(y[1]) - metricRank(x[1])).slice(0, 12);
    const list = document.getElementById("topList");
    const starRows = [...shortlist].filter(c => A[c]).map(c =>
      `<li class="sl" data-code="${c}" tabindex="0"><span class="rk sl-star">★</span><span class="nm">${A[c].name}</span>
        <span class="sv" style="color:${col(metricOf(A[c]) ?? 50)}">${metricOf(A[c]) ?? "—"}</span></li>`).join("");
    list.innerHTML =
      (starRows ? `<li class="sl-h" aria-hidden="true">Your shortlist</li>${starRows}
        <li class="sl-h" aria-hidden="true">Top by ${LABELS[colorBy]}</li>` : "") +
      top.map(([code, a], i) =>
        `<li data-code="${code}" tabindex="0"><span class="rk">${i + 1}</span><span class="nm">${a.name}</span>
          <span class="sv" style="color:${col(metricOf(a))}">${metricOf(a)}</span></li>`).join("");
    list.querySelectorAll("li[data-code]").forEach(li => {
      li.onclick = () => select(li.dataset.code, true);
      li.onkeydown = e => {                 // keyboard: Enter/Space selects
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); select(li.dataset.code, true); }
      };
    });
  }

  // ---- footer build line + guide freshness line ---------------------------
  document.getElementById("genline").textContent = `${data.count} suburbs · built ${data.generated}`;
  const builtDays = Math.max(0, Math.round((Date.now() - new Date(data.generated + "T00:00:00")) / 864e5));
  const builtAgo = builtDays < 1 ? "today" : builtDays < 14 ? `${builtDays} day${builtDays === 1 ? "" : "s"} ago`
    : builtDays < 70 ? `${Math.round(builtDays / 7)} weeks ago` : `${Math.round(builtDays / 30)} months ago`;
  document.getElementById("freshline").innerHTML =
    `<strong>Data last built ${data.generated}</strong> (${builtAgo}). The dataset refreshes automatically in the first week of each month; grade arrows on scorecards show movement since the previous refresh.`;

  // ---- shareable URL state ------------------------------------------------
  let hashReady = false, lastHash = "";
  function writeHash() {
    if (!hashReady) return;
    const p = new URLSearchParams();
    if (citySlug !== (CITIES.default || CITIES.cities[0].slug)) p.set("city", citySlug);
    if (selected) p.set("s", selected);
    if (compareWith && compareWith.length) p.set("vs", compareWith.join("~"));
    p.set("m", mode); p.set("w", Math.round(wLive * 100));
    if (colorBy !== "overall") p.set("c", colorBy);
    if (minScore > 0) p.set("min", Math.round(minScore));
    if (customW) {
      p.set("lw", Object.keys(W_INPUTS.live).map(k => customW.live[k] || 0).join("."));
      p.set("dw", Object.keys(W_INPUTS.dev).map(k => customW.dev[k] || 0).join("."));
    }
    const h = "#" + p.toString();
    if (h === lastHash) return;              // replaceState is rate-limited in some browsers
    lastHash = h;
    history.replaceState(null, "", h);
  }
  function readHash() {
    const h = location.hash.replace(/^#/, "");
    if (!h) return false;
    const p = new URLSearchParams(h);
    if (p.get("m") && MODE_PRESETS[p.get("m")] != null) mode = p.get("m");
    if (p.get("w") != null && !isNaN(+p.get("w"))) wLive = Math.max(0, Math.min(100, +p.get("w"))) / 100;
    if (p.get("c") && COLORBY.some(([k]) => k === p.get("c"))) colorBy = p.get("c");
    if (p.get("min") != null) minScore = Math.max(0, Math.min(90, +p.get("min") || 0));
    if (p.get("vs")) {
      const vs = p.get("vs").split("~").filter(c => A[c]).slice(0, 2);
      compareWith = vs.length ? vs : null;
    }
    if (p.get("lw") && p.get("dw")) {           // restore shared custom weights
      const parse = (kind, str) => {
        const vals = str.split(".").map(v => Math.max(0, Math.min(50, +v || 0)));
        const out = {};
        Object.keys(W_INPUTS[kind]).forEach((k, i) => out[k] = vals[i] ?? 0);
        return out;
      };
      customW = { live: parse("live", p.get("lw")), dev: parse("dev", p.get("dw")) };
      recomputeCustom();
    }
    return p.get("s") && A[p.get("s")] ? p.get("s") : true;
  }

  // ---- custom weights (client-side re-scoring) ----------------------------
  // All pillar percentiles ship in scores.json, so users can rebuild the Live
  // and Development scores with their own weights. Raw weighted averages are
  // re-ranked to 0-100 (same stretch the engine applies), nulls renormalised.
  const W_INPUTS = {
    live: {
      person_safety: a => a.pillars.person_safety.score,
      seifa: a => a.pillars.seifa.score,
      transport: a => a.transit.score,
      owner_occ: a => a.pillars.owner_occ.score,
      schools: a => a.schools.score,
      property_safety: a => a.pillars.property_safety.score,
      family_child: a => a.pillars.child.score,
      hazard_free: a => a.pillars.hazard_free ? a.pillars.hazard_free.score : null,
    },
    dev: {
      detached_share: a => a.pillars.detached.score,
      zoning: a => a.pillars.zoning.score,
      growth: a => a.market.growth_score,
      infra: a => a.infra.score,
      station: a => a.transit.score,
      yield: a => a.pillars.yield.score,
      rental_share: a => a.pillars.rental.score,
      low_density: a => a.pillars.low_density.score,
      heritage_free: a => a.pillars.heritage_free.score,
      hazard_free: a => a.pillars.hazard_free ? a.pillars.hazard_free.score : null,
    },
  };
  const W_LABELS = {
    person_safety: "Personal safety", seifa: "Socio-economic", transport: "Train access",
    owner_occ: "Owner-occupied", schools: "School access", property_safety: "Property safety",
    family_child: "Children 0–14", hazard_free: "Hazard-free (flood/fire)",
    detached_share: "Detached headroom", zoning: "Zoning upside", growth: "Price growth",
    infra: "Grid support", station: "Station proximity", yield: "Rental yield",
    rental_share: "Rental turnover", low_density: "Low density", heritage_free: "Heritage freedom",
  };
  const defaultW = kind => {
    const src = kind === "live" ? (data.weights || {}).liveability : (data.weights || {}).development;
    const out = {};
    Object.keys(W_INPUTS[kind]).forEach(k => out[k] = Math.round(((src || {})[k] || 0) * 100));
    return out;
  };
  function stretchRanks(raw) {                   // Map code -> raw, ranked to 0-100
    const vals = [...raw.entries()].filter(([, v]) => v != null).sort((x, y) => x[1] - y[1]);
    const m = new Map();
    vals.forEach(([c], i) => m.set(c, Math.round((i + 0.5) / vals.length * 1000) / 10));
    raw.forEach((v, c) => { if (!m.has(c)) m.set(c, 50); });
    return m;
  }
  function recomputeCustom() {
    if (!customW) { custLive = custDev = null; return; }
    const calc = kind => {
      const raw = new Map();
      for (const a of Object.values(A)) {
        let s = 0, w = 0;
        for (const [k, get] of Object.entries(W_INPUTS[kind])) {
          const v = get(a), wt = customW[kind][k] || 0;
          if (v != null && wt > 0) { s += v * wt; w += wt; }
        }
        raw.set(a._c, w > 0 ? s / w : null);
      }
      return stretchRanks(raw);
    };
    custLive = calc("live"); custDev = calc("dev");
  }

  const wModal = document.getElementById("weightsModal");
  function buildWeightRows() {
    for (const kind of ["live", "dev"]) {
      const box = document.getElementById(kind === "live" ? "wLiveRows" : "wDevRows");
      const cur = (customW && customW[kind]) || defaultW(kind);
      box.innerHTML = Object.keys(W_INPUTS[kind]).map(k =>
        `<label class="wrow"><span>${W_LABELS[k]}</span>
          <input type="range" min="0" max="50" value="${cur[k] ?? 0}" data-kind="${kind}" data-k="${k}" />
          <b>${cur[k] ?? 0}</b></label>`).join("");
    }
    wModal.querySelectorAll("input[type=range]").forEach(sl => sl.oninput = () => {
      sl.nextElementSibling.textContent = sl.value;
      if (!customW) customW = { live: defaultW("live"), dev: defaultW("dev") };
      customW[sl.dataset.kind][sl.dataset.k] = +sl.value;
      recomputeCustom(); scheduleRefresh();
    });
  }
  function openWeights() {
    buildWeightRows();
    wModal.classList.remove("hidden"); wModal.setAttribute("aria-hidden", "false");
  }
  const closeWeights = () => { wModal.classList.add("hidden"); wModal.setAttribute("aria-hidden", "true"); };
  document.getElementById("weightsBtn").onclick = openWeights;
  document.getElementById("closeWeights").onclick = closeWeights;
  document.getElementById("resetWeights").onclick = () => {
    customW = null; recomputeCustom(); buildWeightRows(); refresh();
  };
  wModal.onclick = e => { if (e.target === wModal) closeWeights(); };

  // ---- point-in-SA2 lookup (for address search) ---------------------------
  function inRing(x, y, ring) {
    let inside = false;
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const xi = ring[i][0], yi = ring[i][1], xj = ring[j][0], yj = ring[j][1];
      if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) inside = !inside;
    }
    return inside;
  }
  function sa2At(lon, lat) {
    for (const f of geo.features) {
      const g = f.geometry, polys = g.type === "Polygon" ? [g.coordinates] : g.coordinates;
      for (const poly of polys)
        if (inRing(lon, lat, poly[0]) && !poly.slice(1).some(h => inRing(lon, lat, h)))
          return f.properties.sa2_code;
    }
    return null;
  }
  let addrMarker = null;
  async function searchAddress(q) {
    try {
      const vb = CITY_BOUNDS.pad(0.05);   // geocode only inside the study area
      const url = "https://nominatim.openstreetmap.org/search?format=json&limit=1&countrycodes=au" +
        `&viewbox=${vb.getWest().toFixed(2)},${vb.getNorth().toFixed(2)},${vb.getEast().toFixed(2)},${vb.getSouth().toFixed(2)}` +
        "&bounded=1&q=" + encodeURIComponent(q);
      const res = await fetch(url, { headers: { "Accept-Language": "en" } }).then(r => r.json());
      if (!res.length) { toast(`Couldn't find that address inside ${data.city}.`); return; }
      const lat = +res[0].lat, lon = +res[0].lon;
      const code = sa2At(lon, lat);
      if (!code) { toast(`That point is outside the ${data.city} study area.`); return; }
      if (addrMarker) map.removeLayer(addrMarker);
      addrMarker = L.marker([lat, lon], { title: res[0].display_name }).addTo(map)
        .bindPopup(res[0].display_name.split(",").slice(0, 3).join(",")).openPopup();
      select(code, true);
    } catch (e) { toast("Address lookup failed — try again in a moment."); }
  }

  // ---- search (suburbs + addresses) ---------------------------------------
  const search = document.getElementById("search"), results = document.getElementById("results");
  const topbar = document.getElementById("topbar");
  const closeSearch = () => { topbar.classList.remove("search-open"); results.innerHTML = ""; search.blur(); };
  const POSTCODES = data.postcodes || {};
  function runSearch() {
    const q = search.value.trim().toLowerCase(); results.innerHTML = "";
    if (!q) return;
    // postcode search: 3-4 digits matches postcode prefixes from the CSA table
    if (/^\d{3,4}$/.test(q)) {
      const rows = [];
      for (const pc of Object.keys(POSTCODES).filter(p => p.startsWith(q)).sort().slice(0, 6)) {
        for (const code of POSTCODES[pc]) {
          if (A[code]) rows.push([pc, code]);
          if (rows.length >= 9) break;
        }
        if (rows.length >= 9) break;
      }
      rows.forEach(([pc, code]) => {
        const d = document.createElement("div"); d.className = "res";
        d.innerHTML = `<span>${A[code].name}</span><small>${pc}</small>`;
        d.onclick = () => { select(code, true); search.value = A[code].name; closeSearch(); };
        results.appendChild(d);
      });
      if (!rows.length) {
        const d = document.createElement("div"); d.className = "res nores";
        d.innerHTML = `<span>No suburbs for postcode “${q}”</span><small>try the name</small>`;
        results.appendChild(d);
      }
      return;
    }
    let matches = entries.filter(([, a]) => a.name.toLowerCase().includes(q));
    let fuzzy = false;
    if (!matches.length && q.length >= 4) {    // typo tolerance: edit distance ≤ 2
      matches = entries
        .map(([code, a]) => {
          const name = a.name.toLowerCase();
          const d = Math.min(...name.split(/[\s\-–]+/).concat(name).map(t => editDist(q, t, 2)));
          return [code, a, d];
        })
        .filter(([, , d]) => d <= 2)
        .sort((x, y) => x[2] - y[2]);
      fuzzy = matches.length > 0;
    }
    matches.slice(0, 8).forEach(([code, a]) => {
      const d = document.createElement("div"); d.className = "res";
      d.innerHTML = `<span>${a.name}</span><small>${fuzzy ? "did you mean?" : (a.lga || "")}</small>`;
      d.onclick = () => { select(code, true); search.value = a.name; closeSearch(); };
      results.appendChild(d);
    });
    if (q.length >= 6) {                       // offer address geocoding as the last row
      const d = document.createElement("div"); d.className = "res addr";
      d.innerHTML = `<span>Find address “${search.value.trim()}”</span><small>OSM</small>`;
      d.onclick = () => { closeSearch(); searchAddress(search.value.trim()); };
      results.appendChild(d);
    }
  }
  // bounded Levenshtein: bails out early once the distance can't beat `max`
  function editDist(a, b, max) {
    if (Math.abs(a.length - b.length) > max) return max + 1;
    let prev = Array.from({ length: b.length + 1 }, (_, i) => i);
    for (let i = 1; i <= a.length; i++) {
      const cur = [i]; let best = i;
      for (let j = 1; j <= b.length; j++) {
        cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
        best = Math.min(best, cur[j]);
      }
      if (best > max) return max + 1;
      prev = cur;
    }
    return prev[b.length];
  }
  search.oninput = runSearch;
  search.onkeydown = e => {                    // ↑/↓ move through results, Enter selects
    const rows = [...results.querySelectorAll(".res")];
    if (!rows.length) return;
    const cur = rows.findIndex(r => r.classList.contains("active"));
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const next = e.key === "ArrowDown" ? Math.min(cur + 1, rows.length - 1) : Math.max(cur - 1, 0);
      rows.forEach((r, i) => r.classList.toggle("active", i === next));
    } else if (e.key === "Enter") {
      (rows[cur] || rows[0]).click();
    }
  };
  // mobile: the topbar magnifier expands the search into a full-width bar
  document.getElementById("searchTog").onclick = () => {
    if (topbar.classList.toggle("search-open")) { search.value = ""; results.innerHTML = ""; search.focus(); }
    else closeSearch();
  };
  map.on("click", closeSearch);

  // ---- city switcher (appears only once a second city has data) -----------
  // A pasted #city= link into an already-open tab must also switch: hash-only
  // navigation doesn't reload, so watch for it and reboot into the new city.
  addEventListener("hashchange", () => {
    const c = new URLSearchParams(location.hash.replace(/^#/, "")).get("city");
    if (c && c !== citySlug && CITIES.cities.some(x => x.slug === c)) location.reload();
  });
  if (CITIES.cities.length > 1) {
    const sel = document.createElement("select");
    sel.id = "citySwitch"; sel.title = "Switch city"; sel.setAttribute("aria-label", "Switch city");
    sel.innerHTML = CITIES.cities.map(c =>
      `<option value="${c.slug}"${c.slug === citySlug ? " selected" : ""}>${c.name}</option>`).join("");
    sel.onchange = () => {
      try { localStorage.setItem("city", sel.value); } catch (e) {}
      const p = new URLSearchParams(); p.set("city", sel.value);
      location.hash = "#" + p.toString();   // a fresh view — the suburb belongs to the old
      location.reload();                    // city; reload even if the hash didn't change
    };
    document.querySelector("#topbar .brand").after(sel);
  }

  // ---- Ask: plain-English budget/goal queries, answered from the data -----
  // "500k and I want to live" / "800k to invest" — parsed and ranked entirely
  // client-side; no API, works offline, instant for every visitor.
  const askModal = document.getElementById("askModal");
  const askInput = document.getElementById("askInput");
  const askResults = document.getElementById("askResults");
  const askSummary = document.getElementById("askSummary");

  // Optional Claude-powered summaries. Deploy cloudflare-worker/ (see its
  // README), paste the worker URL here, and add that origin to the CSP
  // connect-src in index.html. Empty string = feature hidden, site fully
  // client-side.
  const AI_ENDPOINT = "";

  // compass words -> explicit ABS SA4 lists ("east" alone must never match
  // "Melbourne - South East"; first matching key wins, so the engine ships the
  // map with longer phrases first). Curated per city in engine/config.py and
  // delivered via scores.json; the literal below only covers cached old data.
  const REGION_SA4 = data.regions || {
    "inner west": ["Melbourne - West"],
    "inner north": ["Melbourne - Inner"],
    "inner east": ["Melbourne - Inner East"],
    "inner south": ["Melbourne - Inner South"],
    "outer east": ["Melbourne - Outer East"],
    "north east": ["Melbourne - North East"],
    "north west": ["Melbourne - North West"],
    "south east": ["Melbourne - South East"],
    "inner": ["Melbourne - Inner", "Melbourne - Inner East", "Melbourne - Inner South"],
    "west": ["Melbourne - West", "Melbourne - North West"],
    "north": ["Melbourne - North East", "Melbourne - North West"],
    "east": ["Melbourne - Inner East", "Melbourne - Outer East", "Melbourne - North East"],
    "south": ["Melbourne - Inner South", "Melbourne - South East", "Mornington Peninsula"],
    "mornington": ["Mornington Peninsula"], "peninsula": ["Mornington Peninsula"],
  };
  function parseRegion(s) {
    const t = s.replace(/-/g, " ").replace(/\b(south|north)(east|west)\b/g, "$1 $2");
    for (const key of Object.keys(REGION_SA4))
      if (new RegExp("\\b" + key + "\\b").test(t)) return key;
    return null;
  }

  function parseAsk(q) {
    const s = " " + q.toLowerCase() + " ";
    let budget = null, m;
    if ((m = s.match(/\$?\s*(\d+(?:\.\d+)?)\s*(m\b|mil|million)/))) budget = parseFloat(m[1]) * 1e6;
    else if ((m = s.match(/\$?\s*(\d+(?:\.\d+)?)\s*k\b/))) budget = parseFloat(m[1]) * 1e3;
    else if ((m = s.match(/\$?\s*(\d{1,3}(?:[, ]\d{3})+|\d{6,})\b/))) budget = parseFloat(m[1].replace(/[, ]/g, ""));
    else if ((m = s.match(/\$\s*(\d+(?:\.\d+)?)/))) { const n = parseFloat(m[1]); budget = n <= 20 ? n * 1e6 : n * 1e3; }
    else if ((m = s.match(/\b(\d{3,4})\b/))) { const n = +m[1]; if (n >= 200 && n <= 5000) budget = n * 1e3; }
    // weekly rent budget: "$600/wk", "rent under 550 a week"
    let rentMax = null;
    if ((m = s.match(/\$?\s*(\d{2,4})\s*(?:\/\s*|per\s+|a\s+)(?:week|wk|w\b)/))) rentMax = +m[1];
    if (rentMax && budget === rentMax * 1e3) budget = null;   // same digits, was a rent figure
    let goal = "live";
    if (/famil|kids|children|school/.test(s)) goal = "family";
    if (/invest|growth|buy and hold|portfolio|capital/.test(s)) goal = "invest";
    if (/develop|subdivi|build|knock|redevelop|land bank/.test(s)) goal = "develop";
    if (/yield|rental income|cash ?flow|rent (it |them )?out|positivel?y gear/.test(s)) goal = "yield";
    if (goal === "live" && (rentMax || /\brent(ing|er)?\b/.test(s))) goal = "rent";
    return {
      budget, rentMax, goal,
      unit: /unit|apartment|\bflat\b|condo|townhouse/.test(s),
      safe: /\bsafe|safety|low crime/.test(s),
      train: /train|station|commut/.test(s),
      region: parseRegion(s),
    };
  }

  // liveOf/devOf so Ask respects custom weights when the user has set them
  const ASK_GOAL = {
    live:    { label: "to live",          colorBy: "live",   score: a => liveOf(a),
               how: "ranked by Liveability — safety, socio-economics, trains, schools" },
    rent:    { label: "to rent",          colorBy: "live",   score: a => liveOf(a),
               how: "ranked by Liveability among suburbs inside your weekly rent" },
    family:  { label: "for a family",     colorBy: "family", score: a => a.live_family,
               how: "ranked by family-lens Liveability — safety, schools, children" },
    invest:  { label: "to invest",        colorBy: "dev",    score: a => 0.45 * devOf(a) + 0.3 * (a.market.growth_score ?? 50) + 0.25 * (a.pillars.yield.score ?? 50),
               how: "ranked 45% Development + 30% recent growth + 25% yield" },
    develop: { label: "to develop",       colorBy: "dev",    score: a => devOf(a),
               how: "ranked by Development potential — zoning, headroom, growth" },
    yield:   { label: "for rental yield", colorBy: "yield",  score: a => a.pillars.yield.score ?? 0,
               how: "ranked by gross rental yield" },
  };

  // Per-state transfer ("stamp") duty — general rates, no concessions. Keyed by
  // scores.json's `state` so each city uses its own table; add a state's entry
  // when its city ships (see docs/AUSTRALIA.md). No entry = no duty estimate.
  // VIC brackets as at FY 2025-26 (sro.vic.gov.au — update vintage too):
  //   ≤$25k 1.4% · ≤$130k $350 + 2.4% · ≤$960k $2,870 + 6% · ≤$2M flat 5.5% ·
  //   >$2M $110k + 6.5% of the excess.
  const STAMP_DUTY = {
    VIC: {
      name: "Vic", vintage: "FY 2025-26",
      calc: v => {
        if (v <= 25000) return v * 0.014;
        if (v <= 130000) return 350 + (v - 25000) * 0.024;
        if (v <= 960000) return 2870 + (v - 130000) * 0.06;
        if (v <= 2000000) return v * 0.055;
        return 110000 + (v - 2000000) * 0.065;
      },
    },
    // NSW transfer duty, FY 2024-25 thresholds (revenue.nsw.gov.au — indexed
    // each 1 July; premium 7% band applies above ~$3.64M residential).
    NSW: {
      name: "NSW", vintage: "FY 2024-25",
      calc: v => {
        if (v <= 17000) return v * 0.0125;
        if (v <= 36000) return 212 + (v - 17000) * 0.015;
        if (v <= 97000) return 497 + (v - 36000) * 0.0175;
        if (v <= 364000) return 1564 + (v - 97000) * 0.035;
        if (v <= 1212000) return 10909 + (v - 364000) * 0.045;
        if (v <= 3636000) return 49069 + (v - 1212000) * 0.055;
        return 182389 + (v - 3636000) * 0.07;
      },
    },
  };
  const cityDuty = STAMP_DUTY[data.state || "VIC"];   // old cached data is Vic

  function runAsk() {
    const q = askInput.value.trim();
    if (!q) return;
    const p = parseAsk(q), g = ASK_GOAL[p.goal];
    const rows = [];
    for (const [code, a] of entries) {
      if (a.precinct) continue;
      const price = p.unit ? a.market.median_unit : a.market.median_house;
      if (p.budget && (!price || price > p.budget * 1.05)) continue;
      if (p.rentMax && (!a.market.rent_weekly || a.market.rent_weekly > p.rentMax * 1.05)) continue;
      if (p.safe && (a.pillars.person_safety.score ?? 0) < 65) continue;
      if (p.train && (a.transit.nearest_station_km ?? 99) > 1.6) continue;
      if (p.region && !REGION_SA4[p.region].includes(a.sa4)) continue;
      rows.push([code, a, Math.round(g.score(a) * 10) / 10, price]);
    }
    rows.sort((x, y) => y[2] - x[2]);
    const top = rows.slice(0, 12);

    const parts = [];
    if (p.budget) parts.push(money(p.budget) + (p.unit ? " (units)" : ""));
    if (p.rentMax) parts.push("$" + p.rentMax + "/wk rent");
    parts.push(g.label);
    if (p.safe) parts.push("safe"); if (p.train) parts.push("near a train"); if (p.region) parts.push(p.region);
    if (!top.length) {
      askSummary.innerHTML = `No suburbs match <b>${parts.join(" · ")}</b>. Try a higher budget, adding “unit”, or fewer must-haves.`;
      askResults.innerHTML = "";
      askSet = null; refresh();
      return;
    }
    const duty = p.budget && !p.rentMax && cityDuty
      ? ` Stamp duty on a ${money(p.budget)} buy ≈ <b>$${Math.round(cityDuty.calc(p.budget)).toLocaleString()}</b> (${cityDuty.name} general rate, ${cityDuty.vintage} — concessions may apply).`
      : "";
    askSummary.innerHTML = `<b>${rows.length}</b> suburbs fit <b>${parts.join(" · ")}</b> — top ${top.length} below, highlighted on the map.
      <span class="ask-how">${g.how}${customW && (p.goal === "live" || p.goal === "rent" || p.goal === "develop") ? " (your custom weights)" : ""}.${duty}</span>`;
    askResults.innerHTML = top.map(([code, a, sc, price], i) => `
      <div class="ask-row" data-code="${code}">
        <span class="rk">${i + 1}</span>
        <span class="ask-nm">${a.name}<small>${a.lga || ""}${price ? " · median " + money(price) : ""}</small></span>
        <span class="ask-sc" style="color:${rampColor(sc, "balanced")}">${Math.round(sc)}</span>
      </div>`).join("");
    askResults.querySelectorAll(".ask-row").forEach(r =>
      r.onclick = () => { closeAsk(); select(r.dataset.code, true); });

    if (AI_ENDPOINT) {                       // optional grounded AI summary
      const btn = document.createElement("button");
      btn.className = "btn ghost ai-btn"; btn.textContent = "AI summary of these matches";
      btn.onclick = async () => {
        btn.disabled = true; btn.textContent = "Thinking…";
        try {
          const digest = top.map(([, a, s, price]) => ({
            name: a.name, lga: a.lga, grade: a.grade, score: s, median: price,
            rent_wk: a.market.rent_weekly, yield_pct: a.market.yield_headline,
            safety: a.pillars.person_safety.score, station_km: a.transit.nearest_station_km,
          }));
          const res = await fetch(AI_ENDPOINT, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ question: q, context: digest }),
          }).then(r => r.json());
          const out = document.createElement("p");
          out.className = "ai-answer"; out.textContent = res.answer || res.error || "No answer.";
          askResults.prepend(out); btn.remove();
        } catch {
          btn.disabled = false; btn.textContent = "AI summary of these matches";
          toast("AI request failed — try again in a moment.");
        }
      };
      askResults.prepend(btn);
    }

    askSet = new Set(top.map(r => r[0]));
    activeBest = null; activePreset = null; minScore = 0; setMinSlider();
    colorBy = g.colorBy;
    refresh();
    select(top[0][0], false);
  }

  const openAsk = () => { askModal.classList.remove("hidden"); askModal.setAttribute("aria-hidden", "false"); askInput.focus(); };
  const closeAsk = () => { askModal.classList.add("hidden"); askModal.setAttribute("aria-hidden", "true"); };
  document.getElementById("askBtn").onclick = openAsk;
  document.getElementById("askBtn2").onclick = openAsk;
  document.getElementById("closeAsk").onclick = closeAsk;
  document.getElementById("askGo").onclick = runAsk;
  askInput.addEventListener("keydown", e => { if (e.key === "Enter") runAsk(); });
  askModal.onclick = e => { if (e.target === askModal) closeAsk(); };
  document.querySelectorAll("#askChips button").forEach(b =>
    b.onclick = () => { askInput.value = b.dataset.q; runAsk(); });

  // ---- train stations overlay --------------------------------------------
  let stnLayer = null;
  async function ensureStations() {
    if (stnLayer) return stnLayer;
    const gj = await fetch(CITY_BASE + "stations.geojson?v=" + DATA_V).then(r => r.json());
    stnLayer = L.geoJSON(gj, {
      pointToLayer: (f, ll) => L.circleMarker(ll, {
        radius: f.properties.kind === "metro" ? 3.5 : 4.5,
        color: "#fff", weight: 1.2,
        fillColor: f.properties.kind === "metro" ? "#0a84ff" : "#af52de", fillOpacity: .95,
      }),
      onEachFeature: (f, l) => l.bindTooltip(
        `${f.properties.name} station${f.properties.kind === "vline" ? " (V/Line)" : ""}` +
        (f.properties.pax ? ` · ~${(f.properties.pax / 1e6).toFixed(1)}M entries/yr` : "")),
    });
    return stnLayer;
  }
  document.getElementById("stnToggle").onchange = async e => {
    const lyr = await ensureStations();
    if (e.target.checked) lyr.addTo(map); else map.removeLayer(lyr);
  };

  // ---- theme ------------------------------------------------------------
  function setTheme(t) {
    document.documentElement.dataset.theme = t; localStorage.setItem("theme", t);
    document.querySelector('meta[name="theme-color"]').setAttribute("content", t === "dark" ? "#1c1c1e" : "#f2f2f7");
    map.removeLayer(base); base = tilesFor(t === "dark").addTo(map); base.bringToBack();
    map.removeLayer(labels); labels = labelsFor(t === "dark").addTo(map);
  }
  // colour-blind palette toggle (persisted)
  const cbTog = document.getElementById("cbToggle");
  cbTog.checked = cbPalette;
  cbTog.onchange = () => {
    cbPalette = cbTog.checked; localStorage.setItem("cbPalette", cbPalette ? "1" : "0"); refresh();
  };
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
  modal.querySelectorAll("#closeAbout, #closeAbout2").forEach(b => b.onclick = closeGuide);
  modal.onclick = e => { if (e.target === modal) closeGuide(); };
  document.addEventListener("keydown", e => { if (e.key === "Escape") { closeGuide(); closeSearch(); closeWeights(); closeAsk(); } });

  // ---- init -------------------------------------------------------------
  setTheme(localStorage.getItem("theme") || "light");   // bright by default; dark stays a saved choice
  const fromHash = readHash();
  if (fromHash) {                       // restore a shared view
    setSlider(); setMinSlider(); highlightModes(); refresh();
    if (typeof fromHash === "string") select(fromHash, true);
  } else {
    setMode("balanced");
  }
  hashReady = true; writeHash();

  // ---- first-visit coach marks (3 quick steps instead of the full guide) --
  function runCoach() {
    const steps = [
      ["#modeSeg", "Pick a lens", "Live, Balanced or Invest — the map recolours instantly."],
      ["#askBtn", "Ask in plain English", "Try “$650k family home near a train” — answered from the data."],
      ["#infopanel", "Tap any suburb", "Full scorecard: safety, prices, yield, schools, zoning, hazards."],
    ];
    let i = 0;
    const ov = document.createElement("div"); ov.id = "coach";
    document.body.appendChild(ov);
    const show = () => {
      const [selq, h, body] = steps[i];
      const t = document.querySelector(selq);
      const r = t && t.offsetParent !== null ? t.getBoundingClientRect() : null;
      ov.innerHTML = `<div class="coach-bubble" role="dialog" aria-label="${h}">
        <b>${h}</b><p>${body}</p>
        <div class="coach-foot"><span class="coach-dots">${steps.map((_, j) => `<i class="${j === i ? "on" : ""}"></i>`).join("")}</span>
        <button class="btn ghost" id="coachSkip">Skip</button>
        <button class="btn" id="coachNext">${i === steps.length - 1 ? "Done" : "Next"}</button></div></div>`;
      const bub = ov.querySelector(".coach-bubble");
      if (r) {
        const top = Math.min(innerHeight - 170, r.bottom + 12);
        bub.style.top = top + "px";
        bub.style.left = Math.max(10, Math.min(innerWidth - 290, r.left)) + "px";
      } else { bub.classList.add("center"); }
      ov.querySelector("#coachSkip").onclick = done;
      ov.querySelector("#coachNext").onclick = () => (++i < steps.length ? show() : done());
    };
    const done = () => { ov.remove(); localStorage.setItem("seenCoach", "1"); };
    show();
  }
  if (!localStorage.getItem("seenCoach")) {
    localStorage.setItem("seenGuide", "1");   // don't double up with the old auto-guide
    setTimeout(runCoach, 700);
  }

  // dismiss the boot skeleton now everything is painted
  boot.classList.add("done"); setTimeout(() => boot.remove(), 500);

  // conservative offline support: network-first, cache fallback (HTTPS only)
  if ("serviceWorker" in navigator && location.protocol === "https:")
    navigator.serviceWorker.register("sw.js").catch(() => {});
})();
