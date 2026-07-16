"""QLD school-access inputs from the schools-directory dataset on data.qld.

The portal's /download/ URLs serve HTML wrappers to non-browser clients, so
rows come from the CKAN datastore API instead (resource confirmed
datastore-active in City Probe run #3; 39 fields incl Centre Type/Status,
Official Low/High Year Level and the actual address). Coordinates: the field
list was truncated in recon, so latitude/longitude fields are detected by
name at runtime — if absent, the loader prints every field name and returns
no schools (the build's coverage summary flags it for the next iteration).

Covers state AND non-state schools (unlike the NSW adapter).
"""
from __future__ import annotations

import math
import re

import requests

from ... import config
from ...fetch import fresh
import json

API = "https://www.data.qld.gov.au/api/3/action/datastore_search"
RESOURCE = "5b39065c-df32-415c-994c-5ff12f8de997"   # centredetails_may_2020.csv
NEAR_KM = 3.0
_UA = {"User-Agent": "Mozilla/5.0 (compatible; melbourne-property-recon)"}


def _to_km(lon, lat):
    lon0, lat0 = config.CITY_ORIGIN
    return ((lon - lon0) * 111.320 * math.cos(math.radians(lat0)),
            (lat - lat0) * 110.574)


def _rows() -> list[dict]:
    cache = config.DATA_RAW / "qld_schools_directory.json"
    if fresh(cache, 120):
        print("  cached  qld_schools_directory.json")
        return json.loads(cache.read_text(encoding="utf-8"))
    rows, offset = [], 0
    while True:
        r = requests.get(API, params={"resource_id": RESOURCE, "limit": "5000",
                                      "offset": str(offset)}, headers=_UA, timeout=90)
        r.raise_for_status()
        page = (r.json().get("result") or {}).get("records") or []
        rows.extend(page)
        if len(page) < 5000:
            break
        offset += len(page)
    config.DATA_RAW.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(rows), encoding="utf-8")
    print(f"  schools: {len(rows)} rows from the Qld schools directory (datastore API)")
    return rows


def _field(row: dict, *needles: str) -> str | None:
    for k in row:
        lk = k.lower()
        if all(n in lk for n in needles):
            return k
    return None


def _year_num(s: str) -> int | None:
    s = str(s).strip().lower()
    if not s:
        return None
    if "prep" in s or "kinder" in s:
        return 0
    m = re.search(r"year\s*(\d+)", s)
    return int(m.group(1)) if m else None


def suburb_postcode_pairs() -> list[tuple[str, str]]:
    """(SUBURB, postcode) pairs for the search postcode map, from the actual
    address (suburb = last populated address line, state/postcode stripped)."""
    pairs = set()
    for r in _rows():
        pc_key = _field(r, "actual", "post code") or _field(r, "post code")
        pc = str(r.get(pc_key, "") or "").strip().split(".")[0] if pc_key else ""
        sub = ""
        for n in (3, 2, 1):
            k = _field(r, "actual", f"line {n}")
            v = str(r.get(k, "") or "").strip() if k else ""
            if v:
                sub = v
                break
        sub = re.sub(r"\b(QLD|Q)\b\.?", "", sub, flags=re.I)
        sub = re.sub(r"\b\d{4}\b", "", sub).strip(" ,").upper()
        if sub and len(pc) == 4 and pc.isdigit():
            pairs.add((sub, pc))
    return sorted(pairs)


def _load_schools():
    rows = _rows()
    if not rows:
        return []
    lat_key = _field(rows[0], "latitude") or _field(rows[0], "lat")
    lon_key = _field(rows[0], "longitude") or _field(rows[0], "long")
    if not lat_key or not lon_key:
        print("  schools: NO coordinate fields in the directory — fields are:")
        for k in rows[0]:
            print(f"    - {k}")
        return []
    x0, y0, x1, y1 = config.CITY_BBOX
    schools = []
    for r in rows:
        status = str(r.get(_field(r, "status") or "", "") or "").lower()
        ctype = str(r.get(_field(r, "centre type") or "", "") or "").lower()
        if status and "open" not in status:
            continue
        if ctype and "school" not in ctype:
            continue
        try:
            lat, lon = float(r[lat_key]), float(r[lon_key])
        except (KeyError, TypeError, ValueError):
            continue
        if not (x0 <= lon <= x1 and y0 <= lat <= y1):
            continue
        low = _year_num(r.get(_field(r, "low year") or "", ""))
        high = _year_num(r.get(_field(r, "high year") or "", ""))
        primary = low is not None and low <= 3
        secondary = high is not None and high >= 10
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
    """{sa2_code: {nearest_primary_km, nearest_secondary_km, schools_3km}} —
    same residential-weighted median distances as the Vic/NSW adapters."""
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
        cand = []
        for reach in (12.0, 30.0, 1e9):
            cand = [s for s in schools if abs(s[0] - cx) <= reach and abs(s[1] - cy) <= reach]
            if any(s[2] for s in cand) and any(s[3] for s in cand):
                break
        count = sum(1 for x, y, _p, _s in cand if (cx - x) ** 2 + (cy - y) ** 2 <= near2)
        p_meds, s_meds = [], []
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
    print(f"  schools: {len(schools)} QLD schools (state + non-state) -> access for "
          f"{len(out)} SA2s ({res_used} measured from residential land)")
    return out
