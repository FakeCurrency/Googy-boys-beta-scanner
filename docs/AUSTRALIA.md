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
2. **One city per data directory.** When city #2 ships, the engine writes
   `public/data/<city>/…` (scores, explanations, geojson, stations) plus a
   tiny `public/data/cities.json` manifest, and the frontend gains a city
   switcher that loads exactly one city at a time. This keeps the boot payload
   flat (~1 MB per city instead of ~7 MB national), and the PWA, rankings,
   URLs and service worker keep working unchanged per city. Until then the
   single-city layout stays where it is — no churn before it pays for itself.
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

Still Melbourne-specific by design (fix when city #2 ships):

- The product name/brand ("Melbourne Property", `index.html` meta, boot
  screen, og.png) — a naming decision, not a code one.
- `public/data/melbourne.geojson` filename and the single-city data layout
  (see decision 2).
- The Guide's "Data & sources" tab describes Victorian agencies; it becomes
  per-city content (engine already ships a `sources` note it could render).
- `.github/workflows/refresh_data.yml` refreshes one city; it becomes a
  matrix over city profiles.

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

`app.js` now keys duty tables by `data.state`; add NSW/QLD/WA/SA/TAS/ACT/NT
general-rate brackets (each ~6 lines) as each city ships. No entry = the Ask
box simply omits the estimate.

## Architecture changes when city #2 ships

1. `engine/config.py`: `CITIES = {"melbourne": {...}, "sydney": {...}}` — each
   profile holds GCC name, state code, regions map, zone groupings, and which
   source adapters to use. `python -m engine.run --city sydney`.
2. Output per city: `public/data/<city>/{scores,explanations}.json`,
   `boundaries.geojson`, `stations.geojson` + `public/data/cities.json`.
3. Frontend: city switcher in the topbar; city slug in the URL hash;
   everything else already reads from the loaded payload.
4. `refresh_data.yml`: matrix over cities; guards run per city.
5. Payload budget: each city stays ~1–1.5 MB gzipped; nothing national ever
   loads at boot.

## Sequencing

1. **Done (this change):** city profile in config, `state`/`regions` in the
   payload, data-derived map view/geocoder box, per-state duty table.
2. **Sydney** — BOCSAR + NSW VG + bonds + planning portal + TfNSW; build the
   multi-city dirs + switcher as part of it (first real consumer).
3. **Brisbane, Perth, Adelaide** — one at a time; zoning mapping is the slog.
4. **Hobart, Darwin, Canberra** — small SA2 counts; accept LGA-level crime.
5. Regional (non-GCC) Australia only after capitals — needs a different
   density/detached calibration and a UX answer for vast low-data areas.
