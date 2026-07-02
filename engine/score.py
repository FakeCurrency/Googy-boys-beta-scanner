"""Turn raw per-SA2 inputs into Liveability + Development scores.

Every input is converted to a 0-100 percentile *within Greater Melbourne*
(higher = always better; "bad" inputs like crime, density and heritage
coverage are inverted), then blended with the weights in config.py.

Phase 4 refinements:
  * Crime is suburb-level (CSA incidents by suburb/town) with LGA fallback.
  * Real planning controls: Vicmap zone shares + Heritage Overlay coverage.
  * Train-station access feeds Liveability AND Development (activity centres).
  * School access feeds Liveability + the Family badge.
  * Rental medians (DFFH) give gross yield into the Invest/Development lens.
  * Per-area coverage flags so the UI can say when a figure is LGA-level or missing.
"""
from __future__ import annotations

import bisect

from . import config


def _percentiles(values: dict[str, float | None], invert: bool = False) -> dict[str, float]:
    """Map each value to its 0-100 percentile among the non-missing values."""
    present = [v for v in values.values() if v is not None]
    if not present:
        return {k: 50.0 for k in values}
    ordered = sorted(present)
    n = len(ordered)
    out: dict[str, float] = {}
    for k, v in values.items():
        if v is None:
            out[k] = 50.0
            continue
        lo = bisect.bisect_left(ordered, v)
        hi = bisect.bisect_right(ordered, v)
        pct = (lo + hi) / 2 / n * 100
        out[k] = round(100 - pct if invert else pct, 1)
    return out


def _weighted(norm: dict[str, float], weights: dict[str, float]) -> float:
    total = sum(weights.values())
    return round(sum(norm[k] * w for k, w in weights.items()) / total, 1)


def _safest_pct(score: float) -> int:
    """For an inverted (safety) score, the ascending rank: 100 -> bottom 0%."""
    return max(0, min(100, round(100 - score)))


def _explain_live(p: dict, family: float, transit: dict) -> str:
    s = p["person_safety"]["score"]
    safety = (f"among the safest {_safest_pct(s)}% of Greater Melbourne for crimes against the person"
              if s >= 78 else
              "lower-than-average personal-crime rates" if s >= 55 else
              "mid-range personal-crime rates" if s >= 40 else
              "elevated personal-crime rates by Melbourne standards")
    dec = p["seifa"]["decile"] or 0
    seifa = ("a high socio-economic profile (SEIFA decile " + str(dec) + ")" if dec >= 8 else
             "a below-average socio-economic profile (SEIFA decile " + str(dec) + ")" if dec <= 3 else
             "a mid-range socio-economic profile (SEIFA decile " + str(dec) + ")")
    prop = (" Property crime runs higher here, typically retail/transport precincts rather than homes."
            if p["property_safety"]["score"] < 35 else "")
    km, st = transit.get("nearest_station_km"), transit.get("nearest_station")
    train = (f" {st} station is ~{km} km away." if km is not None and km <= 2.5 and st else
             f" Note: the nearest train station ({st}) is ~{km} km away." if km is not None and km > 6 and st
             else "")
    fam = " It also reads as family-friendly." if family >= 70 else ""
    safety = safety[0].upper() + safety[1:]
    return f"{safety}, with {seifa}.{prop}{train}{fam}"


def _explain_dev(p: dict, z: dict | None, transit: dict) -> str:
    det = p["detached"]["raw"] or 0
    head = (f"~{round(det * 100)}% of dwellings are detached houses — strong redevelopment headroom"
            if det >= 0.7 else
            f"only ~{round(det * 100)}% detached houses, so it's already fairly built-up" if det < 0.35 else
            f"~{round(det * 100)}% detached houses — moderate headroom")
    if z:
        gz, rz, hz = round(z["growth_share"] * 100), round(z["restrict_share"] * 100), round(z["heritage_share"] * 100)
        top = (z.get("zone_mix") or [["?", 0]])[0][0]
        if gz >= 20:
            zline = f" {gz}% of sampled land is zoned for intensification (RGZ/MUZ/ACZ/commercial)"
        elif rz >= 45:
            zline = f" {rz}% of land sits under protective zoning ({top}-led), which caps redevelopment"
        else:
            zline = f" Zoning is {top}-led"
        if hz >= 8:
            zline += f", and {hz}% is under a Heritage Overlay"
        zline += "."
    else:
        zline = " No zoning sample for this area."
    km, st = transit.get("nearest_station_km"), transit.get("nearest_station")
    train = (f" Walkable to {st} station — the state's activity-centre program favours exactly this."
             if km is not None and km <= 1.2 and st else "")
    return f"{head}.{zline}{train} Grid capacity remains a proxy (see Infrastructure)."


def _growth_signal(cagr: float | None) -> str:
    if cagr is None:
        return "n/a"
    return "Strong" if cagr >= 4 else "Moderate" if cagr >= 1.5 else "Soft"


def _value_signal(price_pctile: float | None, has_price: bool) -> str | None:
    if not has_price:
        return None
    return "Affordable" if price_pctile <= 33 else "Premium" if price_pctile >= 75 else "Mid-market"


def _yield_signal(y: float | None) -> str | None:
    if y is None:
        return None
    return "Strong yield" if y >= 4.2 else "Fair yield" if y >= 3.2 else "Thin yield"


def _money(v: float) -> str:
    return f"${v / 1e6:.2f}M" if v >= 1e6 else f"${round(v / 1e3)}k"


def _explain_invest(m: dict) -> str:
    if not m["median_house"]:
        return "No recent Valuer-General sale medians for this area (often non-residential SA2s)."
    g12, cagr = m["house_12m"], m["house_3yr_cagr"]
    g12s = f"{'+' if (g12 or 0) >= 0 else ''}{g12}% over 12 months" if g12 is not None else "flat 12 months"
    cagrs = f"{'+' if (cagr or 0) >= 0 else ''}{cagr}% p.a. over 3 years" if cagr is not None else ""
    growth = {"Strong": "strong recent capital growth", "Moderate": "steady growth",
              "Soft": "soft/flat recent growth", "n/a": "limited growth history"}[m["growth_signal"]]
    val = {"Affordable": " An affordable entry point.", "Mid-market": " Mid-market pricing.",
           "Premium": " A premium, blue-chip market."}.get(m["value_signal"], "")
    yld = (f" Rents ~${round(m['rent_weekly'])}/wk → gross house yield ≈{m['yield_house']}%."
           if m.get("yield_house") and m.get("rent_weekly") else "")
    return (f"Median house {_money(m['median_house'])} ({m['house_year']}): {g12s}, {cagrs} — {growth}.{val}{yld}")


def _infra_signal(score: float) -> str:
    return "Strong" if score >= 66 else "Moderate" if score >= 40 else "Limited"


def _explain_infra(inf: dict) -> str:
    t, s, c = inf["nearest_transmission_km"], inf["nearest_substation_km"], inf["substation_count_10km"]
    kv = inf["nearest_line_kv"]
    if t is None:
        return "No electricity-network data for this area."
    line = f"~{t} km from a transmission line" + (f" ({kv} kV)" if kv else "")
    subs = f"{c} substation{'s' if c != 1 else ''} within 10 km" + (f", nearest ~{s} km" if s is not None else "")
    if inf["score"] >= 66:
        return (f"Strong grid support: {line}; {subs}. Well placed for larger-scale "
                "development, subdivision or future EV/charging clusters.")
    if inf["score"] >= 40:
        return (f"Moderate grid support: {line}; {subs}. Smaller infill is more "
                "straightforward than major projects.")
    return (f"Limited existing network: {line}; {subs}. Connection costs are likely "
            "higher for larger projects until the area builds out.")


def _zoning_label(z: dict | None) -> str | None:
    if not z:
        return None
    mix = dict(z.get("zone_mix") or [])
    if mix.get("UGZ", 0) >= 0.4:
        return "Growth-area precinct"
    if z["growth_share"] >= 0.25:
        return "Strongly upzoned"
    if z["growth_share"] >= 0.10:
        return "Some upzoning"
    if z["restrict_share"] >= 0.50:
        return "Tightly protected"
    return "Standard residential"


def _tags(p: dict, family: float, seifa_dec: int, dev: float, market: dict,
          infra_score: float, transit: dict, z: dict | None) -> list[str]:
    """Up to 5 salient, plain-English chips (ordered by salience)."""
    t = []
    ps = p["person_safety"]["score"]
    if ps >= 85: t.append("Very safe")
    elif ps >= 65: t.append("Safe")
    if seifa_dec >= 9 and ps >= 78: t.append("Blue-chip")
    elif seifa_dec >= 8: t.append("Affluent")
    if family >= 72: t.append("Family-friendly")
    if z and z["growth_share"] >= 0.20: t.append("Zoned for growth")
    if (transit.get("nearest_station_km") or 99) <= 1.2: t.append("Near train")
    if dev >= 70 and p["child"]["score"] >= 60: t.append("Growth corridor")
    if infra_score >= 72: t.append("Grid-ready")
    if p["detached"]["score"] >= 72: t.append("Redevelopment headroom")
    if z and z["heritage_share"] >= 0.25: t.append("Heritage constrained")
    if (market.get("yield_house") or 0) >= 4.2: t.append("Strong yield")
    if p["rental"]["score"] >= 72: t.append("High rental demand")
    if p["owner_occ"]["score"] >= 72 and p["rental"]["score"] <= 35: t.append("Tightly held")
    if p["low_density"]["score"] >= 72: t.append("Low density")
    elif p["low_density"]["score"] <= 22: t.append("Built-up")
    if market.get("growth_signal") == "Strong": t.append("Strong growth")
    if market.get("value_signal") == "Affordable" and dev >= 55: t.append("Affordable upside")
    elif market.get("value_signal") == "Premium": t.append("Premium market")
    return t[:5]


def compute_scores(records: dict[str, dict]) -> dict[str, dict]:
    codes = list(records)
    g = lambda key: {c: records[c].get(key) for c in codes}  # noqa: E731

    n = {
        "person_safety": _percentiles(g("person_crime"), invert=True),
        "property_safety": _percentiles(g("property_crime"), invert=True),
        "seifa": _percentiles(g("irsad_score")),
        "ieo": _percentiles(g("ieo_score")),
        "child": _percentiles(g("child_share")),
        "owner_occ": _percentiles(g("owner_occ")),
        "low_social": _percentiles(g("social"), invert=True),
        "detached": _percentiles(g("detached")),
        "rental": _percentiles(g("rental")),
        "mortgage": _percentiles(g("mortgage")),
        "low_density": _percentiles(g("density"), invert=True),
        "growth": _percentiles(g("house_3yr_cagr")),
        "price": _percentiles(g("median_house")),
        "trans_prox": _percentiles(g("nearest_transmission_km"), invert=True),
        "sub_prox": _percentiles(g("nearest_substation_km"), invert=True),
        "sub_dens": _percentiles(g("substation_count_10km")),
        # Phase 4
        "station_prox": _percentiles(g("nearest_station_km"), invert=True),
        "station_dens": _percentiles(g("stations_3km")),
        "school_prim": _percentiles(g("nearest_primary_km"), invert=True),
        "school_sec": _percentiles(g("nearest_secondary_km"), invert=True),
        "school_dens": _percentiles(g("schools_3km")),
        "zoning": _percentiles(g("zoning_raw")),
        "heritage_free": _percentiles(g("heritage_share"), invert=True),
        "yield": _percentiles(g("yield_house")),
    }

    out: dict[str, dict] = {}
    for c in codes:
        r = records[c]
        schools_score = _weighted({
            "primary": n["school_prim"][c], "secondary": n["school_sec"][c],
            "density": n["school_dens"][c],
        }, config.SCHOOL_WEIGHTS)
        # station access: proximity leads, density adds inner-network depth
        transport_score = round(0.75 * n["station_prox"][c] + 0.25 * n["station_dens"][c], 1)
        family = _weighted(
            {"child": n["child"][c], "ieo": n["ieo"][c],
             "person_safety": n["person_safety"][c], "schools": schools_score},
            config.FAMILY_WEIGHTS)
        # Shared pillar inputs; two Liveability values from two weight sets.
        live_norm = {
            "person_safety": n["person_safety"][c], "seifa": n["seifa"][c],
            "owner_occ": n["owner_occ"][c], "property_safety": n["property_safety"][c],
            "family_child": n["child"][c], "transport": transport_score,
            "schools": schools_score,
        }
        live = _weighted(live_norm, config.LIVE_WEIGHTS)               # base (Balanced/Invest)
        live_family = _weighted(live_norm, config.LIVE_WEIGHTS_FAMILY)  # Live / Family-First
        infra_score = _weighted({
            "transmission": n["trans_prox"][c], "substation": n["sub_prox"][c],
            "density": n["sub_dens"][c],
        }, config.INFRA_WEIGHTS)
        dev = _weighted({
            "detached_share": n["detached"][c], "zoning": n["zoning"][c],
            "growth": n["growth"][c], "infra": infra_score,
            "station": n["station_prox"][c], "yield": n["yield"][c],
            "rental_share": n["rental"][c], "low_density": n["low_density"][c],
            "heritage_free": n["heritage_free"][c],
        }, config.DEV_WEIGHTS)
        overall = round(config.DEFAULT_BLEND["live"] * live + config.DEFAULT_BLEND["dev"] * dev, 1)

        pillars = {
            "person_safety": {"score": n["person_safety"][c], "raw": r.get("person_crime")},
            "property_safety": {"score": n["property_safety"][c], "raw": r.get("property_crime")},
            "seifa": {"score": n["seifa"][c], "raw": r.get("irsad_score"), "decile": r.get("irsad_decile")},
            "ieo": {"score": n["ieo"][c], "decile": r.get("ieo_decile")},
            "owner_occ": {"score": n["owner_occ"][c], "raw": r.get("owner_occ")},
            "low_social": {"score": n["low_social"][c], "raw": r.get("social")},
            "child": {"score": n["child"][c], "raw": r.get("child_share")},
            "detached": {"score": n["detached"][c], "raw": r.get("detached")},
            "rental": {"score": n["rental"][c], "raw": r.get("rental")},
            "mortgage": {"score": n["mortgage"][c], "raw": r.get("mortgage")},
            "low_density": {"score": n["low_density"][c], "raw": r.get("density")},
            "transport": {"score": transport_score, "raw": r.get("nearest_station_km")},
            "schools": {"score": schools_score, "raw": r.get("nearest_primary_km")},
            "zoning": {"score": n["zoning"][c], "raw": r.get("zoning_raw")},
            "heritage_free": {"score": n["heritage_free"][c], "raw": r.get("heritage_share")},
            "yield": {"score": n["yield"][c], "raw": r.get("yield_house")},
        }
        seifa_dec = r.get("irsad_decile") or 0
        fam_label = ("Family-friendly" if family >= 72 else
                     "OK for families" if family >= 50 else "Less family-oriented")
        market = {
            "median_house": r.get("median_house"), "median_unit": r.get("median_unit"),
            "house_12m": r.get("house_12m"), "house_3yr_cagr": r.get("house_3yr_cagr"),
            "house_year": r.get("house_year"), "unit_year": r.get("unit_year"),
            "house_series": r.get("house_series") or [],
            "growth_score": n["growth"][c],
            "growth_signal": _growth_signal(r.get("house_3yr_cagr")),
            "value_signal": _value_signal(n["price"][c], bool(r.get("median_house"))),
            "rent_weekly": r.get("rent_weekly"), "rent_12m": r.get("rent_12m"),
            "rent_quarter": r.get("rent_quarter"),
            "yield_house": r.get("yield_house"), "yield_unit": r.get("yield_unit"),
            "yield_signal": _yield_signal(r.get("yield_house")),
        }
        infra = {
            "score": infra_score,
            "advantage": _infra_signal(infra_score),
            "nearest_transmission_km": r.get("nearest_transmission_km"),
            "nearest_substation_km": r.get("nearest_substation_km"),
            "substation_count_10km": r.get("substation_count_10km"),
            "nearest_line_kv": r.get("nearest_line_kv"),
        }
        transit = {
            "score": transport_score,
            "nearest_station_km": r.get("nearest_station_km"),
            "nearest_station": r.get("nearest_station"),
            "stations_3km": r.get("stations_3km"),
            "station_pax": r.get("station_pax"),
        }
        school = {
            "score": schools_score,
            "nearest_primary_km": r.get("nearest_primary_km"),
            "nearest_secondary_km": r.get("nearest_secondary_km"),
            "schools_3km": r.get("schools_3km"),
        }
        zraw = ({"growth_share": r.get("growth_share") or 0, "restrict_share": r.get("restrict_share") or 0,
                 "heritage_share": r.get("heritage_share") or 0, "zone_mix": r.get("zone_mix") or []}
                if r.get("zoning_raw") is not None else None)
        zoning = None
        if zraw is not None:
            zoning = {
                "score": n["zoning"][c],
                "growth_share": r.get("growth_share"), "standard_share": r.get("standard_share"),
                "restrict_share": r.get("restrict_share"), "heritage_share": r.get("heritage_share"),
                "zone_mix": r.get("zone_mix") or [],
                "label": _zoning_label(zraw),
            }
        coverage = {
            "price": bool(r.get("median_house")),
            "rent": r.get("rent_source"),                # "suburb" | "lga" | None
            "crime": r.get("crime_source") or "lga",     # "suburb" | "lga"
            "zoning": r.get("zoning_raw") is not None,
        }
        out[c] = {
            "name": r.get("name"), "sa3": r.get("sa3"), "sa4": r.get("sa4"),
            "lga": r.get("lga"), "population": r.get("population"),
            "live": live, "live_family": live_family, "dev": dev,
            "overall": overall, "grade": config.grade_for(overall),
            "family": {"score": family, "label": fam_label},
            "market": market,
            "infra": infra,
            "transit": transit,
            "schools": school,
            "zoning": zoning,
            "coverage": coverage,
            "pillars": pillars,
            "explanation_live": _explain_live(pillars, family, transit),
            "explanation_dev": _explain_dev(pillars, zraw, transit),
            "explanation_invest": _explain_invest(market),
            "explanation_infra": _explain_infra(infra),
            "tags": _tags(pillars, family, seifa_dec, dev, market, infra_score, transit, zraw),
        }
    return out
