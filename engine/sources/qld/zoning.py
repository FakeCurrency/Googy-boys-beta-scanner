"""QLD planning inputs — a three-source hybrid (no statewide zoning layer).

1. Brisbane City Council LGA: real City Plan 2014 zone polygons from BCC's
   opendatasoft portal (26k polygons; zone_code LDR/LMR/MDR/HDR/..., lvl2
   text), fetched per-SA2-bbox via the exports API.
2. Everywhere else: the statewide "Queensland Land Use - Current" ArcGIS
   layer classifies each grid point by actual use (urban residential, rural
   residential, commercial, grazing, ...) — land use, not zoning intent, but
   it separates growth/standard/restrict well enough for v1.
3. One ShapingSEQ 2023 point query per SA2 labels the fallback for points the
   other two miss (inside the Urban Footprint vs regional landscape). The
   full ShapingSEQ polygons are NOT pulled — the Urban Footprint is a single
   SEQ-wide geometry far too large to point-test per SA2.

"Emerging community" is BCC's greenfield zone and plays the Vic UGZ role;
rural-residential plays LDRZ. flood/bushfire/noise/heritage ship as None.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import requests

from ... import config
from ...fetch import fresh
from ..zoning import _bbox, _grid_points, _in_polys, _query, _rings_of

BCC_EXPORT = ("https://data.brisbane.qld.gov.au/api/explore/v2.1/catalog/datasets/"
              "cp14-zoning-overlay/exports/geojson")
LANDUSE_URL = ("https://spatial-gis.information.qld.gov.au/arcgis/rest/services/"
               "PlanningCadastre/LandUse/MapServer/0/query")
SEQ_RLUC_URL = ("https://spatial-gis.information.qld.gov.au/arcgis/rest/services/"
                "PlanningCadastre/StatePlanning/MapServer/140/query")
_UA = {"User-Agent": "Mozilla/5.0 (compatible; melbourne-property-recon)"}

# BCC lvl2_zone keyword groups (checked lowercase, first match wins)
BCC_GROWTH = ("medium density", "high density", "low-medium", "mixed use",
              "centre", "emerging community", "specialised centre")
BCC_STANDARD = ("low density residential", "tourist", "township")
BCC_RESTRICT = ("character residential", "rural", "environmental", "conservation",
                "industr", "special purpose", "open space", "sport", "community facilities",
                "extractive")
BCC_RES = ("residential", "mixed use", "emerging community", "township", "character")
BCC_PARKS = ("open space", "sport", "conservation")
BCC_UGZ = ("emerging community",)
BCC_LDRZ = ("rural residential",)


def _bcc_zone_class(lvl2: str) -> str | None:
    z = lvl2.lower()
    if any(k in z for k in BCC_GROWTH):
        return "growth"
    if any(k in z for k in BCC_STANDARD):
        return "standard"
    if any(k in z for k in BCC_RESTRICT):
        return "restrict"
    return None


def _bcc_features(bbox) -> list:
    """BCC zone polygons intersecting the bbox: [(code, lvl2, rings, rbbox)]."""
    x0, y0, x1, y1 = bbox
    r = requests.get(BCC_EXPORT, params={
        "where": f"in_bbox(geo_shape, {y0}, {x0}, {y1}, {x1})",
        "select": "zone_code, lvl2_zone",
    }, headers=_UA, timeout=120)
    r.raise_for_status()
    out = []
    for f in r.json().get("features", []):
        if not f.get("geometry"):
            continue
        rings = _rings_of(f["geometry"])
        if not rings:
            continue
        p = f.get("properties") or {}
        out.append((str(p.get("zone_code") or ""), str(p.get("lvl2_zone") or ""),
                    rings, _bbox(rings)))
    return out


def _landuse_features(bbox) -> list:
    """Land-use polygons intersecting the bbox: [(tertiary, rings, rbbox)]."""
    out = []
    for f in _query(LANDUSE_URL, bbox, "tertiary"):
        if not f.get("geometry"):
            continue
        rings = _rings_of(f["geometry"])
        if not rings:
            continue
        p = f.get("properties") or f.get("attributes") or {}
        out.append((str(p.get("tertiary") or "").lower(), rings, _bbox(rings)))
    return out


def _seq_rluc(lon, lat) -> str:
    """ShapingSEQ regional land use category at a point ('' if none)."""
    try:
        r = requests.get(SEQ_RLUC_URL, params={
            "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint",
            "inSR": 4326, "spatialRel": "esriSpatialRelIntersects",
            "outFields": "rluc2023", "returnGeometry": "false", "f": "json",
        }, headers=_UA, timeout=60)
        r.raise_for_status()
        feats = r.json().get("features") or []
        return str((feats[0].get("attributes") or {}).get("rluc2023") or "") if feats else ""
    except Exception:  # noqa: BLE001 - fallback label only
        return ""


def _landuse_class(tert: str) -> tuple[str, str, bool, bool]:
    """(class, code, is_res, is_ldrz) for a land-use tertiary string."""
    if "urban residential" in tert or "manufactured home" in tert:
        return "standard", "RES", True, False
    if "rural residential" in tert or "rural living" in tert:
        return "restrict", "RURES", True, True
    if any(k in tert for k in ("commercial", "public services", "recreation", "utilit",
                               "transport", "communication")):
        return "standard", "URBAN", False, False
    if any(k in tert for k in ("manufacturing", "industrial", "mines", "quarr", "waste")):
        return "restrict", "IND", False, False
    return "", "", False, False


def _shares_for(sa2_geom: dict, centroid: tuple[float, float]) -> dict | None:
    polys = _rings_of(sa2_geom)
    if not polys:
        return None
    bbox = _bbox(polys)
    pts = _grid_points(polys, bbox)
    if not pts:
        return None

    bcc = _bcc_features(bbox)
    landuse = None                    # fetched lazily — only non-BCC SA2s need it

    n = len(pts)
    tally: dict[str, int] = {}
    growth = standard = restrict = parks = ugz = lowden = 0
    res_points: list[list[float]] = []
    ugz_points: list[list[float]] = []
    ldrz_points: list[list[float]] = []
    unmatched: list[tuple[float, float]] = []

    for x, y in pts:
        hit = None
        for code, lvl2, rings, rb in bcc:
            if rb[0] <= x <= rb[2] and rb[1] <= y <= rb[3] and _in_polys(x, y, rings):
                hit = (code, lvl2)
                break
        if hit is None:
            unmatched.append((x, y))
            continue
        code, lvl2 = hit
        cls = _bcc_zone_class(lvl2)
        tally[code or "?"] = tally.get(code or "?", 0) + 1
        z = lvl2.lower()
        if cls == "growth":
            growth += 1
        elif cls == "standard":
            standard += 1
        elif cls == "restrict":
            restrict += 1
        if any(k in z for k in BCC_PARKS):
            parks += 1
        if any(k in z for k in BCC_RES):
            res_points.append([round(x, 4), round(y, 4)])
        if any(k in z for k in BCC_UGZ):
            ugz += 1
            ugz_points.append([round(x, 4), round(y, 4)])
        if any(k in z for k in BCC_LDRZ):
            lowden += 1
            ldrz_points.append([round(x, 4), round(y, 4)])

    if unmatched:
        if len(unmatched) > 0.05 * n:
            landuse = _landuse_features(bbox)
        rluc = _seq_rluc(*centroid).lower()
        uf = "urban footprint" in rluc
        for x, y in unmatched:
            cls = code = ""
            is_res = is_ldrz = False
            if landuse:
                for tert, rings, rb in landuse:
                    if rb[0] <= x <= rb[2] and rb[1] <= y <= rb[3] and _in_polys(x, y, rings):
                        cls, code, is_res, is_ldrz = _landuse_class(tert)
                        break
            if not cls:
                cls, code = ("standard", "URBAN") if uf else ("restrict", "RURAL")
            tally[code] = tally.get(code, 0) + 1
            if cls == "growth":
                growth += 1
            elif cls == "standard":
                standard += 1
            else:
                restrict += 1
            if is_res:
                res_points.append([round(x, 4), round(y, 4)])
            if is_ldrz:
                lowden += 1
                ldrz_points.append([round(x, 4), round(y, 4)])

    gs, ss, rs = growth / n, standard / n, restrict / n
    mix = sorted(((c, k / n) for c, k in tally.items()), key=lambda t: -t[1])[:5]
    return {
        "zoning_raw": round(gs + 0.45 * ss - 0.35 * rs, 4),
        "growth_share": round(gs, 4), "standard_share": round(ss, 4),
        "restrict_share": round(rs, 4), "heritage_share": None,
        "ugz_share": round(ugz / n, 4), "parks_share": round(parks / n, 4),
        "flood_share": None, "bushfire_share": None, "noise_share": None,
        "zone_mix": [[c, round(s, 4)] for c, s in mix],
        "res_points": res_points, "ugz_points": ugz_points, "ldrz_points": ldrz_points,
    }


def get_zoning(features_by_code: dict[str, dict]) -> dict[str, dict]:
    from ... import geo
    centroids = geo.sa2_points()
    cache = config.DATA_RAW / "qld_zoning_by_sa2.json"
    z: dict[str, dict] = {}
    if fresh(cache, 90):
        z = json.loads(cache.read_text(encoding="utf-8"))
    todo = [c for c in features_by_code if c not in z]
    if todo:
        print(f"  zoning: sampling BCC City Plan + QLD land use for {len(todo)} SA2s "
              f"({len(z)} cached) ...")

        def work(code):
            try:
                return code, _shares_for(features_by_code[code],
                                         centroids.get(code, config.CITY_ORIGIN)), None
            except Exception as e:  # noqa: BLE001 - one bad SA2 shouldn't kill the build
                return code, None, e

        fails = 0
        with ThreadPoolExecutor(max_workers=6) as ex:
            for i, (code, shares, err) in enumerate(ex.map(work, todo), 1):
                if err is not None:
                    fails += 1
                    if fails <= 5:
                        print(f"    zoning failed for {code}: {err!r}")
                elif shares is not None:
                    z[code] = shares
                if i % 40 == 0:
                    print(f"    {i}/{len(todo)} sampled")
                    cache.write_text(json.dumps(z), encoding="utf-8")
        if fails > 5:
            print(f"    ... and {fails - 5} more zoning failures (same pattern)")
        cache.write_text(json.dumps(z), encoding="utf-8")
    ok = sum(1 for c in features_by_code if c in z)
    print(f"  zoning: shares for {ok}/{len(features_by_code)} SA2s")
    return {c: z[c] for c in features_by_code if c in z}
