# Melbourne Property — live, invest & develop scores by suburb

One app that helps with three Melbourne decisions — *where's safer to live/rent*, *where an
investment stacks up*, and *where there's room to add value/develop* — by ranking every **Greater
Melbourne suburb** with two 0–100 scores plus a blended overall:

- **Liveability** — *can you live/rent here safely?* **Personal safety leads** (crimes against the
  person weighted far above property crime), plus SEIFA advantage, owner-occupier stability, and a
  **Family Suitability** signal (child share + education/occupation + safety) surfaced as a badge.
- **Development potential** *(v1 = preliminary)* — *room to add value?* Redevelopment headroom from
  low-density detached housing, renter turnover and low current density. Zoning, electricity (AEMO)
  and land-value layers come in later phases.

**Three audience modes** set smart starting weights, palettes and explanations:
🟢 **Live** (safe/stable family base) · ⚖️ **Balanced** · 🔵 **Invest / Develop** (value-add upside).
The weight slider stays adjustable in every mode, blending the two into the **Overall** score live in
the browser. Light/dark mode included.

> General information only — not financial or planning advice.

## How it's built

A small **Python engine** downloads free government data, joins it on the ABS **SA2** suburb code,
scores it, and writes JSON + GeoJSON into `public/`. The site is a static **Leaflet** map — no API
keys, no backend. Pure-Python dependencies only (`requests`, `openpyxl`, `pyshp`), so it installs
cleanly even on Python 3.14.

```
melb-scorer/
  engine/
    config.py          city, score weights, grade cut-offs        <- tune here
    fetch.py           cached downloads + ArcGIS query helper
    geo.py             ABS SA2 boundaries -> simplified GeoJSON (pure-Python Douglas-Peucker)
    score.py           percentile-normalise -> Liveability + Development -> blend + grade
    build.py / run.py  orchestrate: sources -> join on SA2 -> public/data/scores.json
    sources/
      crime.py         CSA Vic criminal incidents by LGA -> SA2 (spatial point-in-polygon)
      census.py        ABS SEIFA + Census G37 (tenure x dwelling) by SA2
  public/              the deployed static site (Leaflet map, scorecard, sliders)
    data/ melbourne.geojson  scores.json
  data_raw/            cached source downloads (gitignored)
```

## Run it

Double-click **`Start Melbourne Property.bat`** (serves the site at http://localhost:8766) and
**`Refresh Data.bat`** to rebuild. Or from a terminal:

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
| Crime | **Crime Statistics Agency Victoria** — recorded offences by LGA, **split into person (Division A) vs property (Division B)** rates (year ending Mar 2026) |
| Socio-economic | ABS **SEIFA 2021** — **IRSAD + IEO** by SA2 (Digital Atlas of Australia ArcGIS) |
| Housing mix | ABS **Census 2021 G37** (tenure × dwelling structure) by SA2 (Digital Atlas) |
| Demographics | ABS **Census 2021 G01** (age 0–14 child share) by SA2 (Digital Atlas) |
| Property prices | **Victorian Valuer-General** — Median House (2014–2024) & Unit (2013–2023) by suburb time series; suburb→SA2 by name matching. land.vic is WAF-blocked, so files are pulled via the Wayback Machine |
| Electricity infrastructure | **Geoscience Australia** National Electricity Infrastructure (transmission lines + substations, v4 2024) via ArcGIS MapServer; per-SA2 proximity/density computed in pure Python |
| LGA→SA2 join | computed spatially from ABS **LGA 2022** boundaries |

**Caveat:** crime is published per LGA, so every suburb in an LGA shares its rate (a wealthy pocket
can inherit a busy retail strip's crime). Suburb-level crime is a planned refinement.

## Scoring

Each input is converted to a **percentile (0–100) within Greater Melbourne** (higher = better; crime,
social housing and density are inverted), then blended with the weights in `engine/config.py`:

- **Liveability (base — Balanced/Invest)** = 40% personal safety + 33% SEIFA IRSAD + 12%
  owner-occupier + 7% property safety + 8% child share.
- **Liveability (Family-First — Live mode)** = 40% personal safety + **20% child share** + 24% SEIFA
  + 12% owner-occupier + **4% property safety**. For a "raise my kids here" lens, property crime is
  down-weighted and the child signal raised; the engine ships both as `live` and `live_family`.
- **Family Suitability** (badge) = 40% child share + 35% SEIFA IEO + 25% personal safety.
- **Development potential** = 35% detached headroom + **20% recent capital growth** (VG 3-year CAGR) +
  **20% electricity-network support** + 15% renter turnover + 10% low density. The electricity
  sub-score = 45% transmission proximity + 30% substation proximity + 25% substation density
  (Geoscience Australia). The scorecard's **Market & Price** and **Infrastructure & Electricity**
  blocks lead in Invest/Develop modes and condense in Live/Family; a toggle overlays the actual
  transmission lines + substations on the map.
- **Overall** = `slider × Liveability + (1 − slider) × Development`.

**One-click presets** (set the slider + colour-by + palette; slider still overrides):
Family First (85/15), Pure Safety (95/5), Balanced Investor (45/55), Value-Add/Developer (20/80).
The **How scores are calculated** panel updates live with the active mode's weights.

All weights live in `engine/config.py` and the **How scores are calculated** panel renders them from
the JSON. The JSON ships per-pillar scores so the Overall blend recomputes instantly in JS when you
move the slider — no rebuild needed.

## Roadmap

- **P2** Property prices & growth (Victorian Valuer-General) — ✅ **done**
- **P3** Electricity network (Geoscience Australia) — map overlay + 20% of Development — ✅ **done**
- **P4** Planning zoning + overlays (Vicmap) → true development potential; then address-level lookup

## Deploy

Every push to `main` publishes `public/` to **GitHub Pages** automatically
(`.github/workflows/pages.yml`) — the live site is at
https://fakecurrency.github.io/melbourne-property/.
The folder is plain static files, so it can also be hosted anywhere static.
