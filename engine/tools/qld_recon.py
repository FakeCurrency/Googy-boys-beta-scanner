"""One-shot recon of QLD data sources for the Brisbane adapters (docs/AUSTRALIA.md).

Run from CI, where the network is open (the sandboxed dev environment can't
reach government portals):

    python -m engine.tools.qld_recon

Candidate sources per the AUSTRALIA.md matrix:
  crime      QPS offence data on data.qld.gov.au (CKAN) / QPS ArcGIS crime map
  prices     Qld open data property sales (CKAN) — availability unconfirmed
  rents      RTA median rents by suburb/postcode (rta.qld.gov.au + CKAN)
  zoning     QSpatial statewide land-use zoning ArcGIS layer
  transport  TransLink SEQ GTFS (stops) + station patronage on CKAN
  schools    Qld state school locations CSV on CKAN

Same drill as nsw_recon: print package resources, CSV headers and ArcGIS
layer fields + one sample feature at Brisbane CBD. Every section is
independent so one dead source can't hide the rest.
"""
from __future__ import annotations

import io
import json
import re
import zipfile

import requests

UA = {"User-Agent": "Mozilla/5.0 (compatible; melbourne-property-recon)"}
BROWSER = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")}
DATA_QLD = "https://www.data.qld.gov.au/api/3/action"
CBD = "153.026,-27.470"   # Brisbane GPO


def _get(url, headers=UA, **kw):
    r = requests.get(url, headers=headers, timeout=60, **kw)
    r.raise_for_status()
    return r


def section(title):
    print(f"\n{'=' * 12} {title}")


def ckan_search(q, rows=5):
    js = _get(f"{DATA_QLD}/package_search", params={"q": q, "rows": rows}).json()
    res = js["result"]
    print(f"search '{q}': {res['count']} packages")
    return res["results"]


def show_package(pkg, max_res=8):
    print(f"\npackage: {pkg['title']}  (id={pkg['id']})")
    org = (pkg.get("organization") or {}).get("title", "")
    print(f"  org={org}  updated={pkg.get('metadata_modified', '')[:10]}")
    first_tab = None
    for r in pkg.get("resources", [])[:max_res]:
        fmt = (r.get("format") or "").upper()
        print(f"  - [{fmt:>5}] {r.get('name', '')[:70]}  size={r.get('size') or '?'}")
        print(f"           {r.get('url', '')}")
        if first_tab is None and fmt in ("CSV", "XLSX", "XLS"):
            first_tab = r
    n = len(pkg.get("resources", []))
    if n > max_res:
        print(f"  ... {n - max_res} more resources")
    return first_tab


def sample_csv(url, label):
    try:
        r = requests.get(url, headers=BROWSER, timeout=90)
        r.raise_for_status()
        ct = r.headers.get("content-type", "")
        chunk = r.content[:16384].decode("utf-8", "replace")
        print(f"  sample {label} (content-type={ct}, {len(r.content)/1e6:.1f} MB):")
        for ln in chunk.splitlines()[:3]:
            print(f"    | {ln[:280]}")
    except Exception as e:  # noqa: BLE001 - recon keeps going
        print(f"  sample {label}: FAILED ({e!r})")


def arcgis_folder(base, folder):
    js = _get(f"{base}/{folder}?f=json").json()
    names = [s["name"] for s in js.get("services", [])]
    print(f"{folder}: {len(names)} services")
    for n in names:
        mark = " <--" if re.search(r"zon|plan|land.?use", n, re.I) else ""
        print(f"  {n}{mark}")
    return names


def arcgis_layer_probe(url, label, point=CBD):
    try:
        js = _get(f"{url}?f=json").json()
        if js.get("layers") is not None:
            print(f"\n{label} layers:")
            for lyr in js["layers"]:
                mark = "   <-- zoning?" if re.search(r"zon|land.?use", lyr["name"], re.I) else ""
                print(f"  [{lyr['id']:>3}] {lyr['name']}{mark}")
            return
        fields = [f["name"] for f in js.get("fields") or []]
        print(f"\n{label}: type={js.get('type')} geom={js.get('geometryType')} fields={fields[:20]}")
        q = _get(f"{url}/query", params={
            "geometry": point, "geometryType": "esriGeometryPoint", "inSR": 4326,
            "spatialRel": "esriSpatialRelIntersects", "outFields": "*",
            "returnGeometry": "false", "f": "json"}).json()
        feats = q.get("features", [])
        err = f" error={json.dumps(q.get('error'))[:200]}" if q.get("error") else ""
        print(f"  point query Brisbane CBD: {len(feats)} feature(s){err}")
        if feats:
            print(f"    {json.dumps(feats[0]['attributes'])[:400]}")
    except Exception as e:  # noqa: BLE001
        print(f"{label}: FAILED ({e})")


def datastore_sample(resource_id, label, rows=3):
    """data.qld.gov.au /download/ URLs serve an HTML wrapper to bots — the CKAN
    datastore API is the reliable path when a resource is datastore-active."""
    try:
        js = _get(f"{DATA_QLD}/datastore_search",
                  params={"resource_id": resource_id, "limit": str(rows)}).json()
        res = js.get("result") or {}
        fields = [f["id"] for f in res.get("fields", [])]
        print(f"  datastore {label}: {len(fields)} fields: {fields[:25]}")
        for rec in res.get("records", [])[:2]:
            print(f"    | {json.dumps(rec)[:300]}")
    except Exception as e:  # noqa: BLE001
        print(f"  datastore {label}: FAILED ({e!r})")


def main() -> None:
    # v3 recon (focused): v2 found division-level crime on S3, no open prices,
    # no statewide zoning layer (BCC City Plan + ShapingSEQ + Land Use as the
    # hybrid), and that data.qld /download/ URLs serve HTML wrappers to bots.
    section("CRIME — division file header (S3 direct)")
    sample_csv("https://open-crime-data.s3-ap-southeast-2.amazonaws.com/Crime%20Statistics/"
               "division_Reported_Offences_Number.csv", "division_Reported_Offences_Number.csv")

    section("ZONING — field/sample probes: ShapingSEQ 140, LandUse 0, BCC cp14 zoning")
    base = "https://spatial-gis.information.qld.gov.au/arcgis/rest/services"
    for lid, pt in ((140, CBD), (140, "152.76,-27.62"),   # CBD + rural Ipswich fringe
                    ):
        arcgis_layer_probe(f"{base}/PlanningCadastre/StatePlanning/MapServer/{lid}",
                           f"StatePlanning/{lid} @ {pt}", point=pt)
    for pt in (CBD, "153.10,-27.52"):
        arcgis_layer_probe(f"{base}/PlanningCadastre/LandUse/MapServer/0",
                           f"LandUse/0 @ {pt}", point=pt)
    try:
        js = _get("https://data.brisbane.qld.gov.au/api/explore/v2.1/catalog/datasets/"
                  "cp14-zoning-overlay/records", params={"limit": "2"}, headers=BROWSER).json()
        print(f"BCC cp14-zoning-overlay: total_count={js.get('total_count')}")
        for rec in js.get("results", [])[:2]:
            slim = {k: v for k, v in rec.items() if k != "geo_shape"}
            print(f"  | {json.dumps(slim)[:400]}")
        meta = _get("https://data.brisbane.qld.gov.au/api/explore/v2.1/catalog/datasets/"
                    "cp14-zoning-overlay", headers=BROWSER).json()
        flds = [f.get("name") for f in (meta.get("fields") or [])]
        print(f"  fields: {flds}")
    except Exception as e:  # noqa: BLE001
        print(f"BCC cp14-zoning-overlay FAILED ({e!r})")
    # other SEQ councils on opendatasoft/ArcGIS would go here later; BCC-only v1

    section("SCHOOLS — datastore API for the schools-directory resource")
    datastore_sample("5b39065c-df32-415c-994c-5ff12f8de997", "centredetails_may_2020.csv")

    section("RENTS — RTA datasets via CKAN org listing")
    try:
        js = _get(f"{DATA_QLD}/organization_list").json()
        orgs = [o for o in js["result"] if "tenanc" in o or "rta" in o or "housing" in o]
        print(f"candidate orgs: {orgs}")
        for org in orgs[:3]:
            js2 = _get(f"{DATA_QLD}/package_search",
                       params={"fq": f"organization:{org}", "rows": "10"}).json()
            for pkg in js2["result"]["results"]:
                print(f"  [{org}] {pkg['title']}")
    except Exception as e:  # noqa: BLE001
        print(f"org listing FAILED ({e!r})")

    section("TRANSPORT — GTFS rail stations + service-frequency proxy")
    try:
        r = requests.get("https://gtfsrt.api.translink.com.au/GTFS/SEQ_GTFS.zip",
                         headers=BROWSER, timeout=120)
        r.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            import csv as _csv
            routes = list(_csv.DictReader(io.TextIOWrapper(z.open("routes.txt"), "utf-8-sig")))
            from collections import Counter
            print("route_type histogram:", Counter(rt["route_type"] for rt in routes))
            rail_routes = {rt["route_id"] for rt in routes if rt["route_type"] in ("2",)}
            trips = list(_csv.DictReader(io.TextIOWrapper(z.open("trips.txt"), "utf-8-sig")))
            rail_trips = {t["trip_id"] for t in trips if t["route_id"] in rail_routes}
            print(f"rail routes: {len(rail_routes)}, rail trips: {len(rail_trips)}")
            stops = list(_csv.DictReader(io.TextIOWrapper(z.open("stops.txt"), "utf-8-sig")))
            parents = [s for s in stops if s.get("location_type") == "1"]
            print(f"stops: {len(stops)}, parent stations (location_type=1): {len(parents)}")
            for s in parents[:5]:
                print(f"  | {s['stop_id']} {s['stop_name']} ({s['stop_lat']},{s['stop_lon']})")
            # how big is stop_times (for the frequency proxy)?
            info = z.getinfo("stop_times.txt")
            print(f"stop_times.txt: {info.file_size/1e6:.0f} MB uncompressed")
    except Exception as e:  # noqa: BLE001
        print(f"GTFS probe FAILED ({e!r})")


def _unused_v2() -> None:  # kept for reference; superseded by the focused v3 above

    section("CRIME — enumerate the open-crime-data S3 bucket (suburb-level files?)")
    try:
        xml = _get("https://open-crime-data.s3-ap-southeast-2.amazonaws.com/",
                   params={"list-type": "2", "prefix": "Crime Statistics/", "max-keys": "400"}).text
        keys = re.findall(r"<Key>([^<]+)</Key>", xml)
        sizes = re.findall(r"<Size>(\d+)</Size>", xml)
        print(f"{len(keys)} objects under 'Crime Statistics/':")
        for k, s in zip(keys, sizes):
            print(f"  {int(s)/1e6:8.1f} MB  {k}")
        trunc = re.search(r"<IsTruncated>(\w+)</IsTruncated>", xml)
        print(f"truncated: {trunc.group(1) if trunc else '?'}")
    except Exception as e:  # noqa: BLE001
        print(f"S3 listing FAILED ({e!r})")
    # header of the most promising suburb-level file if present
    for cand in ("Suburb_Reported_Offences_Number.csv", "Division_Reported_Offences_Number.csv"):
        sample_csv("https://open-crime-data.s3-ap-southeast-2.amazonaws.com/Crime%20Statistics/"
                   + cand, cand)

    section("PRICES — open sale-price candidates (QVAS itself is paid)")
    for q in ("median sale price", "dwelling sales locality", "residential land activity",
              "property transfers"):
        try:
            for pkg in ckan_search(q, rows=3):
                tab = show_package(pkg, max_res=5)
                if tab:
                    sample_csv(tab["url"], tab.get("name", "")[:50])
        except Exception as e:  # noqa: BLE001
            print(f"FAILED ({e!r})")
    base = "https://spatial-gis.information.qld.gov.au/arcgis/rest/services"
    try:
        arcgis_folder(base, "RuralPropertySales")
    except Exception as e:  # noqa: BLE001
        print(f"RuralPropertySales FAILED ({e!r})")

    section("RENTS — RTA median rents (current URLs + CKAN)")
    for url in ("https://www.rta.qld.gov.au/forms-resources/median-rents/median-rents-quick-finder",
                "https://www.rta.qld.gov.au/median-rents",
                "https://www.rta.qld.gov.au/forms-resources/median-rents"):
        try:
            r = requests.get(url, headers=BROWSER, timeout=60, allow_redirects=True)
            print(f"GET {url} -> {r.status_code} (final: {r.url})")
            if r.ok:
                links = sorted(set(re.findall(r'href="([^"]+\.(?:xlsx|csv|xls|json)[^"]*)"', r.text, re.I)))
                print(f"  {len(links)} file links:")
                for ln in links[:15]:
                    print(f"    {ln}")
                # any API/data endpoints embedded in the page?
                apis = sorted(set(re.findall(r'"(https?://[^"]*(?:api|data)[^"]*)"', r.text, re.I)))[:10]
                for a in apis:
                    print(f"    api? {a}")
        except Exception as e:  # noqa: BLE001
            print(f"GET {url} FAILED ({e!r})")
    for q in ("median weekly rent", "RTA rents", "rental data"):
        try:
            for pkg in ckan_search(q, rows=3):
                tab = show_package(pkg, max_res=5)
                if tab:
                    sample_csv(tab["url"], tab.get("name", "")[:50])
        except Exception as e:  # noqa: BLE001
            print(f"FAILED ({e!r})")

    section("ZONING — layer lists of the real PlanningCadastre services")
    for svc in ("PlanningCadastre/StatePlanning", "PlanningCadastre/LandUse",
                "PlanningCadastre/PriorityDevelopmentAreas"):
        arcgis_layer_probe(f"{base}/{svc}/MapServer", svc)
    for q in ("planning scheme zones", "zoning"):
        try:
            for pkg in ckan_search(q, rows=4):
                show_package(pkg, max_res=4)
        except Exception as e:  # noqa: BLE001
            print(f"FAILED ({e!r})")
    # Brisbane City Council opendatasoft: city plan zoning (BCC LGA only, but a
    # concrete fallback if no statewide layer exists)
    try:
        js = _get("https://data.brisbane.qld.gov.au/api/explore/v2.1/catalog/datasets",
                  params={"where": 'search(dataset_id, "zoning")', "limit": "10"},
                  headers=BROWSER).json()
        for d in js.get("results", []):
            print(f"BCC dataset: {d.get('dataset_id')}  ({(d.get('metas') or {}).get('default', {}).get('title')})")
    except Exception as e:  # noqa: BLE001
        print(f"BCC catalog FAILED ({e!r})")

    section("TRANSPORT — station-level patronage (go card) on CKAN")
    for q in ("go card", "station entries", "SEQ patronage"):
        try:
            for pkg in ckan_search(q, rows=3):
                tab = show_package(pkg, max_res=6)
                if tab:
                    sample_csv(tab["url"], tab.get("name", "")[:50])
        except Exception as e:  # noqa: BLE001
            print(f"FAILED ({e!r})")

    section("SCHOOLS — header of the schools-directory CSV")
    sample_csv("https://www.data.qld.gov.au/dataset/0d7eee4a-2990-4195-9d3b-89f4af818e32/"
               "resource/5b39065c-df32-415c-994c-5ff12f8de997/download/centredetails_may_2020.csv",
               "centredetails_may_2020.csv")
    for q in ("schools directory locations", "school details"):
        try:
            for pkg in ckan_search(q, rows=3):
                tab = show_package(pkg, max_res=4)
                if tab:
                    sample_csv(tab["url"], tab.get("name", "")[:50])
        except Exception as e:  # noqa: BLE001
            print(f"FAILED ({e!r})")


if __name__ == "__main__":
    main()
