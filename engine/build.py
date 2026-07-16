"""Orchestrate the full build: geography + sources -> scored JSON for the site."""
from __future__ import annotations

import datetime as dt
import json

from . import config, geo, score
from .sources import census, crime, electricity, erp, prices, rents, schools, transport, zoning

SOURCES_NOTE = {
    "boundaries": "ABS ASGS Edition 3 SA2 (2021)",
    "crime": "Crime Statistics Agency Victoria — criminal incidents by suburb/town (LGA fallback), person vs property split, YE Mar 2026",
    "seifa": "ABS SEIFA 2021 (IRSAD + IEO) by SA2",
    "housing": "ABS Census 2021 G37 (tenure x dwelling structure) by SA2",
    "demographics": "ABS Census 2021 G01 (age 0-14 child share) by SA2",
    "population": "ABS Regional Population — ERP at 30 June 2025 by SA2 (density + crime denominators)",
    "prices": "Victorian Valuer-General — Median House/Unit by Suburb time series (2014-2024)",
    "rents": "DFFH Rental Report — moving annual median rents by suburb (LGA fallback), Sep 2025",
    "transport": "DTP annual train-station patronage (metro + V/Line) station locations, FY2024-25",
    "schools": "Vic Dept of Education — School Locations 2025 (all sectors)",
    "zoning": "Vicmap Planning / VicPlan — planning-scheme zones + Heritage/flood (LSIO/SBO/FO)/bushfire (BMO) overlays (sampled per SA2)",
    "electricity": "Geoscience Australia — National Electricity Infrastructure (transmission lines + substations, v4 2024)",
}


def _load_sa2_index() -> tuple[dict[str, dict], dict[str, dict]]:
    """SA2 code -> name/sa3/sa4 plus code -> geometry from the boundary GeoJSON."""
    path = config.PUBLIC_DATA / "melbourne.geojson"
    if not path.exists():
        geo.build_geojson()
    fc = json.loads(path.read_text(encoding="utf-8"))
    idx, geoms = {}, {}
    for f in fc["features"]:
        p = f["properties"]
        idx[p["sa2_code"]] = {"name": p["sa2_name"], "sa3": p["sa3_name"], "sa4": p["sa4_name"]}
        geoms[p["sa2_code"]] = f["geometry"]
    return idx, geoms


def _yield_pct(weekly_rent, price):
    if not weekly_rent or not price:
        return None
    return round(weekly_rent * 52 / price * 100, 2)


def build() -> None:
    print("1/9 boundaries"); index, geoms = _load_sa2_index()
    names = {code: m["name"] for code, m in index.items()}
    points = geo.melbourne_sa2_points()

    print("2/9 census (SEIFA + housing + demographics + income) + ERP")
    seifa = census.get_seifa()
    housing = census.get_housing()
    demo = census.get_demographics()
    try:
        income = census.get_income()
    except Exception as e:  # noqa: BLE001 - affordability degrades gracefully
        print(f"  income unavailable ({e}); shipping without affordability ratios")
        income = {}
    erp_data = erp.get_erp()
    # Current population: ERP (June 2025) with Census 2021 fallback. Density and
    # crime denominators use this, so growth corridors aren't over-penalised.
    pops = {}
    for c in index:
        e = erp_data.get(c)
        pops[c] = e["erp"] if e else (seifa.get(c) or {}).get("population")

    print("3/9 crime (suburb-level + LGA fallback)")
    crime_lga = crime.get_crime()
    lgas = {c: crime_lga[c].get("lga") for c in index}
    crime_sub = crime.get_crime_suburb(names, pops, lgas)
    postcodes = crime.get_postcode_map(names, lgas)

    print("4/9 prices (Valuer-General)")
    price_data = prices.get_prices(names)
    print("5/9 rents (DFFH Rental Report)")
    rent_data = rents.get_rents(names, lgas)
    print("6/9 zoning + overlays (VicPlan)")
    zone_data = zoning.get_zoning(geoms)

    def _lived_in_points(z):
        """Established urban residential first; UGZ then LDRZ ONLY when a tier is
        empty — two real township points beat eleven empty growth-front paddocks."""
        return (z.get("res_points") or z.get("ugz_points") or z.get("ldrz_points") or [])
    res_pts = {c: _lived_in_points(z) for c, z in zone_data.items()}
    print("7/9 transport (train stations, residential-weighted)")
    station_data = transport.get_stations(points, res_pts)
    print("8/9 schools (residential-weighted) + electricity (Geoscience Australia)")
    school_data = schools.get_schools(points, res_pts)
    infra_data = electricity.get_infra(points)

    print("9/9 scoring")
    records = {}
    for code, meta in index.items():
        s = seifa.get(code, {})
        h = housing.get(code, {})
        d = demo.get(code, {})
        cl = crime_lga.get(code, {})
        cs = crime_sub.get(code, {})
        pr = price_data.get(code, {})
        rn = rent_data.get(code, {})
        st = station_data.get(code, {})
        sc = school_data.get(code, {})
        zn = zone_data.get(code, {})
        inf = infra_data.get(code, {})
        pop = pops.get(code)
        area = s.get("area_sqkm")
        # Employment precincts (airports, industrial estates): almost nobody lives
        # there, so per-resident suburb rates are meaningless — use LGA rates.
        precinct = pop is not None and pop < config.PRECINCT_POP_FLOOR
        crime_vals = cs if (cs and not precinct) else cl
        records[code] = {
            "name": meta["name"], "sa3": meta["sa3"], "sa4": meta["sa4"],
            "lga": cl.get("lga"),
            "person_crime": crime_vals.get("person"), "property_crime": crime_vals.get("property"),
            "total_crime": crime_vals.get("total"),
            "person_trend_pct": cs.get("person_trend_pct") if (cs and not precinct) else None,
            "crime_source": "suburb" if (cs and not precinct) else "lga",
            "precinct": precinct,
            "irsad_score": s.get("irsad_score"), "irsad_decile": s.get("irsad_decile"),
            "ieo_score": s.get("ieo_score"), "ieo_decile": s.get("ieo_decile"),
            "population": pop, "pop_year": (erp_data.get(code) or {}).get("erp_year"),
            "pop_growth_pct": (erp_data.get(code) or {}).get("erp_growth_pct"),
            "income_weekly": (income.get(code) or {}).get("income_weekly"),
            "density": (pop / area) if (pop and area) else None,
            "child_share": d.get("child_share"),
            "owner_occ": h.get("owner_occ"), "mortgage": h.get("mortgage"),
            "rental": h.get("rental"), "social": h.get("social"),
            "detached": h.get("detached"),
            "median_house": pr.get("median_house"), "median_unit": pr.get("median_unit"),
            "house_12m": pr.get("house_12m"), "house_3yr_cagr": pr.get("house_3yr_cagr"),
            "unit_12m": pr.get("unit_12m"), "unit_3yr_cagr": pr.get("unit_3yr_cagr"),
            "house_year": pr.get("house_year"), "unit_year": pr.get("unit_year"),
            "house_series": pr.get("house_series"),
            "rent_weekly": rn.get("rent_weekly"), "rent_12m": rn.get("rent_12m"),
            "rent_bonds": rn.get("rent_bonds"),
            "rent_quarter": rn.get("rent_quarter"), "rent_source": rn.get("rent_source"),
            "yield_house": _yield_pct(rn.get("house_rent"), pr.get("median_house")),
            "yield_unit": _yield_pct(rn.get("flat_rent"), pr.get("median_unit")),
            # headline yield: units where units dominate the stock (3BR-house rent
            # against a unit-heavy market median otherwise misstates the economics)
            "yield_basis": ("unit" if (h.get("detached") is not None and h["detached"] < 0.35
                                       and _yield_pct(rn.get("flat_rent"), pr.get("median_unit")))
                            else "house"),
            "nearest_station_km": st.get("nearest_station_km"),
            "nearest_station": st.get("nearest_station"),
            "stations_3km": st.get("stations_3km"), "station_pax": st.get("station_pax"),
            "metro_km": st.get("metro_km"), "metro_station": st.get("metro_station"),
            "metro_pax": st.get("metro_pax"),
            "vline_km": st.get("vline_km"), "vline_station": st.get("vline_station"),
            "vline_pax": st.get("vline_pax"),
            "nearest_primary_km": sc.get("nearest_primary_km"),
            "nearest_secondary_km": sc.get("nearest_secondary_km"),
            "schools_3km": sc.get("schools_3km"),
            "zoning_raw": zn.get("zoning_raw"),
            "growth_share": zn.get("growth_share"), "standard_share": zn.get("standard_share"),
            "restrict_share": zn.get("restrict_share"), "heritage_share": zn.get("heritage_share"),
            "ugz_share": zn.get("ugz_share"), "parks_share": zn.get("parks_share"),
            "flood_share": zn.get("flood_share"), "bushfire_share": zn.get("bushfire_share"),
            "noise_share": zn.get("noise_share"),
            "zone_mix": zn.get("zone_mix"),
            "nearest_transmission_km": inf.get("nearest_transmission_km"),
            "nearest_substation_km": inf.get("nearest_substation_km"),
            "substation_count_10km": inf.get("substation_count_10km"),
            "nearest_line_kv": inf.get("nearest_line_kv"),
        }
    scored = score.compute_scores(records)

    # Explanation prose ships in a separate lazy-loaded file so the boot payload
    # stays small. Infra prose is dropped — the UI no longer displays it.
    expl = {}
    for code, area in scored.items():
        area.pop("explanation_infra", None)
        e = {k: area.pop(f"explanation_{k}", None) for k in ("live", "dev", "invest")}
        expl[code] = {k: v for k, v in e.items() if v}

    payload = {
        "city": config.GCC_NAME,
        "state": config.STATE_CODE,       # keys the frontend's per-state tables
        "regions": config.CITY_REGIONS,   # Ask box compass-word -> SA4 filter
        "generated": dt.date.today().isoformat(),
        "count": len(scored),
        "default_blend": config.DEFAULT_BLEND,
        "mode_presets": config.MODE_PRESETS,
        "presets": config.PRESETS,
        "weights": {"liveability": config.LIVE_WEIGHTS,
                    "liveability_family": config.LIVE_WEIGHTS_FAMILY,
                    "development": config.DEV_WEIGHTS, "family": config.FAMILY_WEIGHTS,
                    "dev_greenfield": config.DEV_GREENFIELD_WEIGHTS,
                    "dev_infill": config.DEV_INFILL_WEIGHTS},
        "sources": SOURCES_NOTE,
        "postcodes": postcodes,
        "areas": scored,
    }
    config.PUBLIC_DATA.mkdir(parents=True, exist_ok=True)
    out = config.PUBLIC_DATA / "scores.json"
    out.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    print(f"  wrote {out.name}: {len(scored)} areas, {out.stat().st_size/1e6:.2f} MB")
    expl_out = config.PUBLIC_DATA / "explanations.json"
    expl_out.write_text(json.dumps(expl, separators=(",", ":")), encoding="utf-8")
    print(f"  wrote {expl_out.name}: {len(expl)} areas, {expl_out.stat().st_size/1e6:.2f} MB")


if __name__ == "__main__":  # pragma: no cover
    build()
