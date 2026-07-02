"""Planning-zone + Heritage Overlay inputs per SA2 (Phase 4 — the real
"development potential" layer).

Source: VicPlan / Vicmap Planning ArcGIS services (plan-gis.mapshare.vic.gov.au):
  * Planning Scheme Zones (layer 0, "All Zones")   — ZONE_CODE polygons
  * Heritage Overlay      (overlays service, layer 9)

For each SA2 we fetch the zone/overlay polygons intersecting its bounding box
(geometry simplified server-side), lay a regular sample grid over the SA2
polygon, and classify each grid point. Shares of sampled land:
  growth   — zoned for intensification (RGZ, MUZ, ACZ, CCZ, C1Z, HCTZ, ...)
  standard — general residential (GRZ, TZ, UGZ precincts, ...)
  restrict — protective zoning (NRZ, LDRZ, Green Wedge, farming, parkland...)
  heritage — covered by a Heritage Overlay (a real redevelopment constraint)

zoning_raw = growth + 0.45*standard - 0.35*restrict  (percentile-normalised in
score.py; heritage is its own inverted input). Results are cached per SA2 in
data_raw/vicplan_shares.json so the ~720 service queries only run once.
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor

import requests

from .. import config

ZONES_URL = ("https://plan-gis.mapshare.vic.gov.au/arcgis/rest/services/Planning/"
             "Vicplan_PlanningSchemeZones/MapServer/0/query")
HO_URL = ("https://plan-gis.mapshare.vic.gov.au/arcgis/rest/services/Planning/"
          "Vicplan_PlanningSchemeOverlays/MapServer/9/query")
_HEADERS = {"User-Agent": "Mozilla/5.0 (melb-scorer data build)"}
TARGET_POINTS = 280
WORKERS = 6


def _base_code(zone_code: str) -> str:
    """GRZ10 -> GRZ (strip the schedule number)."""
    return re.sub(r"\d+$", "", str(zone_code or "").strip().upper())


# --- geometry helpers (pure Python, GeoJSON coords) --------------------------
def _rings_of(geom: dict) -> list[list[list[tuple[float, float]]]]:
    """[[ext_ring, hole, ...], ...] for Polygon/MultiPolygon."""
    if not geom:
        return []
    if geom["type"] == "Polygon":
        polys = [geom["coordinates"]]
    elif geom["type"] == "MultiPolygon":
        polys = geom["coordinates"]
    else:
        return []
    return [[[tuple(c[:2]) for c in ring] for ring in poly] for poly in polys]


def _in_ring(x, y, ring) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def _in_polys(x, y, polys) -> bool:
    for poly in polys:
        if _in_ring(x, y, poly[0]) and not any(_in_ring(x, y, h) for h in poly[1:]):
            return True
    return False


def _bbox(polys):
    xs = [x for poly in polys for x, _ in poly[0]]
    ys = [y for poly in polys for _, y in poly[0]]
    return min(xs), min(ys), max(xs), max(ys)


def _grid_points(polys, bbox, target=TARGET_POINTS):
    x0, y0, x1, y1 = bbox
    w, h = max(x1 - x0, 1e-6), max(y1 - y0, 1e-6)
    spacing = max(0.0006, min(0.02, (w * h / target) ** 0.5))
    for _ in range(3):   # densify for thin/small SA2s until we have enough points
        pts = []
        ny, nx = int(h / spacing) + 1, int(w / spacing) + 1
        for iy in range(ny):
            y = y0 + (iy + 0.5) * spacing
            for ix in range(nx):
                x = x0 + (ix + 0.5) * spacing
                if _in_polys(x, y, polys):
                    pts.append((x, y))
        if len(pts) >= 24 or spacing <= 0.0004:
            return pts
        spacing = max(0.0004, spacing / 2)
    return pts


def _query(url, bbox, out_fields):
    """All features intersecting bbox (paged past the 1000-record limit)."""
    feats, offset = [], 0
    env = {"xmin": bbox[0], "ymin": bbox[1], "xmax": bbox[2], "ymax": bbox[3],
           "spatialReference": {"wkid": 4326}}
    while True:
        r = requests.post(url, data={
            "geometry": json.dumps(env), "geometryType": "esriGeometryEnvelope", "inSR": 4326,
            "spatialRel": "esriSpatialRelIntersects", "where": "1=1",
            "outFields": out_fields, "returnGeometry": "true", "outSR": 4326,
            "maxAllowableOffset": 0.0003, "geometryPrecision": 5,
            "resultOffset": offset, "f": "geojson",
        }, headers=_HEADERS, timeout=120)
        r.raise_for_status()
        page = r.json().get("features", [])
        feats.extend(page)
        if len(page) < 1000:
            return feats
        offset += len(page)


def _shares_for(sa2_geom: dict) -> dict | None:
    polys = _rings_of(sa2_geom)
    if not polys:
        return None
    bbox = _bbox(polys)
    pts = _grid_points(polys, bbox)
    if not pts:
        return None

    zones = [( _rings_of(f["geometry"]), _bbox(_rings_of(f["geometry"])),
               _base_code(f["properties"].get("ZONE_CODE")))
             for f in _query(ZONES_URL, bbox, "ZONE_CODE") if f.get("geometry")]
    ho = [(_rings_of(f["geometry"]), _bbox(_rings_of(f["geometry"])))
          for f in _query(HO_URL, bbox, "ZONE_CODE") if f.get("geometry")]

    mix: dict[str, int] = {}
    classified = heritage = 0
    for x, y in pts:
        code = None
        for zp, zb, zc in zones:
            if zb[0] <= x <= zb[2] and zb[1] <= y <= zb[3] and _in_polys(x, y, zp):
                code = zc
                break
        if code:
            classified += 1
            mix[code] = mix.get(code, 0) + 1
        for hp, hb in ho:
            if hb[0] <= x <= hb[2] and hb[1] <= y <= hb[3] and _in_polys(x, y, hp):
                heritage += 1
                break
    if classified < 8:
        return None

    share = lambda codes: round(sum(n for c, n in mix.items() if c in codes) / classified, 4)  # noqa: E731
    growth = share(config.ZONES_GROWTH)
    standard = share(config.ZONES_STANDARD)
    restrict = share(config.ZONES_RESTRICT)
    top = sorted(mix.items(), key=lambda kv: -kv[1])[:4]
    return {
        "growth_share": growth, "standard_share": standard, "restrict_share": restrict,
        "heritage_share": round(heritage / len(pts), 4),
        "zoning_raw": round(growth + 0.45 * standard - 0.35 * restrict, 4),
        "zone_mix": [[c, round(n / classified, 3)] for c, n in top],
        "n_points": len(pts),
    }


def get_zoning(features_by_code: dict[str, dict]) -> dict[str, dict]:
    """{sa2_code: {growth_share, standard_share, restrict_share, heritage_share,
                   zoning_raw, zone_mix}} — cached, resumable."""
    cache_path = config.DATA_RAW / "vicplan_shares.json"
    cache: dict[str, dict] = {}
    if cache_path.exists() and cache_path.stat().st_size > 0:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))

    todo = [c for c in features_by_code if c not in cache]
    if todo:
        print(f"  zoning: querying VicPlan for {len(todo)} SA2s "
              f"({len(cache)} cached) — one-time, a few minutes ...")
        done = 0

        def work(code):
            try:
                return code, _shares_for(features_by_code[code])
            except Exception as e:   # keep the build alive; missing -> neutral score
                return code, {"error": str(e)[:120]}

        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            for code, rec in ex.map(work, todo):
                cache[code] = rec if rec is not None else {}
                done += 1
                if done % 25 == 0 or done == len(todo):
                    config.DATA_RAW.mkdir(parents=True, exist_ok=True)
                    cache_path.write_text(json.dumps(cache), encoding="utf-8")
                    print(f"    ... {done}/{len(todo)}")

    # retry any errored SA2s once, next run (drop them from the returned data)
    out = {}
    errs = 0
    for code, rec in cache.items():
        if rec and "error" not in rec:
            out[code] = rec
        elif rec and "error" in rec:
            errs += 1
    if errs:
        print(f"  zoning: {errs} SA2s errored (delete data_raw/vicplan_shares.json entries to retry)")
    print(f"  zoning: shares for {len(out)}/{len(features_by_code)} SA2s")
    return out


if __name__ == "__main__":  # pragma: no cover
    fc = json.loads((config.PUBLIC_DATA / "melbourne.geojson").read_text(encoding="utf-8"))
    feats = {f["properties"]["sa2_code"]: f["geometry"] for f in fc["features"]}
    names = {f["properties"]["sa2_code"]: f["properties"]["sa2_name"] for f in fc["features"]}
    z = get_zoning(feats)
    for nm in ("Toorak", "Tarneit - North", "Nunawading", "Brunswick", "Warrandyte - Wonga Park"):
        code = next((c for c, n in names.items() if n == nm), None)
        if code and code in z:
            print(f"  {nm:28} {z[code]}")
