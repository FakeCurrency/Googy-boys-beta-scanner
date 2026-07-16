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
NEAR_KM = 3.0


def _to_km(lon, lat):
    # local equirectangular projection around the active city's origin -> km
    lon0, lat0 = config.CITY_ORIGIN
    return ((lon - lon0) * 111.320 * math.cos(math.radians(lat0)),
            (lat - lat0) * 110.574)


def _load_schools():
    path = fetch(SCHOOLS_URL, "school_locations.csv")
    x0, y0, x1, y1 = config.CITY_BBOX
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


def _subsample(pts: list, cap: int) -> list:
    if len(pts) <= cap:
        return pts
    step = len(pts) / cap
    return [pts[int(i * step)] for i in range(cap)]


def get_schools(points: dict[str, tuple[float, float]],
                res_points: dict[str, list] | None = None) -> dict[str, dict]:
    """{sa2_code: {nearest_primary_km, nearest_secondary_km, schools_3km}}

    Distances are the median over residentially-zoned sample points (VicPlan
    sampler) with the representative point as fallback — see transport.py.
    """
    schools = _load_schools()
    near2 = NEAR_KM ** 2
    out = {}
    res_used = 0
    for code, (lon, lat) in points.items():
        rp = _subsample((res_points or {}).get(code) or [], 36)
        if rp:
            res_used += 1
        sample = [_to_km(px, py) for px, py in rp] or [_to_km(lon, lat)]
        cx = sum(x for x, _ in sample) / len(sample)
        cy = sum(y for _, y in sample) / len(sample)
        # prefilter to a widening box around the residential centroid for speed
        cand = []
        for reach in (12.0, 30.0, 1e9):
            cand = [s for s in schools if abs(s[0] - cx) <= reach and abs(s[1] - cy) <= reach]
            if any(s[2] for s in cand) and any(s[3] for s in cand):
                break
        p_meds, s_meds = [], []
        count = 0
        for x, y, primary, secondary in cand:
            if (cx - x) ** 2 + (cy - y) ** 2 <= near2:
                count += 1
        for px, py in sample:
            bp = bs = float("inf")
            for x, y, primary, secondary in cand:
                d2 = (px - x) ** 2 + (py - y) ** 2
                if primary and d2 < bp:
                    bp = d2
                if secondary and d2 < bs:
                    bs = d2
            p_meds.append(bp)
            s_meds.append(bs)
        p_meds.sort(); s_meds.sort()
        bp2, bs2 = p_meds[len(p_meds) // 2], s_meds[len(s_meds) // 2]
        out[code] = {
            "nearest_primary_km": round(bp2 ** 0.5, 2) if bp2 < float("inf") else None,
            "nearest_secondary_km": round(bs2 ** 0.5, 2) if bs2 < float("inf") else None,
            "schools_3km": count,
        }
    print(f"  schools: {len(schools)} schools -> access for {len(out)} SA2s "
          f"({res_used} measured from residential land)")
    return out


if __name__ == "__main__":  # pragma: no cover
    import json
    from .. import geo
    pts = geo.sa2_points()
    names = {f["properties"]["sa2_code"]: f["properties"]["sa2_name"]
             for f in json.loads((config.CITY_DATA / config.BOUNDARIES_NAME).read_text(encoding="utf-8"))["features"]}
    sc = get_schools(pts)
    for nm in ("Toorak", "Tarneit - North", "Bentleigh East (Vic.) - North", "Cobblebank - Strathtulloh"):
        code = next((c for c, n in names.items() if n == nm), None)
        if code:
            print(f"  {nm:30} {sc[code]}")
    # fallback: print any Bentleigh
    for c, n in names.items():
        if "Bentleigh East" in n:
            print(f"  {n:30} {sc[c]}")
