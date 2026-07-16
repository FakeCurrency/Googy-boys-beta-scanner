"""NSW planning-zone inputs from the EPI Land Zoning ArcGIS layer.

Same approach as the Vic adapter (whose geometry helpers we reuse): pull the
zone polygons intersecting each SA2's bbox from
Planning/EPI_Primary_Planning_Layers (layer 2 Land Zoning, layer 0 Heritage),
lay the sample grid over the SA2 polygon and classify each point by SYM_CODE.

NSW zone grouping (post-2021 employment-zone codes; legacy B* kept for maps
not yet converted). R2 Low Density plays the Vic NRZ role. There is no UGZ
analogue (ugz_share=0) and flood/bushfire/noise overlays ship as None in v1 —
the scorer renormalises missing inputs.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

from ... import config
from ...fetch import fresh
from ..zoning import _bbox, _grid_points, _in_polys, _query, _rings_of

EPI = ("https://mapprod3.environment.nsw.gov.au/arcgis/rest/services/"
       "Planning/EPI_Primary_Planning_Layers/MapServer")
ZONES_URL = f"{EPI}/2/query"
HERITAGE_URL = f"{EPI}/0/query"

ZONES_GROWTH = {"R3", "R4", "MU1", "MU", "B3", "B4", "B8", "E1", "E2"}
ZONES_STANDARD = {"R1", "B1", "B2", "E3", "RU5"}
ZONES_RESTRICT = {"R2", "R5", "C1", "C2", "C3", "C4", "E4",
                  "RU1", "RU2", "RU3", "RU4", "RU6", "W1", "W2", "W3"}
ZONES_RES = {"R1", "R2", "R3", "R4", "R5", "MU1", "B4", "RU5"}   # people live here
ZONES_LOWDEN = {"R5"}                                            # LDRZ analogue
ZONES_PARKS = {"RE1", "RE2", "C1"}


def _shares_for(sa2_geom: dict) -> dict | None:
    polys = _rings_of(sa2_geom)
    bbox = _bbox(polys)
    pts = _grid_points(polys, bbox)
    if not pts:
        return None
    # _query asks for f=geojson, so attributes arrive under "properties"
    zones = []
    for f in _query(ZONES_URL, bbox, "SYM_CODE"):
        if not f.get("geometry"):
            continue
        rings = _rings_of(f["geometry"])
        if not rings:
            continue
        code = ((f.get("properties") or f.get("attributes") or {}).get("SYM_CODE") or "")
        zones.append((code, rings, _bbox(rings)))
    heritage = []
    for f in _query(HERITAGE_URL, bbox, "OBJECTID"):
        if not f.get("geometry"):
            continue
        rings = _rings_of(f["geometry"])
        if rings:
            heritage.append((rings, _bbox(rings)))

    n = len(pts)
    tally: dict[str, int] = {}
    growth = standard = restrict = parks = her = lowden = 0
    res_points: list[list[float]] = []
    ldrz_points: list[list[float]] = []
    for x, y in pts:
        code = None
        for zc, zpolys, zb in zones:
            if zb[0] <= x <= zb[2] and zb[1] <= y <= zb[3] and _in_polys(x, y, zpolys):
                code = zc.strip().upper()
                break
        if code:
            tally[code] = tally.get(code, 0) + 1
            if code in ZONES_GROWTH:
                growth += 1
            elif code in ZONES_STANDARD:
                standard += 1
            elif code in ZONES_RESTRICT:
                restrict += 1
            if code in ZONES_PARKS:
                parks += 1
            if code in ZONES_RES:
                res_points.append([round(x, 4), round(y, 4)])
            if code in ZONES_LOWDEN:
                lowden += 1
                ldrz_points.append([round(x, 4), round(y, 4)])
        if any(hb[0] <= x <= hb[2] and hb[1] <= y <= hb[3] and _in_polys(x, y, hp)
               for hp, hb in heritage):
            her += 1

    gs, ss, rs = growth / n, standard / n, restrict / n
    mix = sorted(((c, k / n) for c, k in tally.items()), key=lambda t: -t[1])[:5]
    return {
        "zoning_raw": round(gs + 0.45 * ss - 0.35 * rs, 4),
        "growth_share": round(gs, 4), "standard_share": round(ss, 4),
        "restrict_share": round(rs, 4), "heritage_share": round(her / n, 4),
        "ugz_share": 0.0, "parks_share": round(parks / n, 4),
        "flood_share": None, "bushfire_share": None, "noise_share": None,
        "zone_mix": [[c, round(s, 4)] for c, s in mix],
        "res_points": res_points, "ugz_points": [], "ldrz_points": ldrz_points,
    }


def get_zoning(features_by_code: dict[str, dict]) -> dict[str, dict]:
    cache = config.DATA_RAW / "nsw_zoning_by_sa2.json"
    z: dict[str, dict] = {}
    if fresh(cache, 90):
        z = json.loads(cache.read_text(encoding="utf-8"))
    todo = [c for c in features_by_code if c not in z]
    if todo:
        print(f"  zoning: querying NSW ePlanning for {len(todo)} SA2s "
              f"({len(z)} cached) ...")

        def work(code):
            try:
                return code, _shares_for(features_by_code[code]), None
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
