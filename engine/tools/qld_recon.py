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


def main() -> None:
    # v2 recon: v1 (run #1) confirmed the QPS S3 bucket, SEQ GTFS and the
    # schools-directory CSV, and ruled out my guessed LandUseZoning service +
    # the old RTA quick-finder URL. This pass drills into exactly the gaps.

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
