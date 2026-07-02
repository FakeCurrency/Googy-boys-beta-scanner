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


def _percentiles(values: dict[str, float | None], invert: bool = False) -> dict[str, float | None]:
    """Map each value to its 0-100 percentile among the non-missing values.

    Missing stays None — the weighted blends renormalise over present inputs
    instead of letting "no data" masquerade as a median suburb.
    """
    present = [v for v in values.values() if v is not None]
    ordered = sorted(present)
    n = len(ordered)
    out: dict[str, float | None] = {}
    for k, v in values.items():
        if v is None or n == 0:
            out[k] = None
            continue
        lo = bisect.bisect_left(ordered, v)
        hi = bisect.bisect_right(ordered, v)
        pct = (lo + hi) / 2 / n * 100
        out[k] = round(100 - pct if invert else pct, 1)
    return out


def _weighted(norm: dict[str, float | None], weights: dict[str, float]) -> tuple[float | None, int]:
    """Weighted blend over the inputs that exist; returns (score, inputs_used)."""
    used = {k: w for k, w in weights.items() if norm.get(k) is not None}
    if not used:
        return None, 0
    total = sum(used.values())
    return round(sum(norm[k] * w for k, w in used.items()) / total, 1), len(used)


def _safest_pct(score: float) -> int:
    """For an inverted (safety) score, the ascending rank: 100 -> bottom 0%."""
    return max(0, min(100, round(100 - score)))


def _explain_live(p: dict, family: float, transit: dict, r: dict) -> str:
    if r.get("precinct"):
        return ("An employment precinct (airport/industrial) with almost no residents — "
                "liveability signals are shown for completeness but aren't meaningful here; "
                "crime uses the surrounding LGA's rates.")
    s = p["person_safety"]["score"] or 50
    safety = (f"among the safest {_safest_pct(s)}% of Greater Melbourne for crimes against the person"
              if s >= 78 else
              "lower-than-average personal-crime rates" if s >= 55 else
              "mid-range personal-crime rates" if s >= 40 else
              "elevated personal-crime rates by Melbourne standards")
    # Per-resident caveat for CBD-style precincts with big visitor populations.
    if (r.get("crime_source") == "suburb" and (r.get("person_crime") or 0) > 2500):
        safety += (" (rates are per resident — precincts with large daytime/visitor "
                   "crowds overstate day-to-day risk)")
    dec = p["seifa"]["decile"] or 0
    seifa = ("a high socio-economic profile (SEIFA decile " + str(dec) + ")" if dec >= 8 else
             "a below-average socio-economic profile (SEIFA decile " + str(dec) + ")" if dec <= 3 else
             "a mid-range socio-economic profile (SEIFA decile " + str(dec) + ")")
    prop = (" Property crime runs higher here, typically retail/transport precincts rather than homes."
            if (p["property_safety"]["score"] or 50) < 35 else "")
    km, st = transit.get("nearest_station_km"), transit.get("nearest_station")
    train = (f" {st} station is ~{km} km away." if km is not None and km <= 2.5 and st else
             f" Note: the nearest train station ({st}) is ~{km} km away." if km is not None and km > 6 and st
             else "")
    fam = " It also reads as family-friendly." if (family or 0) >= 70 else ""
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
        fz, bz = round(z.get("flood_share", 0) * 100), round(z.get("bushfire_share", 0) * 100)
        risks = [f"{fz}% flood (LSIO/SBO/FO)" if fz >= 5 else "",
                 f"{bz}% bushfire (BMO)" if bz >= 5 else ""]
        risks = [x for x in risks if x]
        if risks:
            zline += f" Hazard overlays cover {' and '.join(risks)} — factor approvals and insurance."
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
    basis = m.get("yield_basis") or "house"
    yv = m.get("yield_headline")
    yld = ""
    if yv and m.get("rent_weekly"):
        yld = f" Rents ~${round(m['rent_weekly'])}/wk → gross {basis} yield ≈{yv}%."
        if basis == "house" and (m.get("median_house") or 0) > 2e6:
            yld += " (3-bed rent vs a whole-market median — premium-home yields read low.)"
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


def _tags(p: dict, family: float | None, seifa_dec: int, dev: float, market: dict,
          infra_score: float | None, transit: dict, z: dict | None,
          precinct: bool = False) -> list[str]:
    """Up to 5 salient, plain-English chips (ordered by salience)."""
    sc = lambda key: p[key]["score"] if p[key]["score"] is not None else 50  # noqa: E731
    t = []
    if precinct: t.append("Employment precinct")
    ps = sc("person_safety")
    if not precinct:
        if ps >= 85: t.append("Very safe")
        elif ps >= 65: t.append("Safe")
        if seifa_dec >= 9 and ps >= 78: t.append("Blue-chip")
        elif seifa_dec >= 8: t.append("Affluent")
        if (family or 0) >= 72: t.append("Family-friendly")
    if z and z["growth_share"] >= 0.20: t.append("Zoned for growth")
    if (transit.get("nearest_station_km") or 99) <= 1.2: t.append("Near train")
    if dev >= 70 and sc("child") >= 60: t.append("Growth corridor")
    if (infra_score or 0) >= 72: t.append("Grid-ready")
    if sc("detached") >= 72: t.append("Redevelopment headroom")
    if z and z["heritage_share"] >= 0.25: t.append("Heritage constrained")
    if z and z.get("flood_share", 0) >= 0.25: t.append("Flood overlay")
    if z and z.get("bushfire_share", 0) >= 0.25: t.append("Bushfire overlay")
    if (market.get("yield_headline") or 0) >= 4.2: t.append("Strong yield")
    if sc("rental") >= 72: t.append("High rental demand")
    if sc("owner_occ") >= 72 and sc("rental") <= 35: t.append("Tightly held")
    if sc("low_density") >= 72: t.append("Low density")
    elif p["low_density"]["score"] is not None and p["low_density"]["score"] <= 22: t.append("Built-up")
    if market.get("growth_signal") == "Strong": t.append("Strong growth")
    if market.get("value_signal") == "Affordable" and dev >= 55: t.append("Affordable upside")
    elif market.get("value_signal") == "Premium": t.append("Premium market")
    return t[:5]


def compute_scores(records: dict[str, dict]) -> dict[str, dict]:
    codes = list(records)
    g = lambda key: {c: records[c].get(key) for c in codes}  # noqa: E731

    # combined hazard coverage (flood + bushfire overlays) and headline yield
    # (unit yield where units dominate the stock, else 3BR-house yield)
    hazard = {}
    yield_head = {}
    for c in codes:
        r = records[c]
        fl, bf = r.get("flood_share"), r.get("bushfire_share")
        hazard[c] = (fl or 0) + (bf or 0) if (fl is not None or bf is not None) else None
        yield_head[c] = (r.get("yield_unit") if r.get("yield_basis") == "unit"
                         else r.get("yield_house")) or r.get("yield_house") or r.get("yield_unit")

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
        "hazard_free": _percentiles(hazard, invert=True),
        "ugz": _percentiles(g("ugz_share")),
        "upzone": _percentiles(g("growth_share")),           # upzoned share only (no UGZ)
        "unrestricted": _percentiles(g("restrict_share"), invert=True),
        "yield": _percentiles(yield_head),
    }

    # ---- pass 1: sub-scores + raw weighted composites -----------------------
    interim: dict[str, dict] = {}
    for c in codes:
        schools_score, _ = _weighted({
            "primary": n["school_prim"][c], "secondary": n["school_sec"][c],
            "density": n["school_dens"][c],
        }, config.SCHOOL_WEIGHTS)
        # station access: proximity leads, density adds inner-network depth
        transport_score, _ = _weighted(
            {"prox": n["station_prox"][c], "dens": n["station_dens"][c]},
            {"prox": 0.75, "dens": 0.25})
        family, _ = _weighted(
            {"child": n["child"][c], "ieo": n["ieo"][c],
             "person_safety": n["person_safety"][c], "schools": schools_score},
            config.FAMILY_WEIGHTS)
        # Shared pillar inputs; two Liveability values from two weight sets.
        live_norm = {
            "person_safety": n["person_safety"][c], "seifa": n["seifa"][c],
            "owner_occ": n["owner_occ"][c], "property_safety": n["property_safety"][c],
            "family_child": n["child"][c], "transport": transport_score,
            "schools": schools_score, "hazard_free": n["hazard_free"][c],
        }
        live_raw, live_used = _weighted(live_norm, config.LIVE_WEIGHTS)
        live_family_raw, _ = _weighted(live_norm, config.LIVE_WEIGHTS_FAMILY)
        infra_score, _ = _weighted({
            "transmission": n["trans_prox"][c], "substation": n["sub_prox"][c],
            "density": n["sub_dens"][c],
        }, config.INFRA_WEIGHTS)
        dev_raw, dev_used = _weighted({
            "detached_share": n["detached"][c], "zoning": n["zoning"][c],
            "growth": n["growth"][c], "infra": infra_score,
            "station": n["station_prox"][c], "yield": n["yield"][c],
            "rental_share": n["rental"][c], "low_density": n["low_density"][c],
            "heritage_free": n["heritage_free"][c], "hazard_free": n["hazard_free"][c],
        }, config.DEV_WEIGHTS)
        green_raw, _ = _weighted({
            "ugz": n["ugz"][c], "unrestricted": n["unrestricted"][c],
            "low_density": n["low_density"][c], "growth": n["growth"][c],
            "detached_share": n["detached"][c], "yield": n["yield"][c],
            "infra": infra_score,
        }, config.DEV_GREENFIELD_WEIGHTS)
        infill_raw, _ = _weighted({
            "upzone": n["upzone"][c], "station": n["station_prox"][c],
            "detached_share": n["detached"][c], "heritage_free": n["heritage_free"][c],
            "growth": n["growth"][c], "rental_share": n["rental"][c],
            "hazard_free": n["hazard_free"][c],
        }, config.DEV_INFILL_WEIGHTS)
        interim[c] = {
            "schools_score": schools_score, "transport_score": transport_score,
            "family": family, "infra_score": infra_score,
            "live_raw": live_raw, "live_family_raw": live_family_raw, "dev_raw": dev_raw,
            "green_raw": green_raw, "infill_raw": infill_raw,
            "live_used": live_used, "dev_used": dev_used,
        }

    # ---- composite stretch ---------------------------------------------------
    # Averaging many percentile inputs regresses toward 50 (the old build had an
    # interquartile dev range of just 44-56 and produced zero A grades). Re-rank
    # the composites so Live/Dev use the full 0-100 range; grades become
    # distribution tiers via the percentile of the default-blend Overall.
    live_s = _percentiles({c: interim[c]["live_raw"] for c in codes})
    livef_s = _percentiles({c: interim[c]["live_family_raw"] for c in codes})
    dev_s = _percentiles({c: interim[c]["dev_raw"] for c in codes})
    green_s = _percentiles({c: interim[c]["green_raw"] for c in codes})
    infill_s = _percentiles({c: interim[c]["infill_raw"] for c in codes})
    overall_val = {c: (round(config.DEFAULT_BLEND["live"] * live_s[c]
                             + config.DEFAULT_BLEND["dev"] * dev_s[c], 1)
                       if live_s[c] is not None and dev_s[c] is not None else None)
                   for c in codes}
    overall_pct = _percentiles(overall_val)

    # ---- pass 2: assemble output ---------------------------------------------
    out: dict[str, dict] = {}
    for c in codes:
        r = records[c]
        im = interim[c]
        schools_score, transport_score = im["schools_score"], im["transport_score"]
        family, infra_score = im["family"], im["infra_score"]
        live = live_s[c] if live_s[c] is not None else 50.0
        live_family = livef_s[c] if livef_s[c] is not None else 50.0
        dev = dev_s[c] if dev_s[c] is not None else 50.0
        overall = overall_val[c] if overall_val[c] is not None else 50.0

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
            "hazard_free": {"score": n["hazard_free"][c], "raw": hazard[c]},
            "yield": {"score": n["yield"][c], "raw": yield_head[c]},
        }
        seifa_dec = r.get("irsad_decile") or 0
        fam_label = ("Family-friendly" if (family or 0) >= 72 else
                     "OK for families" if (family or 0) >= 50 else "Less family-oriented")
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
            "yield_headline": yield_head[c], "yield_basis": r.get("yield_basis"),
            "yield_signal": _yield_signal(yield_head[c]),
        }
        infra = {
            "score": infra_score,
            "advantage": _infra_signal(infra_score) if infra_score is not None else "n/a",
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
                 "heritage_share": r.get("heritage_share") or 0,
                 "flood_share": r.get("flood_share") or 0, "bushfire_share": r.get("bushfire_share") or 0,
                 "zone_mix": r.get("zone_mix") or []}
                if r.get("zoning_raw") is not None else None)
        zoning = None
        if zraw is not None:
            zoning = {
                "score": n["zoning"][c],
                "growth_share": r.get("growth_share"), "standard_share": r.get("standard_share"),
                "restrict_share": r.get("restrict_share"), "heritage_share": r.get("heritage_share"),
                "flood_share": r.get("flood_share"), "bushfire_share": r.get("bushfire_share"),
                "zone_mix": r.get("zone_mix") or [],
                "label": _zoning_label(zraw),
            }
        coverage = {
            "price": bool(r.get("median_house")),
            "rent": r.get("rent_source"),                # "suburb" | "lga" | None
            "crime": r.get("crime_source") or "lga",     # "suburb" | "lga"
            "zoning": r.get("zoning_raw") is not None,
            "live_inputs": [im["live_used"], len(config.LIVE_WEIGHTS)],
            "dev_inputs": [im["dev_used"], len(config.DEV_WEIGHTS)],
        }
        precinct = bool(r.get("precinct"))
        out[c] = {
            "name": r.get("name"), "sa3": r.get("sa3"), "sa4": r.get("sa4"),
            "lga": r.get("lga"), "population": r.get("population"),
            "pop_year": r.get("pop_year"),
            "precinct": precinct,
            "live": live, "live_family": live_family, "dev": dev,
            "dev_green": green_s[c] if green_s[c] is not None else 50.0,
            "dev_infill": infill_s[c] if infill_s[c] is not None else 50.0,
            # grade = distribution tier of the default-blend Overall (A+ = top ~10%)
            "overall": overall, "grade": config.grade_for(overall_pct[c] if overall_pct[c] is not None else 50.0),
            "family": {"score": family, "label": fam_label},
            "market": market,
            "infra": infra,
            "transit": transit,
            "schools": school,
            "zoning": zoning,
            "coverage": coverage,
            "pillars": pillars,
            "explanation_live": _explain_live(pillars, family, transit, r),
            "explanation_dev": _explain_dev(pillars, zraw, transit),
            "explanation_invest": _explain_invest(market),
            "explanation_infra": _explain_infra(infra),
            "tags": _tags(pillars, family, seifa_dec, dev, market, infra_score, transit, zraw, precinct),
        }
    return out
