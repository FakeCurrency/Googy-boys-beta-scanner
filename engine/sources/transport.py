"""Train-station access inputs per SA2 (Phase 4).

Source: DTP (opendata.transport.vic.gov.au) annual station patronage CSVs —
metropolitan + regional — which carry every station's coordinates plus annual
entries (FY2024-25). Complete station list (222 metro + 94 V/Line), unlike the
generalised Vicmap Lite layer which drops many inner stations.

For each SA2's representative point: nearest-station distance + name, stations
within ~3 km, and the nearest station's annual patronage (narrative only).
Feeds Liveability (transport access) and Development (Victoria's activity-
centre housing program is explicitly station-centred).

Also exports public/data/stations.geojson for a map overlay.
"""
from __future__ import annotations

import csv
import json
import math

from .. import config
from ..fetch import fetch

METRO_URL = ("https://opendata.transport.vic.gov.au/dataset/2fa2cdfa-84f1-455e-b6c9-058b92774b34/"
             "resource/c9507eb5-aa48-4a43-aa09-c10a24d1f2fe/download/"
             "annual-metropolitan-train-station-patronage-station-entries-2024-2025.csv")
REGIONAL_URL = ("https://opendata.transport.vic.gov.au/dataset/2d4f81dc-f56a-4bcf-8291-ee04fe9669e6/"
                "resource/a5d6eb97-0555-4c8d-9dc7-316c6062cc57/download/"
                "annual-regional-train-station-patronage-station-entries-2024-2025.csv")
# Greater Melbourne envelope with margin so edge SA2s see stations just outside.
ENVELOPE = (144.2, -38.7, 145.9, -37.1)
NEAR_KM = 3.0

# Local equirectangular projection (same origin as electricity.py) -> km.
_LON0, _LAT0 = 145.0, -37.8
_KX = 111.320 * math.cos(math.radians(_LAT0))
_KY = 110.574


def _to_km(lon, lat):
    return (lon - _LON0) * _KX, (lat - _LAT0) * _KY


def _read_stations(path, kind):
    rows = []
    with open(path, encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            try:
                lat, lon = float(r["Stop_lat"]), float(r["Stop_long"])
            except (KeyError, TypeError, ValueError):
                continue
            pax = r.get("Pax_annual")
            rows.append({"name": r.get("Stop_name", "").strip(), "lon": lon, "lat": lat,
                         "kind": kind, "pax": int(pax) if pax and pax.isdigit() else None})
    return rows


def _subsample(pts: list, cap: int) -> list:
    if len(pts) <= cap:
        return pts
    step = len(pts) / cap
    return [pts[int(i * step)] for i in range(cap)]


def get_stations(points: dict[str, tuple[float, float]],
                 res_points: dict[str, list] | None = None) -> dict[str, dict]:
    """{sa2_code: {nearest_station_km, nearest_station, stations_3km, station_pax}}

    Distances are the *median* over residentially-zoned sample points (from the
    VicPlan sampler) so large fringe SA2s are measured from where people live,
    not the geometric centroid. Falls back to the representative point.
    """
    raw = (_read_stations(fetch(METRO_URL, "stations_metro.csv"), "metro")
           + _read_stations(fetch(REGIONAL_URL, "stations_regional.csv"), "vline"))
    x0, y0, x1, y1 = ENVELOPE
    stations, overlay = [], []
    for s in raw:
        if not (x0 <= s["lon"] <= x1 and y0 <= s["lat"] <= y1):
            continue
        stations.append((*_to_km(s["lon"], s["lat"]), s))
        overlay.append({"type": "Feature",
                        "geometry": {"type": "Point",
                                     "coordinates": [round(s["lon"], 5), round(s["lat"], 5)]},
                        "properties": {"name": s["name"], "kind": s["kind"], "pax": s["pax"]}})

    config.PUBLIC_DATA.mkdir(parents=True, exist_ok=True)
    (config.PUBLIC_DATA / "stations.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": overlay}, separators=(",", ":")),
        encoding="utf-8")

    near2 = NEAR_KM ** 2
    out = {}
    res_used = 0
    for code, (lon, lat) in points.items():
        rp = _subsample((res_points or {}).get(code) or [], 48)
        if rp:
            res_used += 1
        sample = [_to_km(px, py) for px, py in rp] or [_to_km(lon, lat)]
        # residential centroid anchors "nearest station" name + the 3 km count
        cx = sum(x for x, _ in sample) / len(sample)
        cy = sum(y for _, y in sample) / len(sample)
        best2, best, count = float("inf"), None, 0
        for sx, sy, s in stations:
            d2 = (cx - sx) ** 2 + (cy - sy) ** 2
            if d2 < best2:
                best2, best = d2, s
            if d2 <= near2:
                count += 1
        dists = sorted(min((px - sx) ** 2 + (py - sy) ** 2 for sx, sy, _ in stations)
                       for px, py in sample)
        median2 = dists[len(dists) // 2]
        out[code] = {
            "nearest_station_km": round(median2 ** 0.5, 2) if best else None,
            "nearest_station": best["name"] if best else None,
            "stations_3km": count,
            "station_pax": best["pax"] if best else None,
        }
    print(f"  transport: {len(stations)} stations -> access for {len(out)} SA2s "
          f"({res_used} measured from residential land)")
    return out


if __name__ == "__main__":  # pragma: no cover
    from .. import geo
    pts = geo.melbourne_sa2_points()
    names = {f["properties"]["sa2_code"]: f["properties"]["sa2_name"]
             for f in json.loads((config.PUBLIC_DATA / "melbourne.geojson").read_text(encoding="utf-8"))["features"]}
    st = get_stations(pts)
    for nm in ("Toorak", "Tarneit - North", "Nunawading", "Cobblebank - Strathtulloh", "Warrandyte - Wonga Park"):
        code = next((c for c, n in names.items() if n == nm), None)
        if code:
            print(f"  {nm:28} {st[code]}")
