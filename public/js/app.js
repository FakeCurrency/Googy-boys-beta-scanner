/* Melbourne Property — map, audience modes, one-click presets, scorecards. */
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
    "Train access": "Distance to the nearest metro/V-Line station, plus how many are within 3 km.",
    "School access": "Distance to the nearest primary and secondary schools, plus choice within 3 km.",
    "Zoning upside": "Share of land zoned for intensification (RGZ, MUZ, ACZ, HCTZ, commercial) vs protective zoning — from Vicmap Planning.",
    "Rental yield": "Gross yield: 3-bed-house annual rent ÷ median house price.",
    "Heritage freedom": "Inverse of Heritage Overlay coverage — heritage controls constrain redevelopment.",
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

  // tiny inline price-history sparkline (VG yearly medians)
  function spark(series) {
    if (!series || series.length < 4) return "";
    const w = 110, h = 30, xs = series.map(p => p[0]), ys = series.map(p => p[1]);
    const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
    const pts = series.map(([x, y]) =>
      `${((x - x0) / (x1 - x0 || 1) * (w - 4) + 2).toFixed(1)},${(h - 3 - (y - y0) / (y1 - y0 || 1) * (h - 8)).toFixed(1)}`).join(" ");
    const up = ys[ys.length - 1] >= ys[0];
    return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true"
      title="${x0}–${x1} median house price"><polyline points="${pts}" fill="none"
      stroke="${up ? "var(--good)" : "#ff3b30"}" stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round"/></svg>`;
  }

  function marketBlock(a, prominent) {
    const m = a.market;
    const sig = (label, cls) => `<span class="sig sig-${cls}">${label}</span>`;
    const rentLine = m.rent_weekly ? `Rent ~$${Math.round(m.rent_weekly)}/wk${
        m.rent_12m != null ? ` (${m.rent_12m >= 0 ? "+" : ""}${m.rent_12m}% 12m)` : ""}${
        m.yield_house ? ` · yield ≈${m.yield_house}%` : ""}${
        a.coverage.rent === "lga" ? ` <span class="cov" title="No suburb-level rent series for this area — figure is the ${a.lga} LGA median">LGA-level</span>` : ""}` : "";
    if (!m.median_house)
      return `<div class="market mini"><div class="market-h">Market &amp; Price</div>
        <p class="market-note">No Valuer-General sale medians for this area (often non-residential).</p>
        ${rentLine ? `<div class="market-sub">${rentLine}</div>` : ""}</div>`;
    const up = (m.house_12m ?? 0) >= 0;
    return `<div class="market${prominent ? "" : " mini"}">
      <div class="market-h">Market &amp; Price <span class="src">VG ${m.house_year} · DFFH ${m.rent_quarter || ""}</span></div>
      <div class="market-row">
        <div class="price"><span class="ml">Median house</span><span class="pv-big">${money(m.median_house)}</span></div>
        ${spark(m.house_series)}
        <div class="growth" style="color:${up ? "var(--good)" : "#ff3b30"}">${up ? "▲" : "▼"} ${m.house_12m ?? "–"}% <small>12m</small></div>
      </div>
      <div class="market-sub">
        ${m.median_unit ? `Unit ${money(m.median_unit)} · ` : ""}3-yr ${m.house_3yr_cagr ?? "–"}%/yr
        ${sig(m.growth_signal + " growth", m.growth_signal.toLowerCase())}${m.value_signal ? sig(m.value_signal, "val") : ""}${m.yield_signal ? sig(m.yield_signal, m.yield_house >= 4.2 ? "strong" : m.yield_house >= 3.2 ? "moderate" : "soft") : ""}
      </div>
      ${rentLine ? `<div class="market-sub">${rentLine}</div>` : ""}
      ${prominent ? `<p class="market-note">${a.explanation_invest}</p>` : ""}</div>`;
  }

  const IC = {
    fam: '<svg class="ic ic-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="9" cy="8" r="3"/><path d="M3.6 19a5.4 5.4 0 0 1 10.8 0"/><path d="M16 6.6a3 3 0 0 1 0 5.8M17.4 14a5 5 0 0 1 3 4.6"/></svg>',
    bolt: '<svg class="ic ic-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round" aria-hidden="true"><path d="M13 3 5 13h5l-1 8 8-11h-5z"/></svg>',
    train: '<svg class="ic ic-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="6" y="3" width="12" height="13" rx="2.5"/><path d="M6 10h12M9.5 16 7 20M14.5 16 17 20"/><circle cx="9.5" cy="13" r=".6" fill="currentColor"/><circle cx="14.5" cy="13" r=".6" fill="currentColor"/></svg>',
    school: '<svg class="ic ic-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m12 4 9 4.5-9 4.5-9-4.5z"/><path d="M6.5 10.8V16c0 1.2 2.5 2.5 5.5 2.5s5.5-1.3 5.5-2.5v-5.2"/></svg>',
  };

  function transitBlock(a, prominent) {
    const t = a.transit, s = a.schools;
    if (t.nearest_station_km == null && s.nearest_primary_km == null) return "";
    const st = t.nearest_station_km != null
      ? `${IC.train} <b>${t.nearest_station}</b> ~${t.nearest_station_km} km${t.stations_3km > 1 ? ` · ${t.stations_3km} stations &lt;3 km` : ""}`
      : "";
    const sch = s.nearest_primary_km != null
      ? `${IC.school} primary ~${s.nearest_primary_km} km · secondary ~${s.nearest_secondary_km ?? "—"} km · ${s.schools_3km} schools &lt;3 km`
      : "";
    return `<div class="market${prominent ? "" : " mini"}">
      <div class="market-h">Trains &amp; Schools <span class="src">DTP FY24-25 · DE 2025</span></div>
      ${st ? `<div class="market-sub icrow">${st}</div>` : ""}
      ${sch ? `<div class="market-sub icrow">${sch}</div>` : ""}</div>`;
  }

  function zoningBlock(a, prominent) {
    const z = a.zoning;
    if (!z) return `<div class="market mini"><div class="market-h">Planning &amp; Zoning</div>
      <p class="market-note">No zoning sample for this area.</p></div>`;
    const mix = (z.zone_mix || []).slice(0, 3).map(([c, s]) =>
      `<span class="sig sig-val" title="${ZONE_NAMES[c] || c}">${c} ${Math.round(s * 100)}%</span>`).join("");
    const her = z.heritage_share >= 0.03
      ? `<span class="sig ${z.heritage_share >= 0.25 ? "sig-soft" : "sig-moderate"}">Heritage ${Math.round(z.heritage_share * 100)}%</span>` : "";
    return `<div class="market${prominent ? "" : " mini"}">
      <div class="market-h">Planning &amp; Zoning <span class="src">VicPlan</span></div>
      <div class="market-sub"><span class="sig sig-${z.growth_share >= 0.2 ? "strong" : z.restrict_share >= 0.5 ? "soft" : "moderate"}">${z.label}</span>${mix}${her}</div>
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
    if (compareWith && compareWith !== code) return renderCompare(code, compareWith);
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
      <p class="bestfor"><b>Best for:</b> ${bestFor(a)}.
        <button class="cmp-btn" id="cmpBtn" title="Compare this suburb side-by-side with another">⇆ Compare</button></p>
      ${comparePicking ? `<p class="cmp-hint">Now tap a second suburb on the map, list or search…
        <button class="cmp-x" id="cmpCancel">cancel</button></p>` : ""}
      <div class="bigrow">
        <div class="big" style="background:${rampColor(lv, "live")}"><div class="lab">${liveLab}</div><div class="num">${lv}</div></div>
        <div class="big" style="background:${rampColor(a.dev, "invest")}"><div class="lab">Development</div><div class="num">${a.dev}</div></div>
        <div class="big" style="background:${col(ov)}"><div class="lab">Overall</div><div class="num">${ov}</div></div>
      </div>
      ${prominent ? marketBlock(a, true) + zoningBlock(a, true) + transitBlock(a, false) + infraBlock(a, true) : ""}
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
      ${bar("Grid support", a.infra.score, a.infra.advantage)}
      ${bar("Rental yield", p.yield.score, p.yield.raw == null ? "n/a" : p.yield.raw + "%")}
      ${bar("Rental turnover", p.rental.score, pct(p.rental.raw), true)}
      ${bar("Low density", p.low_density.score, p.low_density.raw == null ? "—" : Math.round(p.low_density.raw).toLocaleString() + "/km²", true)}
      ${bar("Heritage freedom", p.heritage_free.score, p.heritage_free.raw == null ? "n/a" : Math.round(p.heritage_free.raw * 100) + "% HO", true)}
      <p class="summary">${a.explanation_live}</p>
      <p class="summary dev">${a.explanation_dev}</p>
      ${prominent ? "" : marketBlock(a, false) + zoningBlock(a, false) + transitBlock(a, false) + infraBlock(a, false)}
      ${coverageNote(a)}`;
    const cb = document.getElementById("cmpBtn");
    if (cb) cb.onclick = () => { comparePicking = true; renderCard(code); };
    const cc = document.getElementById("cmpCancel");
    if (cc) cc.onclick = () => { comparePicking = false; renderCard(code); };
    sc.classList.remove("pop"); void sc.offsetWidth; sc.classList.add("pop");  // re-trigger fade-in
  }

  // ---- compare mode -------------------------------------------------------
  let compareWith = null, comparePicking = false;
  function renderCompare(codeA, codeB) {
    const a = A[codeA], b = A[codeB]; if (!a || !b) return;
    const num = (x, y, lowerBetter) => {
      if (x == null || y == null || x === y) return ["", ""];
      const aWins = lowerBetter ? x < y : x > y;
      return aWins ? ["win", ""] : ["", "win"];
    };
    const row = (label, va, vb, cls = ["", ""], tip = "") =>
      `<div class="cmp-row" title="${tip}"><span class="cmp-l">${label}</span>
        <span class="cmp-v ${cls[0]}">${va ?? "—"}</span><span class="cmp-v ${cls[1]}">${vb ?? "—"}</span></div>`;
    const lvA = liveOf(a), lvB = liveOf(b), ovA = overallOf(a), ovB = overallOf(b);
    const kmA = a.transit.nearest_station_km, kmB = b.transit.nearest_station_km;
    sc.classList.remove("empty");
    sc.innerHTML = `
      <div class="sc-head cmp-head">
        <div><h2 class="sc-name">Compare</h2>
          <p class="sc-sub">${a.name} vs ${b.name}</p></div>
        <button class="cmp-x big" id="cmpExit" title="Exit compare">×</button>
      </div>
      <div class="cmp-row cmp-titles"><span class="cmp-l"></span>
        <span class="cmp-v"><b>${a.name}</b><span class="grade gmini" style="background:${gradeColor(a.grade)}">${a.grade}</span></span>
        <span class="cmp-v"><b>${b.name}</b><span class="grade gmini" style="background:${gradeColor(b.grade)}">${b.grade}</span></span></div>
      ${row("Liveability", lvA, lvB, num(lvA, lvB))}
      ${row("Development", a.dev, b.dev, num(a.dev, b.dev))}
      ${row("Overall (your blend)", ovA, ovB, num(ovA, ovB))}
      ${row("Family suitability", a.family.score, b.family.score, num(a.family.score, b.family.score))}
      ${row("Personal safety", a.pillars.person_safety.score, b.pillars.person_safety.score,
            num(a.pillars.person_safety.score, b.pillars.person_safety.score), "percentile — higher = safer")}
      ${row("SEIFA decile", a.pillars.seifa.decile, b.pillars.seifa.decile, num(a.pillars.seifa.decile, b.pillars.seifa.decile))}
      ${row("Median house", money(a.market.median_house), money(b.market.median_house))}
      ${row("Rent / week", a.market.rent_weekly ? "$" + Math.round(a.market.rent_weekly) : null,
            b.market.rent_weekly ? "$" + Math.round(b.market.rent_weekly) : null)}
      ${row("Gross yield", a.market.yield_house ? a.market.yield_house + "%" : null,
            b.market.yield_house ? b.market.yield_house + "%" : null,
            num(a.market.yield_house, b.market.yield_house))}
      ${row("3-yr growth", a.market.house_3yr_cagr != null ? a.market.house_3yr_cagr + "%/yr" : null,
            b.market.house_3yr_cagr != null ? b.market.house_3yr_cagr + "%/yr" : null,
            num(a.market.house_3yr_cagr, b.market.house_3yr_cagr))}
      ${row("Nearest station", kmA != null ? kmA + " km" : null, kmB != null ? kmB + " km" : null, num(kmA, kmB, true))}
      ${row("Zoning", a.zoning ? a.zoning.label : null, b.zoning ? b.zoning.label : null)}
      ${row("Grid support", a.infra.advantage, b.infra.advantage)}
      <p class="covnote">Green = the stronger side. Tap × to go back to the full scorecard.</p>`;
    document.getElementById("cmpExit").onclick = () => { compareWith = null; renderCard(selected); writeHash(); };
    sc.classList.remove("pop"); void sc.offsetWidth; sc.classList.add("pop");
  }

  function coverageNote(a) {
    const c = a.coverage, notes = [];
    notes.push(c.crime === "suburb" ? "crime: suburb-level" : "crime: LGA-level");
    if (c.rent === "lga") notes.push("rent: LGA-level");
    else if (!c.rent) notes.push("rent: no data");
    if (!c.price) notes.push("price: no VG match");
    if (!c.zoning) notes.push("zoning: no sample");
    return `<p class="covnote" title="How fine-grained each source is for this exact area">Data coverage — ${notes.join(" · ")}</p>`;
  }

  function select(code, fly) {
    infopanel.classList.remove("peek");       // picking a suburb re-opens a pushed-down sheet
    if (comparePicking && selected && code !== selected) {
      comparePicking = false; compareWith = code;
      repaint(); renderCompare(selected, compareWith); writeHash();
      return;
    }
    selected = code; repaint();
    if (compareWith && compareWith !== code) renderCompare(code, compareWith);
    else renderCard(code);
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
    writeHash();
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

  // ---- shareable URL state ------------------------------------------------
  let hashReady = false;
  function writeHash() {
    if (!hashReady) return;
    const p = new URLSearchParams();
    if (selected) p.set("s", selected);
    if (compareWith) p.set("vs", compareWith);
    p.set("m", mode); p.set("w", Math.round(wLive * 100));
    if (colorBy !== "overall") p.set("c", colorBy);
    if (minScore > 0) p.set("min", Math.round(minScore));
    history.replaceState(null, "", "#" + p.toString());
  }
  function readHash() {
    const h = location.hash.replace(/^#/, "");
    if (!h) return false;
    const p = new URLSearchParams(h);
    if (p.get("m") && MODE_PRESETS[p.get("m")] != null) mode = p.get("m");
    if (p.get("w") != null && !isNaN(+p.get("w"))) wLive = Math.max(0, Math.min(100, +p.get("w"))) / 100;
    if (p.get("c")) colorBy = p.get("c");
    if (p.get("min") != null) minScore = Math.max(0, Math.min(90, +p.get("min") || 0));
    if (p.get("vs") && A[p.get("vs")]) compareWith = p.get("vs");
    return p.get("s") && A[p.get("s")] ? p.get("s") : true;
  }

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
      const url = "https://nominatim.openstreetmap.org/search?format=json&limit=1&countrycodes=au" +
        "&viewbox=144.2,-37.1,145.9,-38.7&bounded=1&q=" + encodeURIComponent(q);
      const res = await fetch(url, { headers: { "Accept-Language": "en" } }).then(r => r.json());
      if (!res.length) { alert("Couldn't find that address inside Greater Melbourne."); return; }
      const lat = +res[0].lat, lon = +res[0].lon;
      const code = sa2At(lon, lat);
      if (!code) { alert("That point is outside the Greater Melbourne study area."); return; }
      if (addrMarker) map.removeLayer(addrMarker);
      addrMarker = L.marker([lat, lon], { title: res[0].display_name }).addTo(map)
        .bindPopup(res[0].display_name.split(",").slice(0, 3).join(",")).openPopup();
      select(code, true);
    } catch (e) { alert("Address lookup failed — try again in a moment."); }
  }

  // ---- search (suburbs + addresses) ---------------------------------------
  const search = document.getElementById("search"), results = document.getElementById("results");
  const topbar = document.getElementById("topbar");
  const closeSearch = () => { topbar.classList.remove("search-open"); results.innerHTML = ""; search.blur(); };
  function runSearch() {
    const q = search.value.trim().toLowerCase(); results.innerHTML = "";
    if (!q) return;
    entries.filter(([, a]) => a.name.toLowerCase().includes(q)).slice(0, 8).forEach(([code, a]) => {
      const d = document.createElement("div"); d.className = "res";
      d.innerHTML = `<span>${a.name}</span><small>${a.lga || ""}</small>`;
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
  search.oninput = runSearch;
  search.onkeydown = e => { if (e.key === "Enter") { const f = results.querySelector(".res"); if (f) f.click(); } };
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

  // ---- train stations overlay --------------------------------------------
  let stnLayer = null;
  async function ensureStations() {
    if (stnLayer) return stnLayer;
    const gj = await fetch("data/stations.geojson").then(r => r.json());
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
  const fromHash = readHash();
  if (fromHash) {                       // restore a shared view
    setSlider(); setMinSlider(); highlightModes(); refresh();
    if (typeof fromHash === "string") select(fromHash, true);
  } else {
    setMode("balanced");
  }
  hashReady = true; writeHash();
  if (!localStorage.getItem("seenGuide")) { openGuide("start"); localStorage.setItem("seenGuide", "1"); }
})();
