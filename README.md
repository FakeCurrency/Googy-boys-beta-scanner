# Melbourne Property — live, invest & develop scores by suburb

One app that helps with three Melbourne decisions — *where's safer to live/rent*, *where an
investment stacks up*, and *where there's room to add value/develop* — by ranking every **Greater
Melbourne suburb** with two 0–100 scores plus a blended overall:

- **Liveability** — *can you live/rent here safely and conveniently?* **Personal safety leads**
  (suburb-level crimes against the person weighted far above property crime), plus SEIFA advantage,
  train-station access, owner-occupier stability, school access, and a **Family Suitability**
  signal surfaced as a badge.
- **Development potential** — *room to add value?* **VicPlan zoning** (growth vs restrictive zones,
  Heritage Overlay constraint), detached-housing headroom, recent price growth, electricity-grid
  support, station access, gross rental yield, renter turnover and low current density.

**Three audience modes** (Live / Balanced / Invest) set smart starting weights, palettes and
explanations; the blend slider stays adjustable in every mode. On top of that: an **Ask** box that
answers plain-English queries from the data (“$700k family home near a train”, “rent under $550/wk”,
with stamp-duty estimates), compare **two or three** suburbs side-by-side with price-history
sparklines, a **shortlist** (starred suburbs outlined on the map, saved locally), search by suburb /
**postcode** / street address, fuzzy typo-tolerant matching, shareable URLs, custom score weights,
a train-station overlay, a colour-blind-safe palette, grade-trend arrows between data
refreshes, offline support (PWA + service worker) and an iOS-style light/dark interface.

> General information only — not financial or planning advice.

## How it's built

A small **Python engine** downloads free government data, joins it on the ABS **SA2** suburb code,
scores it, and writes JSON + GeoJSON into `public/`. The site is a static **Leaflet** map — no API
keys, no backend. Pure-Python dependencies only (`requests`, `openpyxl`, `pyshp`), so it installs
cleanly even on Python 3.14.

```
melbourne-property/
  engine/
    config.py          city, score weights, grade cut-offs        <- tune here
    fetch.py           cached downloads + ArcGIS query helper
    geo.py             ABS SA2 boundaries -> simplified GeoJSON (pure-Python Douglas-Peucker)
    score.py           percentile-normalise -> Liveability + Development -> blend + grade
    build.py / run.py  orchestrate: sources -> join on SA2 -> public/data/scores.json
    sources/
      crime.py         CSA Vic criminal incidents by suburb/town (LGA fallback)
      census.py        ABS SEIFA + Census G37 (tenure x dwelling) by SA2
      prices.py        Valuer-General median house/unit series (2014-2024)
      rents.py         DFFH median weekly rents by suburb -> gross yields
      transport.py     DTP train stations + patronage -> station access
      schools.py       Dept of Education school locations -> school access
      zoning.py        VicPlan zones + Heritage Overlay sampled per SA2
      electricity.py   Geoscience Australia transmission network
  public/              the deployed static site (Leaflet map, scorecard, sliders)
    data/ melbourne.geojson  scores.json  explanations.json  stations.geojson  electricity.geojson
  scripts/             double-click launchers: .bat (Windows) + .sh (macOS/Linux)
  data_raw/            cached source downloads (gitignored)
```

## Run it

On Windows, double-click **`scripts/Start Melbourne Property.bat`** (serves the site at
http://localhost:8766) and **`scripts/Refresh Data.bat`** to rebuild. On macOS/Linux, run
**`scripts/start.sh`** and **`scripts/refresh-data.sh`** instead. Or from a terminal:

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m engine.run          # build public/data/*
.venv\Scripts\python -m http.server 8766 --directory public
```

`python -m engine.run --geo-only` rebuilds just the map; `--force` re-downloads cached sources.

## Data sources (all free / public)

| Layer | Source |
|---|---|
| Suburb boundaries | ABS ASGS Edition 3 **SA2** (2021) shapefile |
| Crime | **Crime Statistics Agency Victoria** — criminal incidents **by suburb/town** (354/361 SA2s; LGA fallback), split into person (Division A) vs property (Division B), year ending Mar 2026 |
| Socio-economic | ABS **SEIFA 2021** — **IRSAD + IEO** by SA2 (Digital Atlas of Australia ArcGIS) |
| Housing mix | ABS **Census 2021 G37** (tenure × dwelling structure) by SA2 (Digital Atlas) |
| Demographics | ABS **Census 2021 G01** (age 0–14 child share) by SA2 (Digital Atlas) |
| Property prices | **Victorian Valuer-General** — Median House & Unit (2014–2024) by suburb time series; suburb→SA2 by name matching. land.vic is WAF-blocked, so files are pulled via the Wayback Machine |
| Rents & yields | **DFFH Rental Report** — moving annual median weekly rents by suburb (LGA fallback), Sep 2025 → gross house/unit yields |
| Planning zones | **Vicmap Planning / VicPlan** — planning-scheme zones + **Heritage Overlay**, grid-sampled per SA2 into growth / standard / restrictive / heritage shares |
| Trains | **DTP** annual station patronage (metro + V/Line) with station locations, FY2024-25 → nearest-station access + map overlay |
| Schools | **Vic Dept of Education** — School Locations 2025 (all sectors) → school access |
| Electricity infrastructure | **Geoscience Australia** National Electricity Infrastructure (transmission lines + substations, v4 2024) via ArcGIS MapServer; per-SA2 proximity/density computed in pure Python |
| LGA→SA2 join | computed spatially from ABS **LGA 2022** boundaries |

**Caveat:** a handful of SA2s still fall back to LGA-level crime or rents — each scorecard shows a
data-coverage line so you can see exactly what a suburb's scores are based on.

## Scoring

Each input is converted to a **percentile (0–100) within Greater Melbourne** (higher = better; crime,
social housing and density are inverted), then blended with the weights in `engine/config.py`:

- **Liveability (base — Balanced/Invest)** = 33% personal safety + 25% SEIFA IRSAD +
  10% train access + 9% owner-occupier + 7% school access + 6% property safety + 5% child share +
  **5% hazard-free** (less flood/bushfire overlay coverage).
- **Liveability (Family-First — Live mode)** = 33% personal safety + 18% SEIFA + **15% child share**
  + **12% school access** + 8% owner-occupier + 7% train access + 4% hazard-free +
  **3% property safety**. The engine ships both as `live` and `live_family`.
- **Family Suitability** (badge) = 32% child share + 28% SEIFA IEO + 22% personal safety +
  18% school access.
- **Development potential** = **19% detached headroom + 17% zoning upside** (growth-zone share,
  with restrictive zones penalised) + 12% recent capital growth (VG 3-year CAGR) + 12%
  electricity-network support + 10% station access + **8% gross rental yield** (unit basis where
  units dominate) + 7% renter turnover + 5% low density + **5% heritage-free** + **5% hazard-free**.
  Two percentile-stretched **sub-lenses** ship alongside: `dev_green` (Greenfield: UGZ corridors)
  and `dev_infill` (Infill: upzoned + station-centred established suburbs). The scorecard's
  **Market & Price**, **Planning, Zoning & Hazards** and **Trains & Schools** blocks lead in
  Invest/Develop modes; a toggle overlays train stations. (Electricity-grid support still feeds
  the score but no longer has its own display surfaces.)
- **Overall** = `slider × Liveability + (1 − slider) × Development`. Liveability and Development are
  re-ranked 0–100 across all SA2s; letter grades are tiers of the default-blend Overall (A+ = top
  ~10%). Station/school distances are measured from **residentially-zoned sample points**, missing
  inputs are excluded with weights renormalised, and a **⚖ Customise weights** panel rebuilds every
  score client-side (shareable via the URL).

**One-click presets** (set the slider + colour-by + palette; slider still overrides):
Family First (85/15), Pure Safety (95/5), Balanced Investor (45/55), Value-Add/Developer (20/80).
The **How scores are calculated** panel updates live with the active mode's weights.

All weights live in `engine/config.py` and the **How scores are calculated** panel renders them from
the JSON. The JSON ships per-pillar scores so the Overall blend recomputes instantly in JS when you
move the slider — no rebuild needed.

## New signals (P6)

The engine also scores **affordability** (median house ÷ Census median household income),
**population growth** (ERP year-on-year — feeds the Greenfield lens), a **4-year crime trend**
per suburb, **parks/green-space share** (PPRZ/PCRZ) in Liveability, **airport-noise overlays**
(MAEO/AEO — "Flight path" tag), unit price momentum, and rental-bond counts. Source URLs
self-upgrade (CSA quarter probing, DFFH CKAN discovery, ERP next-year-first) with pinned
fallbacks, and caches age out via `fresh()` so quarterly data refreshes itself. Engine unit
tests live in `engine/tests/` (`python -m unittest discover -s engine/tests`).

## Optional AI answers

`cloudflare-worker/` contains a small Cloudflare Worker that proxies Ask questions to Claude
(so no API key ever ships in the static site) and returns a grounded summary of the matched
suburbs. The site is fully functional without it — see `cloudflare-worker/README.md` to enable.

## Roadmap

- **P2** Property prices & growth (Victorian Valuer-General) — ✅ **done**
- **P3** Electricity network (Geoscience Australia) — grid-support scoring — ✅ **done** (the map
  overlay + scorecard surfaces were later removed to simplify the UI)
- **P4** Suburb-level crime, rents/yields, stations, schools, **VicPlan zoning + Heritage Overlay**,
  compare mode, address search, shareable URLs — ✅ **done**
- **P5** Flood (LSIO/SBO/FO) + bushfire (BMO) overlays, ERP 2025 populations, Greenfield/Infill
  sub-lenses, residential-weighted distances, custom weights — ✅ **done**
- **P6** Affordability/income, population growth, crime trends, parks + airport noise, Ask,
  shortlist, 3-way compare, PWA/offline, engine tests, CI minify + monthly refresh — ✅ **done**
- **P7** Height/design overlays (DDO), vegetation controls, land values, GTFS travel times,
  a second city and the road to all of Australia — the city profile now lives in
  `engine/config.py` and ships in the data, so a new city is a profile + per-state
  source adapters. The full state-by-state source matrix, decisions (per-city
  percentiles, per-city data dirs) and sequencing live in **`docs/AUSTRALIA.md`**.

## Deploy

Every push to `main` publishes `public/` to **GitHub Pages** automatically
(`.github/workflows/pages.yml`) — the live site is at
https://fakecurrency.github.io/melbourne-property/.
The folder is plain static files, so it can also be hosted anywhere static.

The deploy minifies JS/CSS on the runner and stamps every asset + data URL with the run number,
so browsers always pick up fresh code and data together (no manual cache-version bumps).

**Data refresh:** the **Refresh Data** workflow (Actions tab → Refresh Data → Run workflow)
rebuilds `public/data/` in the cloud from all sources and commits the result — no local machine
needed. It runs automatically on the 1st of each month, caches raw downloads between runs,
snapshots the previous grades to `prev-scores.json` (the site shows ▲▼ grade-trend arrows),
refuses to commit coverage regressions, warns on large grade drift, and files a GitHub issue
if a run fails. A `restore_sha` input rolls `public/data` back to any previous commit.

## Licence

Code is **MIT** (see `LICENSE`). Source data remains © its publishers (ABS, Victorian agencies,
Geoscience Australia) under **CC BY 4.0** — attribution is in the app's Guide → Data & sources.
