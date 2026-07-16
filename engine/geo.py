"""Build the Greater Melbourne SA2 boundary GeoJSON.

Downloads the ABS ASGS Edition 3 SA2 (2021) shapefile, keeps only the SA2s
inside Greater Melbourne, simplifies the polygons with a pure-Python
Douglas-Peucker (no geopandas/shapely needed) and writes a compact GeoJSON for
the web map.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import shapefile  # pyshp

from . import config
from .fetch import fetch


# --- polygon simplification (pure Python) ----------------------------------
def _dp(pts: list[tuple[float, float]], tol: float) -> list[tuple[float, float]]:
    """Iterative Douglas-Peucker on an open polyline. ``tol`` in coord units."""
    n = len(pts)
    if n < 3:
        return pts[:]
    keep = [False] * n
    keep[0] = keep[-1] = True
    tol2 = tol * tol
    stack = [(0, n - 1)]
    while stack:
        s, e = stack.pop()
        ax, ay = pts[s]
        bx, by = pts[e]
        dx, dy = bx - ax, by - ay
        seg2 = dx * dx + dy * dy
        dmax, idx = 0.0, -1
        for i in range(s + 1, e):
            px, py = pts[i]
            if seg2 == 0.0:
                d = (px - ax) ** 2 + (py - ay) ** 2
            else:
                t = ((px - ax) * dx + (py - ay) * dy) / seg2
                projx, projy = ax + t * dx, ay + t * dy
                d = (px - projx) ** 2 + (py - projy) ** 2
            if d > dmax:
                dmax, idx = d, i
        if dmax > tol2 and idx != -1:
            keep[idx] = True
            stack.append((s, idx))
            stack.append((idx, e))
    return [pts[i] for i in range(n) if keep[i]]


def _simplify_ring(ring: list[tuple[float, float]], tol: float) -> list[tuple[float, float]] | None:
    """Simplify a closed ring; return None if it collapses below a triangle."""
    if len(ring) <= 4:
        return ring
    pts = ring[:-1] if ring[0] == ring[-1] else ring[:]
    n = len(pts)
    a = pts[0]
    # split the ring at the vertex furthest from the start so DP behaves well
    k = max(range(1, n), key=lambda i: (pts[i][0] - a[0]) ** 2 + (pts[i][1] - a[1]) ** 2)
    out = _dp(pts[: k + 1], tol)[:-1] + _dp(pts[k:] + [pts[0]], tol)
    if out[0] != out[-1]:
        out.append(out[0])
    return out if len(out) >= 4 else None


def _round_ring(ring, p):
    return [(round(x, p), round(y, p)) for x, y in ring]


def _simplify_geometry(geom: dict, tol: float, prec: int) -> dict | None:
    """Simplify a GeoJSON Polygon/MultiPolygon geometry. Drop empty parts."""
    gtype = geom["type"]
    if gtype == "Polygon":
        polys = [geom["coordinates"]]
    elif gtype == "MultiPolygon":
        polys = geom["coordinates"]
    else:
        return None

    new_polys = []
    for poly in polys:
        new_rings = []
        for ring_i, ring in enumerate(poly):
            simp = _simplify_ring([tuple(c) for c in ring], tol)
            if simp is None:
                if ring_i == 0:  # exterior collapsed -> keep coarse original
                    simp = [tuple(c) for c in ring]
                else:
                    continue     # drop a vanished hole
            new_rings.append(_round_ring(simp, prec))
        if new_rings:
            new_polys.append(new_rings)

    if not new_polys:
        return None
    if len(new_polys) == 1:
        return {"type": "Polygon", "coordinates": new_polys[0]}
    return {"type": "MultiPolygon", "coordinates": new_polys}


# --- shapefile field helpers ----------------------------------------------
def _field_index(field_names: list[str], *candidates: str) -> int | None:
    low = [f.lower() for f in field_names]
    for cand in candidates:
        for i, name in enumerate(low):
            if name.startswith(cand.lower()):
                return i
    return None


def _ring_centroid(ring: list[tuple[float, float]]) -> tuple[float, float, float]:
    """Area-weighted centroid of a ring; returns (cx, cy, signed_area)."""
    a = cx = cy = 0.0
    for i in range(len(ring) - 1):
        x0, y0 = ring[i]
        x1, y1 = ring[i + 1]
        cross = x0 * y1 - x1 * y0
        a += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    if a == 0:
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        return sum(xs) / len(xs), sum(ys) / len(ys), 0.0
    a *= 0.5
    return cx / (6 * a), cy / (6 * a), a


def representative_point(geom: dict) -> tuple[float, float]:
    """Interior point of a Polygon/MultiPolygon: centroid of its largest ring."""
    polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
    best = None
    best_area = -1.0
    for poly in polys:
        ext = [tuple(c) for c in poly[0]]
        cx, cy, area = _ring_centroid(ext)
        if abs(area) > best_area:
            best_area, best = abs(area), (cx, cy)
    return best


def point_in_ring(x: float, y: float, ring: list[tuple[float, float]]) -> bool:
    """Ray-casting point-in-polygon test against a single ring."""
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def sa2_points() -> dict[str, tuple[float, float]]:
    """{sa2_code: (lon, lat)} representative point for each Greater Melbourne SA2."""
    extract_dir = config.DATA_RAW / "sa2_shp"
    if not extract_dir.exists():
        build_geojson()  # ensures the shapefile is downloaded + extracted
    shp = next(extract_dir.glob("*.shp"))
    reader = shapefile.Reader(str(shp))
    field_names = [f[0] for f in reader.fields[1:]]
    i_code = _field_index(field_names, "SA2_CODE", "SA2_MAIN")
    i_gcc = _field_index(field_names, "GCC_NAME")
    pts = {}
    for sr in reader.iterShapeRecords():
        if str(sr.record[i_gcc]).strip() != config.GCC_NAME or not sr.shape.points:
            continue
        pts[str(sr.record[i_code])] = representative_point(sr.shape.__geo_interface__)
    return pts


def build_geojson(force: bool = False) -> Path:
    """Download, filter to Greater Melbourne, simplify and write the GeoJSON."""
    zip_path = fetch(config.SA2_SHP_URL, force=force)

    extract_dir = config.DATA_RAW / "sa2_shp"
    if force or not extract_dir.exists():
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(extract_dir)
    shp = next(extract_dir.glob("*.shp"))

    reader = shapefile.Reader(str(shp))
    field_names = [f[0] for f in reader.fields[1:]]  # skip DeletionFlag
    i_code = _field_index(field_names, "SA2_CODE", "SA2_MAIN", "SA2_5DIG")
    i_name = _field_index(field_names, "SA2_NAME")
    i_sa3 = _field_index(field_names, "SA3_NAME")
    i_sa4 = _field_index(field_names, "SA4_NAME")
    i_gcc = _field_index(field_names, "GCC_NAME")
    if None in (i_code, i_name, i_gcc):
        raise RuntimeError(f"Unexpected shapefile fields: {field_names}")

    features = []
    for sr in reader.iterShapeRecords():
        rec = sr.record
        if str(rec[i_gcc]).strip() != config.GCC_NAME:
            continue
        if not sr.shape.points:  # special/non-spatial SA2 (offshore, no address)
            continue
        geom = _simplify_geometry(
            sr.shape.__geo_interface__, config.SIMPLIFY_TOL, config.COORD_PRECISION
        )
        if geom is None:
            continue
        features.append({
            "type": "Feature",
            "properties": {
                "sa2_code": str(rec[i_code]),
                "sa2_name": str(rec[i_name]),
                "sa3_name": str(rec[i_sa3]) if i_sa3 is not None else "",
                "sa4_name": str(rec[i_sa4]) if i_sa4 is not None else "",
            },
            "geometry": geom,
        })

    fc = {"type": "FeatureCollection", "features": features}
    config.CITY_DATA.mkdir(parents=True, exist_ok=True)
    out = config.CITY_DATA / config.BOUNDARIES_NAME
    out.write_text(json.dumps(fc, separators=(",", ":")), encoding="utf-8")
    size_mb = out.stat().st_size / 1e6
    print(f"  wrote {out.name}: {len(features)} SA2s, {size_mb:.2f} MB")
    return out


if __name__ == "__main__":  # pragma: no cover
    build_geojson()
