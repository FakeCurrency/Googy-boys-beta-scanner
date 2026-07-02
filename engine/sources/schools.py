"""School-access inputs per SA2 (Phase 4).

Source: Victorian Department of Education "School Locations 2025" CSV
(data.vic, all sectors: Government + Catholic + Independent) with X/Y
coordinates. For each SA2's representative point we compute distance to the
nearest primary-serving and secondary-serving school and how many schools sit
within ~3 km (choice). SEIFA IEO remains the quality proxy; this measures
actual access.
"""
from __future__ import annotations

import csv
import math

from .. import config
from ..fetch import fetch

SCHOOLS_URL = ("https://www.education.vic.gov.au/Documents/about/research/datavic/"
               "dv402-SchoolLocations2025.csv")
ENVELOPE = (144.2, -38.7, 145.9, -37.1)
NEAR_KM = 3.0

_LON0, _LAT0 = 145.0, -37.8
_KX = 111.320 * math.cos(math.radians(_LAT0))
_KY = 110.574


def _to_km(lon, lat):
    return (lon - _LON0) * _KX, (lat - _LAT0) * _KY


def _load_schools():
    path = fetch(SCHOOLS_URL, "school_locations.csv")
    x0, y0, x1, y1 = ENVELOPE
    schools = []
    # The department ships this CP1252-encoded; fall back if that changes.
    for enc in ("cp1252", "utf-8-sig"):
        try:
            with open(path, encoding=enc, newline="") as fh:
                rows = list(csv.DictReader(fh))
            break
        except UnicodeDecodeError:
            continue
    for r in rows:
        if str(r.get("School_Status", "")).strip().lower() not in ("o", "open", ""):
            continue
        try:
            lon, lat = float(r["X"]), float(r["Y"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (x0 <= lon <= x1 and y0 <= lat <= y1):
            continue
        stype = str(r.get("School_Type", "")).strip().lower()   # Primary / Secondary / Pri/Sec / Special ...
        primary = "pri" in stype
        secondary = "sec" in stype
        if not (primary or secondary):
            continue
        x, y = _to_km(lon, lat)
        schools.append((x, y, primary, secondary))
    return schools


def get_schools(points: dict[str, tuple[float, float]]) -> dict[str, dict]:
    """{sa2_code: {nearest_primary_km, nearest_secondary_km, schools_3km}}"""
    schools = _load_schools()
    near2 = NEAR_KM ** 2
    out = {}
    for code, (lon, lat) in points.items():
        px, py = _to_km(lon, lat)
        best_p2 = best_s2 = float("inf")
        count = 0
        for x, y, primary, secondary in schools:
            d2 = (px - x) ** 2 + (py - y) ** 2
            if primary and d2 < best_p2:
                best_p2 = d2
            if secondary and d2 < best_s2:
                best_s2 = d2
            if d2 <= near2:
                count += 1
        out[code] = {
            "nearest_primary_km": round(best_p2 ** 0.5, 2) if best_p2 < float("inf") else None,
            "nearest_secondary_km": round(best_s2 ** 0.5, 2) if best_s2 < float("inf") else None,
            "schools_3km": count,
        }
    print(f"  schools: {len(schools)} schools (all sectors) -> access for {len(out)} SA2s")
    return out


if __name__ == "__main__":  # pragma: no cover
    import json
    from .. import geo
    pts = geo.melbourne_sa2_points()
    names = {f["properties"]["sa2_code"]: f["properties"]["sa2_name"]
             for f in json.loads((config.PUBLIC_DATA / "melbourne.geojson").read_text(encoding="utf-8"))["features"]}
    sc = get_schools(pts)
    for nm in ("Toorak", "Tarneit - North", "Bentleigh East (Vic.) - North", "Cobblebank - Strathtulloh"):
        code = next((c for c, n in names.items() if n == nm), None)
        if code:
            print(f"  {nm:30} {sc[code]}")
    # fallback: print any Bentleigh
    for c, n in names.items():
        if "Bentleigh East" in n:
            print(f"  {n:30} {sc[c]}")
