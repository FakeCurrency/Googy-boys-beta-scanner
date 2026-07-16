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
        r = requests.get(url, headers=BROWSER, timeout=90, stream=True)
        r.raise_for_status()
        ct = r.headers.get("content-type", "")
        chunk = next(r.iter_content(16384)).decode("utf-8", "replace")
        print(f"  sample {label} (content-type={ct}):")
        for ln in chunk.splitlines()[:3]:
            print(f"    | {ln[:280]}")
        r.close()
    except Exception as e:  # noqa: BLE001 - recon keeps going
        print(f"  sample {label}: FAILED ({e})")


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
    section("CRIME — QPS offence data (CKAN)")
    for q in ("crime offence suburb", "qps offences"):
        try:
            for pkg in ckan_search(q, rows=3):
                tab = show_package(pkg)
                if tab:
                    sample_csv(tab["url"], tab.get("name", "")[:50])
        except Exception as e:  # noqa: BLE001
            print(f"FAILED ({e})")
    # the QPS online crime map is ArcGIS-backed; probe the well-known host
    arcgis_layer_probe("https://mapi.police.qld.gov.au/arcgis/rest/services", "QPS ArcGIS root")

    section("PRICES — Qld property sales (CKAN; may be paid QVAS)")
    for q in ("property sales", "residential land sales", "valuation sales"):
        try:
            for pkg in ckan_search(q, rows=3):
                tab = show_package(pkg)
                if tab:
                    sample_csv(tab["url"], tab.get("name", "")[:50])
        except Exception as e:  # noqa: BLE001
            print(f"FAILED ({e})")

    section("RENTS — RTA median rents (CKAN + rta.qld.gov.au scrape)")
    for q in ("median rents", "rental bond"):
        try:
            for pkg in ckan_search(q, rows=3):
                tab = show_package(pkg)
                if tab:
                    sample_csv(tab["url"], tab.get("name", "")[:50])
        except Exception as e:  # noqa: BLE001
            print(f"FAILED ({e})")
    try:
        html = _get("https://www.rta.qld.gov.au/median-rents-quick-finder", headers=BROWSER).text
        links = sorted(set(re.findall(r'href="([^"]+\.(?:xlsx|csv|xls)[^"]*)"', html, re.I)))
        print(f"rta.qld.gov.au quick-finder: {len(links)} file links")
        for ln in links[:15]:
            print(f"  {ln}")
    except Exception as e:  # noqa: BLE001
        print(f"rta.qld.gov.au scrape FAILED ({e})")

    section("ZONING — QSpatial statewide land-use zoning (ArcGIS)")
    base = "https://spatial-gis.information.qld.gov.au/arcgis/rest/services"
    try:
        js = _get(f"{base}?f=json").json()
        print(f"root folders: {js.get('folders')}")
        for folder in ("PlanningCadastre", "Basemaps", "Boundaries"):
            if folder in (js.get("folders") or []):
                try:
                    arcgis_folder(base, folder)
                except Exception as e:  # noqa: BLE001
                    print(f"{folder}: FAILED ({e})")
    except Exception as e:  # noqa: BLE001
        print(f"QSpatial root FAILED ({e})")
    # the commonly cited statewide layer (probe both MapServer + layer 0)
    for u, lbl in ((f"{base}/PlanningCadastre/LandUseZoning/MapServer", "LandUseZoning MapServer"),
                   (f"{base}/PlanningCadastre/LandUseZoning/MapServer/0", "LandUseZoning layer 0")):
        arcgis_layer_probe(u, lbl)

    section("TRANSPORT — TransLink SEQ GTFS stops + patronage (CKAN)")
    try:
        r = requests.get("https://gtfsrt.api.translink.com.au/GTFS/SEQ_GTFS.zip",
                         headers=BROWSER, timeout=120)
        r.raise_for_status()
        print(f"SEQ_GTFS.zip: {len(r.content)/1e6:.1f} MB")
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            print(f"  files: {z.namelist()[:10]}")
            for name in ("stops.txt", "routes.txt"):
                if name in z.namelist():
                    lines = z.open(name).read(3000).decode("utf-8", "replace").splitlines()
                    print(f"  head of {name}:")
                    for ln in lines[:2]:
                        print(f"    | {ln[:280]}")
    except Exception as e:  # noqa: BLE001
        print(f"SEQ GTFS FAILED ({e})")
    for q in ("translink patronage", "rail station patronage"):
        try:
            for pkg in ckan_search(q, rows=3):
                tab = show_package(pkg)
                if tab:
                    sample_csv(tab["url"], tab.get("name", "")[:50])
        except Exception as e:  # noqa: BLE001
            print(f"FAILED ({e})")

    section("SCHOOLS — Qld state school locations (CKAN)")
    for q in ("state school locations", "school enrolments"):
        try:
            for pkg in ckan_search(q, rows=3):
                tab = show_package(pkg)
                if tab:
                    sample_csv(tab["url"], tab.get("name", "")[:50])
        except Exception as e:  # noqa: BLE001
            print(f"FAILED ({e})")


if __name__ == "__main__":
    main()
