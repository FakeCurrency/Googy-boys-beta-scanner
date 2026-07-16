# Expanding to all of Australia — design & source plan

This documents how the Melbourne-only app becomes a multi-city (eventually
national) product, what has already been generalised, and — the real work —
the state-by-state data source matrix. Written before any second city ships
so the decisions survive contact with the code.

## Decisions (made, not open)

1. **Percentiles stay within each city.** A score of 90 means "better than
   ~90% of this city", exactly as today. Ranking nationally would let rural
   areas dominate density/headroom metrics and capital suburbs dominate price
   metrics, silently changing what every existing score means. Cross-city
   comparison is a non-goal; choosing *within* a market is the product.
2. **One city per data directory — BUILT.** The engine writes
   `public/data/<slug>/…` (scores, explanations, boundaries, stations) plus a
   `public/data/cities.json` manifest, and the frontend has a city switcher
   (hidden while only one city has data) that loads exactly one city at a
   time, with the city carried in the URL hash and remembered per device.
   This keeps the boot payload flat (~1 MB per city instead of ~7 MB
   national), and the PWA, rankings, URLs and service worker all work
   unchanged per city.
3. **City-by-city, not big-bang.** Sydney first (best open data after Vic),
   then Brisbane/Perth/Adelaide, then the smaller capitals. Each new city is
   a config profile + per-state source adapters; the frontend needs nothing
   new after the switcher exists.

## Already generalised (this refactor)

Everything city-specific the frontend needs now ships inside `scores.json`
and the app derives the rest from data:

- `state` (e.g. `"VIC"`) keys the frontend's per-state stamp-duty tables.
- `regions` carries the curated compass-word → SA4 map for the Ask box
  (moved from a hardcoded Melbourne map in app.js into `engine/config.py`).
- The initial map view and the Nominatim geocoder bounding box are computed
  from the loaded boundary file — no hardcoded coordinates remain.
- "Greater Melbourne" copy in tooltips/toasts uses `data.city`.

Also built since: the multi-city plumbing itself. `engine/config.py` holds a
`CITIES` registry (Melbourne and Sydney both `ready: True`),
`python -m engine.run --city <slug>` switches profiles (`--geo-only` already
works for any city since ABS boundaries are national; a full build refuses
until the state's adapters exist), every output goes to
`public/data/<slug>/…`, `build()` maintains `cities.json`, and the frontend
resolves the city from hash → saved choice → manifest default.

Still Melbourne-specific by design (fix when city #2 ships):

- The product name/brand ("Melbourne Property", `index.html` meta, boot
  screen, og.png) — a naming decision, not a code one.
- The Guide's "Data & sources" tab describes Victorian agencies; it becomes
  per-city content (engine already ships a `sources` note it could render).
- `build.py`'s `SOURCES_NOTE` text and the Vic zone groupings in config —
  both move into the city profile with the first NSW adapters.
- `.github/workflows/refresh_data.yml` refreshes Melbourne (paths already
  per-city); it becomes a matrix over ready cities.

## What scales for free (national datasets)

| Layer | Source | Notes |
|---|---|---|
| Boundaries | ABS ASGS Ed. 3 SA2 shapefile | Already national (~2,470 SA2s); the engine filters by `GCC_NAME` |
| Socio-economic | ABS SEIFA 2021 (IRSAD, IEO) | National |
| Housing mix / demographics / income | ABS Census 2021 (G37, G01, G02) | National |
| Populations & growth | ABS Regional ERP | National |
| Electricity | Geoscience Australia transmission + substations | National (grid support still feeds Development) |
| Schools | Vic DoE today → **ACARA school locations** | ACARA is national; switching removes a per-state adapter entirely |

## The per-state work (hardest first)

### 1. Crime — the hardest layer, and the most important

Each state publishes through a different agency, geography and offence
taxonomy. Scores are only comparable if every state's categories are mapped
into the same person/property split the app uses.

| State | Agency | Geography | Notes |
|---|---|---|---|
| VIC | CSA (done) | suburb/town, LGA fallback | The template |
| NSW | BOCSAR | suburb + LGA | Good open data; offence groups map cleanly to person/property |
| QLD | QPS / QGSO open data | QPS divisions/LGA | Geographic crosswalk to SA2 needed |
| WA | WA Police crime statistics | suburb/locality | Downloadable time series |
| SA | SAPOL via data.sa.gov.au | suburb | Quarterly extracts |
| TAS / NT / ACT | DPFEM / NT Police / ACT Policing | LGA-ish | Coarser; accept LGA-level coverage flags (the UI already surfaces these) |

Adapter contract (what `engine/sources/crime.py` needs per state): incidents
by locality for the latest year, split person vs property, plus a
locality→SA2 assignment. Keep Vic's LGA-fallback + `coverage` flag pattern.

### 2. Planning & zoning — per-state code mapping

Vicmap's GRZ/RGZ/NRZ… codes exist only in Victoria. Each state needs its own
`ZONES_GROWTH / STANDARD / RESTRICT` grouping in the city profile:

| State | Source | Growth-ish codes (indicative) |
|---|---|---|
| NSW | NSW Planning Portal (EPI Land Zoning) | R3, R4, B4/MU1, E1/E2 commercial cores |
| QLD | Council planning schemes via QSpatial | Varies by council — hardest zoning state |
| WA | Data WA (R-Codes + scheme zones) | R40+, mixed-use/centre zones |
| SA | SA Planning & Design Code (data.sa) | Urban corridor, activity-centre zones |

Heritage/flood/bushfire overlays also exist per state (NSW: EPI heritage +
flood planning; QLD: council overlays) — same grid-sampling approach applies.

### 3. Prices, rents, yields

| State | Prices | Rents |
|---|---|---|
| VIC | Valuer-General (done) | DFFH (done) |
| NSW | NSW Valuer General bulk sales | Fair Trading rental bond lodgements (suburb-level, excellent) |
| QLD | Qld open data property sales | RTA median rents by suburb |
| WA | Landgate sales data | Bond administrator via REIWA/Data WA |
| SA | data.sa property sales | CBS bond data |

12-month change, 3-yr CAGR, yields and sparklines all reuse the existing
pipeline once each adapter emits `(suburb, year, median_house, median_unit)`.

### 4. Transport

| State | Stations + patronage |
|---|---|
| NSW | TfNSW Open Data (Opal tap-ons by station) |
| QLD | Translink gtfs + station patronage releases |
| WA | Transperth patronage reports |
| SA | Adelaide Metro GTFS (patronage coarser) |

The station-access scoring is already source-agnostic — it needs
`(name, lat, lon, kind, pax)` per city.

### 5. Stamp duty (frontend)

`app.js` now keys duty tables by `data.state`; VIC and NSW are in. Add
QLD/WA/SA/TAS/ACT/NT general-rate brackets (each ~6 lines) as each city
ships. No entry = the Ask box simply omits the estimate.

## Architecture status

1. ✅ `engine/config.py`: `CITIES` registry + `set_city()`;
   `python -m engine.run --city <slug>` gated on `ready` (`--geo-only`
   always allowed). Per-state source dispatch lives in
   `engine/sources/__init__.py::for_state()` (VIC = package level,
   NSW = `engine/sources/nsw/`); zone-code groupings live in each state's
   zoning adapter.
2. ✅ Output per city: `public/data/<slug>/{scores,explanations,prev-scores}.json`,
   `boundaries.geojson`, `stations.geojson` + `public/data/cities.json`
   (maintained by `build()`; a city appears only once its data exists).
3. ✅ Frontend: city switcher in the topbar (hidden with one city), `city`
   hash param, per-device memory; everything else reads the loaded payload.
   The CI smoke test switches cities when the manifest lists more than one.
4. ✅ `refresh_data.yml`: snapshots, builds and guards every city listed in
   `public/data/cities.json` (a city joins the monthly refresh the moment its
   first dataset is committed).
5. Payload budget: each city stays ~1–1.5 MB gzipped; nothing national ever
   loads at boot.

## Sequencing

1. **Done:** city profile in config, `state`/`regions` in the payload,
   data-derived map view/geocoder box, per-state duty table.
1b. **Done:** the full multi-city plumbing — per-city data dirs, cities.json,
   `--city` builds, frontend switcher.
2. **Done — Sydney is live.** Six NSW adapters built against CI recon
   (the sandboxed dev environment can't reach state portals, so adapters are
   developed via `sydney_probe.yml` dispatch on a branch; runs commit the
   built dataset back). Coverage of the 373 Greater Sydney SA2s:
   - crime: BOCSAR suburb dataset, person/property split + 4-yr trend — 358
   - prices: VG bulk PSI 2018–2024 via Wayback (direct is WAF-403) — 358,
     with yearly medians, 12m/3yr stats and sparklines
   - zoning: ePlanning EPI Land Zoning + Heritage layers, NSW groupings
     (R2 low-density plays the Vic NRZ role, no UGZ analogue) — 373
   - transport: TfNSW station locations + entry/exit patronage — 373
   - schools: DoE master dataset (government schools) — 373
   - **rents: none in v1.** Fair Trading's bond workbooks sit under
     `/sites/default/files/noindex/` behind a JS challenge: direct fetches
     get challenge HTML with any UA/cookies, and `noindex` means Wayback
     never archived them. Scores renormalise (rent/yield pills show
     "no data"). Follow-up: DCJ's quarterly **Rent and Sales Report**
     publishes median weekly rents by LGA/district — a future
     `nsw/rents.py` source, or a headed-browser fetch in CI.
3. **Brisbane, Perth, Adelaide** — one at a time; zoning mapping is the slog.
3. **Brisbane, Perth, Adelaide** — one at a time; zoning mapping is the slog.
4. **Hobart, Darwin, Canberra** — small SA2 counts; accept LGA-level crime.
5. Regional (non-GCC) Australia only after capitals — needs a different
   density/detached calibration and a UX answer for vast low-data areas.
