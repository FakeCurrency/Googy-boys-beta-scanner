"""QLD train-station access from the TransLink SEQ GTFS feed.

stops.txt carries parent stations (location_type=1, e.g. "Albion station"),
but busway stations share the same shape — the rail set is derived by
streaming stop_times.txt (156 MB) once: rail routes (route_type 2) -> trips ->
stop_ids -> parent stations. QLD publishes no station-level patronage, so
pax ships as None (the frontend labels pax "trips/yr" and the scorer
renormalises missing inputs). Everything maps to the app's "metro" kind.
"""
from __future__ import annotations

import csv
import io
import json
import math
import re
import zipfile

from ... import config
from ...fetch import fetch, fresh

GTFS_URL = "https://gtfsrt.api.translink.com.au/GTFS/SEQ_GTFS.zip"
NEAR_KM = 3.0


def _to_km(lon, lat):
    lon0, lat0 = config.CITY_ORIGIN
    return ((lon - lon0) * 111.320 * math.cos(math.radians(lat0)),
            (lat - lat0) * 110.574)


def _load_stations() -> list[dict]:
    cache = config.DATA_RAW / "qld_rail_stations.json"
    if fresh(cache, 60):
        print("  cached  qld_rail_stations.json")
        return json.loads(cache.read_text(encoding="utf-8"))

    path = fetch(GTFS_URL, "qld_seq_gtfs.zip", max_age_days=60)
    with zipfile.ZipFile(path) as z:
        routes = csv.DictReader(io.TextIOWrapper(z.open("routes.txt"), "utf-8-sig"))
        rail_routes = {r["route_id"] for r in routes if r.get("route_type") == "2"}
        trips = csv.DictReader(io.TextIOWrapper(z.open("trips.txt"), "utf-8-sig"))
        rail_trips = {t["trip_id"] for t in trips if t["route_id"] in rail_routes}

        rail_stop_ids = set()
        st = csv.reader(io.TextIOWrapper(z.open("stop_times.txt"), "utf-8-sig"))
        header = next(st)
        i_trip = header.index("trip_id")
        i_stop = header.index("stop_id")
        for r in st:                       # one streaming pass over ~156 MB
            if r[i_trip] in rail_trips:
                rail_stop_ids.add(r[i_stop])

        stops = list(csv.DictReader(io.TextIOWrapper(z.open("stops.txt"), "utf-8-sig")))

    rail_parents = {s.get("parent_station") or s["stop_id"]
                    for s in stops if s["stop_id"] in rail_stop_ids}
    x0, y0, x1, y1 = config.CITY_BBOX
    stations, seen = [], set()
    for s in stops:
        if s["stop_id"] not in rail_parents:
            continue
        try:
            lat, lon = float(s["stop_lat"]), float(s["stop_lon"])
        except (TypeError, ValueError):
            continue
        if not (x0 <= lon <= x1 and y0 <= lat <= y1):
            continue
        name = re.sub(r"\s+station$", "", re.sub(r"\s+", " ", s["stop_name"]).strip(), flags=re.I)
        key = name.upper()
        if not name or key in seen:
            continue
        seen.add(key)
        stations.append({"name": name, "lon": lon, "lat": lat, "kind": "metro", "pax": None})
    config.DATA_RAW.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(stations), encoding="utf-8")
    print(f"  transport: {len(stations)} SEQ rail stations from GTFS "
          f"({len(rail_stop_ids)} rail platform stops)")
    return stations


def get_stations(points: dict[str, tuple[float, float]],
                 res_points: dict[str, list] | None = None) -> dict[str, dict]:
    stations_raw = _load_stations()

    config.CITY_DATA.mkdir(parents=True, exist_ok=True)
    overlay = [{"type": "Feature",
                "geometry": {"type": "Point",
                             "coordinates": [round(s["lon"], 5), round(s["lat"], 5)]},
                "properties": {"name": s["name"], "kind": s["kind"], "pax": s["pax"]}}
               for s in stations_raw]
    (config.CITY_DATA / "stations.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": overlay}, separators=(",", ":")),
        encoding="utf-8")

    stations = [(*_to_km(s["lon"], s["lat"]), s) for s in stations_raw]
    near2 = NEAR_KM ** 2

    def _subsample(pts: list, cap: int) -> list:
        if len(pts) <= cap:
            return pts
        step = len(pts) / cap
        return [pts[int(i * step)] for i in range(cap)]

    def _nearest(sample, cx, cy, subset):
        if not subset:
            return None, None
        best2, best = float("inf"), None
        for sx, sy, s in subset:
            d2 = (cx - sx) ** 2 + (cy - sy) ** 2
            if d2 < best2:
                best2, best = d2, s
        dists = sorted(min((px - sx) ** 2 + (py - sy) ** 2 for sx, sy, _ in subset)
                       for px, py in sample)
        return round(dists[len(dists) // 2] ** 0.5, 2), best

    out = {}
    res_used = 0
    for code, (lon, lat) in points.items():
        rp = _subsample((res_points or {}).get(code) or [], 48)
        if rp:
            res_used += 1
        sample = [_to_km(px, py) for px, py in rp] or [_to_km(lon, lat)]
        cx = sum(x for x, _ in sample) / len(sample)
        cy = sum(y for _, y in sample) / len(sample)
        count = sum(1 for sx, sy, _ in stations if (cx - sx) ** 2 + (cy - sy) ** 2 <= near2)
        any_km, any_st = _nearest(sample, cx, cy, stations)
        out[code] = {
            "nearest_station_km": any_km,
            "nearest_station": any_st["name"] if any_st else None,
            "stations_3km": count,
            "station_pax": None,
            "metro_km": any_km, "metro_station": any_st["name"] if any_st else None,
            "metro_pax": None,
            "vline_km": None, "vline_station": None, "vline_pax": None,
        }
    print(f"  transport: {len(stations)} QLD rail stations -> access for "
          f"{len(out)} SA2s ({res_used} measured from residential land)")
    return out
