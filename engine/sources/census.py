"""Census-derived inputs per SA2: SEIFA advantage + housing mix.

Both come from ABS datasets published on the Digital Atlas of Australia as
ArcGIS feature services (cleaner than parsing DataPack zips):
  * SEIFA 2021 by SA2        -> IRSAD score/decile, usual resident population
  * Census 2021 G37 by SA2   -> tenure x dwelling-structure counts
"""
from __future__ import annotations

import json

from .. import config
from ..fetch import arcgis_query_all

_ABS = "https://services1.arcgis.com/v8Kimc579yljmjSP/ArcGIS/rest/services"
SEIFA_LAYER = f"{_ABS}/SA2_2021_SEIFA_v3/FeatureServer/0"
G37_LAYER = f"{_ABS}/ABS_2021_Census_G37_Beta/FeatureServer/4"
# G01 "Selected person characteristics by sex" — layer 4 is SA2; used for child share.
G01_LAYER = f"{_ABS}/ABS_2021_Census_G01_Selected_person_characteristics_by_sex_Beta/FeatureServer/4"

_SEIFA_FIELDS = (
    "SA2_CODE_2021,IRSAD_score,IRSAD_decile,IRSAD_percentile,"
    "IEO_score,IEO_decile,AREA_ALBERS_SQKM,urp_2021"
)
_G37_FIELDS = (
    "SA2_CODE_2021,Total_Total,O_OR_Total,O_MTG_Total,"
    "R_Tot_Total,R_ST_h_auth_Total,Total_DS_Sep_house"
)
_G01_FIELDS = "SA2_CODE_2021,Tot_P_P,Age_0_4_yr_P,Age_5_14_yr_P"


def _cached(name: str, layer: str, fields: str) -> list[dict]:
    path = config.DATA_RAW / name
    if path.exists() and path.stat().st_size > 0:
        print(f"  cached  {name}")
        return json.loads(path.read_text(encoding="utf-8"))
    print(f"  querying ArcGIS {name} ...")
    rows = arcgis_query_all(layer, fields)
    config.DATA_RAW.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows), encoding="utf-8")
    print(f"  fetched {len(rows)} rows -> {name}")
    return rows


def get_seifa() -> dict[str, dict]:
    """{sa2_code: {irsad/ieo scores+deciles, population, area_sqkm, density}}"""
    out = {}
    for a in _cached("seifa_sa2.json", SEIFA_LAYER, _SEIFA_FIELDS):
        code = str(a.get("SA2_CODE_2021") or "").strip()
        if not code:
            continue
        pop = a.get("urp_2021")
        area = a.get("AREA_ALBERS_SQKM")
        out[code] = {
            "irsad_score": a.get("IRSAD_score"),
            "irsad_decile": a.get("IRSAD_decile"),
            "irsad_pct": a.get("IRSAD_percentile"),
            "ieo_score": a.get("IEO_score"),
            "ieo_decile": a.get("IEO_decile"),
            "population": pop,
            "area_sqkm": area,
            "density": (pop / area) if (pop and area) else None,  # persons / km^2
        }
    return out


def get_demographics() -> dict[str, dict]:
    """{sa2_code: {child_share}} — share of population aged 0-14 (family proxy)."""
    out = {}
    for a in _cached("census_g01_sa2.json", G01_LAYER, _G01_FIELDS):
        code = str(a.get("SA2_CODE_2021") or "").strip()
        tot = a.get("Tot_P_P") or 0
        if not code or not tot:
            continue
        kids = (a.get("Age_0_4_yr_P") or 0) + (a.get("Age_5_14_yr_P") or 0)
        out[code] = {"child_share": kids / tot}
    return out


def get_housing() -> dict[str, dict]:
    """{sa2_code: {dwellings, owner_occ, mortgage, rental, social, detached}} as shares 0-1."""
    out = {}
    for a in _cached("census_g37_sa2.json", G37_LAYER, _G37_FIELDS):
        code = str(a.get("SA2_CODE_2021") or "").strip()
        total = a.get("Total_Total") or 0
        if not code or not total:
            continue
        owned = (a.get("O_OR_Total") or 0) + (a.get("O_MTG_Total") or 0)
        out[code] = {
            "dwellings": total,
            "owner_occ": owned / total,
            "mortgage": (a.get("O_MTG_Total") or 0) / total,
            "rental": (a.get("R_Tot_Total") or 0) / total,
            "social": (a.get("R_ST_h_auth_Total") or 0) / total,
            "detached": (a.get("Total_DS_Sep_house") or 0) / total,
        }
    return out


def get_income() -> dict[str, dict]:
    """{sa2_code: {income_weekly}} — median household income from the Census
    G02 DataPack (the Digital Atlas has no G02 service). Static 2021 figures;
    used for a price-to-income affordability ratio (caveated as 2021 income)."""
    import csv
    import io
    import zipfile

    from ..fetch import fetch
    # per-state DataPack (the G02 table isn't served nationally by the Atlas)
    st = config.STATE_CODE
    url = ("https://www.abs.gov.au/census/find-census-data/datapacks/download/"
           f"2021_GCP_SA2_for_{st}_short-header.zip")
    path = fetch(url, f"census_gcp_sa2_{st.lower()}.zip")
    out = {}
    with zipfile.ZipFile(path) as z:
        g02 = next(n for n in z.namelist() if "G02" in n and n.endswith(".csv"))
        with z.open(g02) as fh:
            for r in csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8-sig")):
                code = str(r.get("SA2_CODE_2021", "")).strip()
                inc = r.get("Median_tot_hhd_inc_weekly")
                try:
                    inc = float(inc)
                except (TypeError, ValueError):
                    inc = None
                if code and inc:
                    out[code] = {"income_weekly": inc}
    print(f"  income: household medians for {len(out)} SA2s (Census 2021 G02)")
    return out


if __name__ == "__main__":  # pragma: no cover
    seifa = get_seifa()
    housing = get_housing()
    print(f"SEIFA rows: {len(seifa)}  Housing rows: {len(housing)}")
    # spot-check a known affluent Melbourne SA2 (Toorak = 206051138)
    for code in ("206051138",):
        print(code, "SEIFA:", seifa.get(code), "HOUSING:", housing.get(code))
