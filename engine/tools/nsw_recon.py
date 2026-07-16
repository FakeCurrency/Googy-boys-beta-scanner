"""One-shot recon of NSW data sources for the Sydney adapters (docs/AUSTRALIA.md).

Run from CI, where the network is open (the sandboxed dev environment can't
reach government portals):

    python -m engine.tools.nsw_recon

For each source it prints the chosen CKAN packages, their resources
(name / format / size / url) and the header + first data line of the most
promising CSV — plus ArcGIS discovery for EPI Land Zoning (service list,
layer fields, one sample feature inside Greater Sydney). The output is the
ground truth the NSW adapters get written against, so keep it compact and
factual; every section is independent so one dead source can't hide the rest.
"""
from __future__ import annotations

import io
import json
import zipfile

import requests

UA = {"User-Agent": "Mozilla/5.0 (compatible; melbourne-property-recon)"}
DATA_NSW = "https://data.nsw.gov.au/data/api/3/action"
TFNSW = "https://opendata.transport.nsw.gov.au/data/api/3/action"


def _get(url, **kw):
    r = requests.get(url, headers=UA, timeout=60, **kw)
    r.raise_for_status()
    return r


def section(title):
    print(f"\n{'=' * 12} {title}")


def ckan_search(base, q, rows=6):
    js = _get(f"{base}/package_search", params={"q": q, "rows": rows}).json()
    res = js["result"]
    print(f"search '{q}': {res['count']} packages")
    return res["results"]


def show_package(pkg, max_res=8, note_first_csv=True):
    print(f"\npackage: {pkg['title']}  (id={pkg['id']})")
    org = (pkg.get("organization") or {}).get("title", "")
    print(f"  org={org}  updated={pkg.get('metadata_modified', '')[:10]}")
    first_csv = None
    for r in pkg.get("resources", [])[:max_res]:
        fmt = (r.get("format") or "").upper()
        size = r.get("size") or "?"
        print(f"  - [{fmt:>5}] {r.get('name', '')[:70]}  size={size}")
        print(f"           {r.get('url', '')}")
        if note_first_csv and first_csv is None and fmt in ("CSV", "XLSX", "XLS"):
            first_csv = r
    n = len(pkg.get("resources", []))
    if n > max_res:
        print(f"  ... {n - max_res} more resources")
    return first_csv


def sample_csv(url, label):
    """Print the header + first data row of a (possibly large) CSV without
    downloading it all; unzip in memory if it's a small zip."""
    try:
        r = requests.get(url, headers=UA, timeout=90, stream=True)
        r.raise_for_status()
        ct = r.headers.get("content-type", "")
        if url.lower().endswith(".zip") or "zip" in ct:
            buf = io.BytesIO(r.content if len(r.content) < 30e6 else b"")
            if not buf.getbuffer().nbytes:
                print(f"  sample {label}: zip too large to sample inline"); return
            with zipfile.ZipFile(buf) as z:
                name = next((n for n in z.namelist() if n.lower().endswith((".csv", ".dat"))), z.namelist()[0])
                lines = z.open(name).read(4000).decode("utf-8", "replace").splitlines()
                print(f"  sample {label} ({name}):")
        else:
            chunk = next(r.iter_content(8192)).decode("utf-8", "replace")
            lines = chunk.splitlines()
            print(f"  sample {label} (content-type={ct}):")
        for ln in lines[:3]:
            print(f"    | {ln[:240]}")
    except Exception as e:  # noqa: BLE001 - recon keeps going
        print(f"  sample {label}: FAILED ({e})")


def arcgis_find_zoning():
    base = "https://mapprod3.environment.nsw.gov.au/arcgis/rest/services"
    for folder in ("ePlanning", "Planning"):
        try:
            js = _get(f"{base}/{folder}?f=json").json()
            names = [s["name"] for s in js.get("services", [])]
            print(f"{folder}: {len(names)} services")
            for n in names:
                print(f"  - {n}")
        except Exception as e:  # noqa: BLE001
            print(f"{folder}: FAILED ({e})")
    # the principal planning layers service usually carries Land Zoning
    for svc in ("ePlanning/Planning_Portal_Principal_Planning",
                "ePlanning/Planning_Portal_Planning_Layers"):
        try:
            js = _get(f"{base}/{svc}/MapServer?f=json").json()
            print(f"\n{svc}/MapServer layers:")
            zoning_ids = []
            for lyr in js.get("layers", []):
                mark = ""
                if "zoning" in lyr["name"].lower():
                    zoning_ids.append(lyr["id"]); mark = "   <-- ZONING"
                print(f"  [{lyr['id']:>3}] {lyr['name']}{mark}")
            for lid in zoning_ids[:1]:
                meta = _get(f"{base}/{svc}/MapServer/{lid}?f=json").json()
                print(f"\n  layer {lid} fields:")
                for f in meta.get("fields", [])[:25]:
                    print(f"    {f['name']} ({f['type']})")
                q = _get(f"{base}/{svc}/MapServer/{lid}/query", params={
                    "geometry": "151.21,-33.87", "geometryType": "esriGeometryPoint",
                    "inSR": 4326, "spatialRel": "esriSpatialRelIntersects",
                    "outFields": "*", "returnGeometry": "false", "f": "json",
                }).json()
                feats = q.get("features", [])
                print(f"  sample query at Sydney CBD: {len(feats)} feature(s)")
                if feats:
                    print(f"    {json.dumps(feats[0]['attributes'])[:400]}")
        except Exception as e:  # noqa: BLE001
            print(f"{svc}: FAILED ({e})")


def main() -> None:
    section("CRIME — BOCSAR via data.nsw CKAN")
    try:
        for pkg in ckan_search(DATA_NSW, "bocsar criminal incidents", rows=4):
            csv = show_package(pkg)
            if csv:
                sample_csv(csv["url"], csv.get("name", "")[:50])
    except Exception as e:  # noqa: BLE001
        print(f"FAILED ({e})")

    section("PRICES — NSW Valuer General bulk property sales (PSI)")
    for url in ("https://www.valuergeneral.nsw.gov.au/__psi/yearly/2024.zip",
                "https://www.valuergeneral.nsw.gov.au/__psi/yearly/2023.zip"):
        try:
            r = requests.head(url, headers=UA, timeout=30, allow_redirects=True)
            print(f"HEAD {url} -> {r.status_code} bytes={r.headers.get('content-length')}")
        except Exception as e:  # noqa: BLE001
            print(f"HEAD {url} FAILED ({e})")
    try:
        for pkg in ckan_search(DATA_NSW, "valuer general property sales", rows=3):
            show_package(pkg, max_res=5, note_first_csv=False)
    except Exception as e:  # noqa: BLE001
        print(f"FAILED ({e})")

    section("RENTS — rental bond lodgements via data.nsw CKAN")
    try:
        for pkg in ckan_search(DATA_NSW, "rental bond lodgement", rows=4):
            csv = show_package(pkg, max_res=6)
            if csv:
                sample_csv(csv["url"], csv.get("name", "")[:50])
                break
    except Exception as e:  # noqa: BLE001
        print(f"FAILED ({e})")

    section("TRANSPORT — TfNSW train station entries/exits")
    try:
        for pkg in ckan_search(TFNSW, "train station entries and exits", rows=3):
            csv = show_package(pkg, max_res=6)
            if csv:
                sample_csv(csv["url"], csv.get("name", "")[:50])
                break
    except Exception as e:  # noqa: BLE001
        print(f"FAILED ({e})")

    section("SCHOOLS — NSW school locations via data.nsw CKAN")
    try:
        for pkg in ckan_search(DATA_NSW, "nsw school locations master dataset", rows=3):
            csv = show_package(pkg, max_res=5)
            if csv:
                sample_csv(csv["url"], csv.get("name", "")[:50])
                break
    except Exception as e:  # noqa: BLE001
        print(f"FAILED ({e})")

    section("ZONING — EPI Land Zoning via NSW planning ArcGIS")
    arcgis_find_zoning()


if __name__ == "__main__":
    main()
