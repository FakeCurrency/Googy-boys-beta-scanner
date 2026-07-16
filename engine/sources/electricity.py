"""Electricity-infrastructure inputs per SA2 (Phase 3).

Source: Geoscience Australia "National Electricity Infrastructure" MapServer
(free, national, v4 2024) — Transmission Substations (points, with voltage) and
Transmission Lines (polylines, with capacity kV). We pull the Greater Melbourne
extent and, for each SA2's representative point, compute:
  * nearest_transmission_km  — distance to the nearest high-voltage line
  * nearest_substation_km    — distance to the nearest transmission substation
  * substation_count_10km    — substations within ~10 km (network density)
  * nearest_line_kv          — capacity of the closest line (narrative only)

These are strong, defensible proxies for "how easy/cheap is it to connect new
development". Actual spare *capacity / headroom* is commercially sensitive and
not public — documented as a limitation in code and UI.

We also export a compact public/data/electricity.geojson overlay (lines +
substations) so the map can show the network, fulfilling the original
"combine the AEMO map" vision.
"""
from __future__ import annotations

import json
import math

import requests

from .. import config
from ..geo import _dp  # reuse the pure-Python Douglas-Peucker

ELEC = "https://services.ga.gov.au/gis/rest/services/National_Electricity_Infrastructure/MapServer"
SUBSTATIONS_LAYER, LINES_LAYER = 0, 2
BUFFER_KM = 10.0


def _envelope() -> dict:
    """The active city's clip envelope (the GA dataset is national)."""
    x0, y0, x1, y1 = config.CITY_BBOX
    return {"xmin": x0, "ymin": y0, "xmax": x1, "ymax": y1,
            "spatialReference": {"wkid": 4326}}


def _to_km(lon, lat):
    # local equirectangular projection around the active city's origin -> km
    lon0, lat0 = config.CITY_ORIGIN
    return ((lon - lon0) * 111.320 * math.cos(math.radians(lat0)),
            (lat - lat0) * 110.574)


def _fetch_layer(lid: int, out_fields: str, fname: str) -> list[dict]:
    """Query a GA MapServer layer within the city envelope as GeoJSON (cached per city)."""
    path = config.DATA_RAW / f"{config.CITY['slug']}_{fname}"
    if path.exists() and path.stat().st_size > 0:
        print(f"  cached  {fname}")
        return json.loads(path.read_text(encoding="utf-8"))["features"]
    print(f"  querying GA electricity {fname} ...")
    params = {
        "geometry": json.dumps(_envelope()), "geometryType": "esriGeometryEnvelope",
        "inSR": 4326, "spatialRel": "esriSpatialRelIntersects", "where": "1=1",
        "outFields": out_fields, "returnGeometry": "true", "outSR": 4326,
        "resultRecordCount": 5000, "f": "geojson",
    }
    r = requests.get(f"{ELEC}/{lid}/query", params=params,
                     headers={"User-Agent": "Mozilla/5.0 (melb-scorer)"}, timeout=120)
    r.raise_for_status()
    fc = r.json()
    config.DATA_RAW.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fc), encoding="utf-8")
    print(f"  fetched {len(fc.get('features', []))} -> {fname}")
    return fc["features"]


def _operational(props: dict) -> bool:
    s = str(props.get("operationalstatus") or "").lower()
    return s == "" or "oper" in s


def _load_network():
    """Return (substations[(x,y,kv,lon,lat,name)], segments[(ax,ay,bx,by,kv)], overlay)."""
    subs_raw = _fetch_layer(SUBSTATIONS_LAYER, "NAME,VOLTAGEKV,OPERATIONALSTATUS", "ga_substations.geojson")
    lines_raw = _fetch_layer(LINES_LAYER, "NAME,CAPACITYKV,OPERATIONALSTATUS", "ga_lines.geojson")

    substations, sub_overlay = [], []
    for f in subs_raw:
        p = f.get("properties", {})
        g = f.get("geometry") or {}
        if g.get("type") != "Point" or not _operational(p):
            continue
        lon, lat = g["coordinates"][:2]
        kv = p.get("voltagekv")
        x, y = _to_km(lon, lat)
        substations.append((x, y, kv))
        sub_overlay.append({"type": "Feature", "geometry": {"type": "Point",
                            "coordinates": [round(lon, 4), round(lat, 4)]},
                            "properties": {"kv": kv, "name": p.get("name")}})

    segments, line_overlay = [], []
    for f in lines_raw:
        p = f.get("properties", {})
        g = f.get("geometry") or {}
        if not _operational(p) or g.get("type") not in ("LineString", "MultiLineString"):
            continue
        kv = p.get("capacitykv")
        parts = [g["coordinates"]] if g["type"] == "LineString" else g["coordinates"]
        for part in parts:
            simp = _dp([tuple(c[:2]) for c in part], 0.003)  # ~300 m simplify
            if len(simp) < 2:
                continue
            line_overlay.append({"type": "Feature", "properties": {"kv": kv},
                                 "geometry": {"type": "LineString",
                                 "coordinates": [[round(x, 4), round(y, 4)] for x, y in simp]}})
            kmpts = [_to_km(lon, lat) for lon, lat in simp]
            for (ax, ay), (bx, by) in zip(kmpts, kmpts[1:]):
                segments.append((ax, ay, bx, by, kv))

    overlay = {"type": "FeatureCollection", "features": line_overlay + sub_overlay}
    return substations, segments, overlay


def _seg_dist2(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    seg = dx * dx + dy * dy
    if seg == 0:
        return (px - ax) ** 2 + (py - ay) ** 2
    t = ((px - ax) * dx + (py - ay) * dy) / seg
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    cx, cy = ax + t * dx, ay + t * dy
    return (px - cx) ** 2 + (py - cy) ** 2


def get_infra(points: dict[str, tuple[float, float]]) -> dict[str, dict]:
    """{sa2_code: {nearest_transmission_km, nearest_substation_km, substation_count_10km, nearest_line_kv}}"""
    substations, segments, overlay = _load_network()
    # write the map overlay once
    config.CITY_DATA.mkdir(parents=True, exist_ok=True)
    (config.CITY_DATA / "electricity.geojson").write_text(
        json.dumps(overlay, separators=(",", ":")), encoding="utf-8")

    out = {}
    buf2 = BUFFER_KM ** 2
    for code, (lon, lat) in points.items():
        px, py = _to_km(lon, lat)
        # nearest line (+ its kV)
        best_line2, best_kv = float("inf"), None
        for ax, ay, bx, by, kv in segments:
            d2 = _seg_dist2(px, py, ax, ay, bx, by)
            if d2 < best_line2:
                best_line2, best_kv = d2, kv
        # nearest substation + density
        best_sub2, count = float("inf"), 0
        for x, y, _kv in substations:
            d2 = (px - x) ** 2 + (py - y) ** 2
            if d2 < best_sub2:
                best_sub2 = d2
            if d2 <= buf2:
                count += 1
        out[code] = {
            "nearest_transmission_km": round(best_line2 ** 0.5, 2) if best_line2 < float("inf") else None,
            "nearest_substation_km": round(best_sub2 ** 0.5, 2) if best_sub2 < float("inf") else None,
            "substation_count_10km": count,
            "nearest_line_kv": best_kv,
        }
    print(f"  electricity: {len(substations)} substations, {len(segments)} line segments "
          f"-> infra signals for {len(out)} SA2s")
    return out


if __name__ == "__main__":  # pragma: no cover
    from .. import geo
    pts = geo.sa2_points()
    names = {f["properties"]["sa2_code"]: f["properties"]["sa2_name"]
             for f in json.loads((config.CITY_DATA / config.BOUNDARIES_NAME).read_text(encoding="utf-8"))["features"]}
    infra = get_infra(pts)
    for nm in ("Nunawading", "Tarneit - North", "Toorak", "Cobblebank - Strathtulloh", "Somerton"):
        code = next((c for c, n in names.items() if n == nm), None)
        if code:
            print(f"  {nm:28} {infra[code]}")
