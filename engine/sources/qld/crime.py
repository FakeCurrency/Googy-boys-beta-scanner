"""QLD crime inputs from QPS open data (City Probe recon, runs #1-3).

The finest open geography is the police *division* (division names are suburb
names — "Acacia Ridge"), published as a wide CSV on the QPS S3 bucket:

    "Division","Month Year",<~90 offence columns>     (MonthYear like JAN01)

The offence columns mix parent categories ("Assault") with their subcategories
("Grievous Assault", ...), so summing everything double-counts. We prefer the
explicit "Offences Against the Person" / "Offences Against Property" /
"Other Offences" rollup columns when present, else fall back to a curated
parent-category list. Division counts flow to SA2s through the same locality
matching + population weighting as the Vic/NSW adapters.

LGA level: v1 ships without an LGA rate fallback; LGA *names* still come from
the national ABS boundary spatial join.
"""
from __future__ import annotations

import csv
import re
from collections import defaultdict

from ... import config, geo
from ...fetch import fetch, fresh
from ..crime import _load_vic_lgas, _sa2_localities  # city-agnostic helpers
import json

DIVISION_CSV = ("https://open-crime-data.s3-ap-southeast-2.amazonaws.com/"
                "Crime%20Statistics/division_Reported_Offences_Number.csv")
LGA_RATES_CSV = ("https://open-crime-data.s3-ap-southeast-2.amazonaws.com/"
                 "Crime%20Statistics/LGA_Reported_Offences_Rates.csv")

ROLLUP_PERSON = "offences against the person"
ROLLUP_PROPERTY = "offences against property"

# fallback parent categories (skip subcategories like "Grievous Assault")
PARENT_PERSON = {"homicide (murder)", "other homicide", "assault", "sexual offences",
                 "robbery", "kidnapping & abduction", "extortion",
                 "stalking", "life endangering acts"}
PARENT_PROPERTY = {"unlawful entry", "arson", "other property damage",
                   "unlawful use of motor vehicle", "other theft (excl. unlawful entry)",
                   "fraud", "handling stolen goods"}

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"])}


def _month_key(s: str) -> tuple[int, int] | None:
    """'JAN01' -> (2001, 1); QPS months run from JAN01."""
    s = str(s).strip().upper()
    if len(s) == 5 and s[:3] in _MONTHS and s[3:].isdigit():
        y = int(s[3:])
        return (2000 + y if y < 90 else 1900 + y, _MONTHS[s[:3]])
    return None


def _counts_by_division() -> dict[str, dict]:
    """{DIVISION: {person, property, total, person_prev}} over the latest 12
    months (person_prev = same window four years earlier, for the trend)."""
    cache = config.DATA_RAW / "qld_crime_by_division.json"
    if fresh(cache, 60):
        print("  cached  qld_crime_by_division.json")
        return json.loads(cache.read_text(encoding="utf-8"))

    path = fetch(DIVISION_CSV, "qld_crime_division.csv", max_age_days=60)
    with open(path, encoding="utf-8-sig", newline="") as fh:
        rows = csv.reader(fh)
        header = next(rows)
        lower = [str(h).strip().lower() for h in header]
        i_div = next(i for i, h in enumerate(lower) if "division" in h)
        i_month = next(i for i, h in enumerate(lower) if "month" in h)

        rollup_p = next((i for i, h in enumerate(lower) if h == ROLLUP_PERSON), None)
        rollup_q = next((i for i, h in enumerate(lower) if h == ROLLUP_PROPERTY), None)
        if rollup_p is not None and rollup_q is not None:
            person_cols, property_cols = [rollup_p], [rollup_q]
            mode = "rollup columns"
        else:
            person_cols = [i for i, h in enumerate(lower) if h in PARENT_PERSON]
            property_cols = [i for i, h in enumerate(lower) if h in PARENT_PROPERTY]
            mode = f"parent categories ({len(person_cols)}p/{len(property_cols)}q)"
        print(f"  crime: QPS division split via {mode}")

        # first pass is impossible without knowing the latest month — the file
        # is small enough to keep the per-division-month sums in memory instead
        per = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))   # div -> (y,m) -> [person, property]
        months_seen = set()
        for r in rows:
            if len(r) <= max(i_div, i_month):
                continue
            mk = _month_key(r[i_month])
            div = str(r[i_div]).strip().upper()
            if not mk or not div:
                continue
            months_seen.add(mk)

            def _s(cols):
                t = 0.0
                for i in cols:
                    if i < len(r):
                        v = str(r[i]).strip().replace(",", "")
                        if v and v.replace(".", "").isdigit():
                            t += float(v)
                return t

            cell = per[div][mk]
            cell[0] += _s(person_cols)
            cell[1] += _s(property_cols)

    months = sorted(months_seen)
    if len(months) < 60:
        raise RuntimeError(f"QPS division csv: only {len(months)} months recognised")
    latest12 = set(months[-12:])
    prev12 = set(months[-60:-48])
    counts = {}
    for div, by_month in per.items():
        person = sum(v[0] for m, v in by_month.items() if m in latest12)
        prop = sum(v[1] for m, v in by_month.items() if m in latest12)
        prev = sum(v[0] for m, v in by_month.items() if m in prev12)
        counts[div] = {"person": person, "property": prop,
                       "total": person + prop, "person_prev": prev}
    cache.write_text(json.dumps(counts), encoding="utf-8")
    print(f"  crime: QPS division counts for {len(counts)} divisions "
          f"(12 months to {months[-1][0]}-{months[-1][1]:02d})")
    return counts


def _norm_lga(n: str) -> str:
    """'Brisbane City Council' / ABS 'Brisbane' -> 'BRISBANE'."""
    n = re.sub(r"\s*\((?:[^)]*)\)\s*$", "", str(n).strip())
    n = re.sub(r"\s+(?:Aboriginal\s+Shire|City|Shire|Regional|Rural City|Town|Borough)?"
               r"\s*Council$", "", n, flags=re.I)
    return re.sub(r"\s+", " ", n).strip().upper()


def _rates_by_lga() -> dict[str, dict]:
    """{LGA: {person, property, total}} annual rates per 100k — the latest 12
    monthly rates summed, from the QPS LGA rates file (division matching only
    reaches ~1/4 of SA2s, so this is the coverage backbone like Vic's)."""
    cache = config.DATA_RAW / "qld_crime_lga_rates.json"
    if fresh(cache, 60):
        print("  cached  qld_crime_lga_rates.json")
        return json.loads(cache.read_text(encoding="utf-8"))

    path = fetch(LGA_RATES_CSV, "qld_crime_lga_rates.csv", max_age_days=60)
    with open(path, encoding="utf-8-sig", newline="") as fh:
        rows = csv.reader(fh)
        header = next(rows)
        lower = [str(h).strip().lower() for h in header]
        i_lga = next(i for i, h in enumerate(lower) if "lga" in h)
        i_month = next(i for i, h in enumerate(lower) if "month" in h)
        rollup_p = next((i for i, h in enumerate(lower) if h == ROLLUP_PERSON), None)
        rollup_q = next((i for i, h in enumerate(lower) if h == ROLLUP_PROPERTY), None)
        person_cols = [rollup_p] if rollup_p is not None else \
            [i for i, h in enumerate(lower) if h in PARENT_PERSON]
        property_cols = [rollup_q] if rollup_q is not None else \
            [i for i, h in enumerate(lower) if h in PARENT_PROPERTY]

        per = defaultdict(dict)      # lga -> (y,m) -> [person_rate, property_rate]
        months_seen = set()
        for r in rows:
            if len(r) <= max(i_lga, i_month):
                continue
            mk = _month_key(r[i_month])
            lga = _norm_lga(r[i_lga])
            if not mk or not lga:
                continue
            months_seen.add(mk)

            def _s(cols):
                t = 0.0
                for i in cols:
                    if i < len(r):
                        v = str(r[i]).strip().replace(",", "")
                        try:
                            t += float(v) if v else 0.0
                        except ValueError:
                            pass
                return t

            cell = per[lga].setdefault(mk, [0.0, 0.0])
            cell[0] += _s(person_cols)
            cell[1] += _s(property_cols)

    latest12 = set(sorted(months_seen)[-12:])
    out = {}
    for lga, by_month in per.items():
        p = sum(v[0] for m, v in by_month.items() if m in latest12)
        q = sum(v[1] for m, v in by_month.items() if m in latest12)
        out[lga] = {"person": round(p, 1), "property": round(q, 1), "total": round(p + q, 1)}
    cache.write_text(json.dumps(out), encoding="utf-8")
    print(f"  crime: QPS LGA rates for {len(out)} LGAs (latest 12 months)")
    return out


def get_crime() -> dict[str, dict]:
    """{sa2_code: {lga, person, property, total}} — LGA names via the national
    ABS boundary join, per-100k rates from the QPS LGA rates file (the app's
    fallback for SA2s the division matching misses)."""
    lgas = _load_vic_lgas()          # filters by config.STATE_NAME — city-agnostic
    rates = _rates_by_lga()
    points = geo.sa2_points()
    out = {}
    matched = 0
    for code, (x, y) in points.items():
        chosen = None
        for lga in lgas:
            x0, y0, x1, y1 = lga["bbox"]
            if x0 <= x <= x1 and y0 <= y <= y1 and any(geo.point_in_ring(x, y, r) for r in lga["rings"]):
                chosen = lga
                break
        if chosen is None and lgas:
            chosen = min(lgas, key=lambda L: (
                (x - (L["bbox"][0] + L["bbox"][2]) / 2) ** 2
                + (y - (L["bbox"][1] + L["bbox"][3]) / 2) ** 2))
        name = chosen["name"] if chosen else None
        r = rates.get(_norm_lga(name)) if name else None
        if r:
            matched += 1
        out[code] = {"lga": name,
                     "person": r["person"] if r else None,
                     "property": r["property"] if r else None,
                     "total": r["total"] if r else None}
    print(f"  crime: LGA names for {len(out)} SA2s, LGA rates matched for {matched}")
    return out


def get_crime_suburb(name_by_code: dict[str, str],
                     pop_by_code: dict[str, float],
                     lga_by_code: dict[str, str]) -> dict[str, dict]:
    """Division counts split across the SA2s referencing the matching locality
    (population-weighted), then per-100k rates — same shape as Vic/NSW."""
    counts = _counts_by_division()

    loc2sa2: dict[str, list[str]] = defaultdict(list)
    for code, name in name_by_code.items():
        if not pop_by_code.get(code):
            continue
        for loc in _sa2_localities(name):
            loc2sa2[loc].append(code)

    alloc: dict[str, dict] = defaultdict(
        lambda: {"person": 0.0, "property": 0.0, "total": 0.0, "person_prev": 0.0})
    for loc, c in counts.items():
        sa2s = loc2sa2.get(loc)
        if not sa2s:
            continue
        pop_sum = sum(pop_by_code[s] for s in sa2s)
        if pop_sum <= 0:
            continue
        for s in sa2s:
            w = pop_by_code[s] / pop_sum
            a = alloc[s]
            for k in ("person", "property", "total", "person_prev"):
                a[k] += c.get(k, 0.0) * w

    out = {}
    for code in name_by_code:
        pop = pop_by_code.get(code)
        a = alloc.get(code)
        if not pop or not a or a["total"] <= 0:
            out[code] = {}
            continue
        rec = {k: round(v / pop * 1e5, 1) for k, v in a.items() if k != "person_prev"}
        if a["person_prev"] >= 20 and a["person"] >= 20:
            rec["person_trend_pct"] = round((a["person"] - a["person_prev"])
                                            / a["person_prev"] * 100, 1)
        out[code] = rec
    matched = sum(1 for v in out.values() if v)
    print(f"  crime: division-level rates for {matched}/{len(out)} SA2s")
    return out


def get_postcode_map(name_by_code: dict[str, str],
                     lga_by_code: dict[str, str]) -> dict[str, list[str]]:
    """{postcode: [sa2_codes]} for search — (suburb, postcode) pairs from the
    Qld schools directory (most residential suburbs have a school)."""
    from .schools import suburb_postcode_pairs
    loc2sa2: dict[str, list[str]] = defaultdict(list)
    for code, name in name_by_code.items():
        for loc in _sa2_localities(name):
            loc2sa2[loc].append(code)
    out: dict[str, list[str]] = {}
    for loc, pc in suburb_postcode_pairs():
        for c in loc2sa2.get(loc, []):
            out.setdefault(pc, [])
            if c not in out[pc]:
                out[pc].append(c)
    print(f"  postcodes: {len(out)} QLD postcodes resolve to SA2s (schools-derived)")
    return out
