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


def sample_zip(url, label, max_mb=40):
    """Download a zip (bounded), list its contents, print header + 2 rows of
    the first CSV inside."""
    try:
        r = _get(url)
        if len(r.content) > max_mb * 1e6:
            print(f"  {label}: zip is {len(r.content)/1e6:.0f} MB — skipped"); return
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            names = z.namelist()
            print(f"  {label}: {len(names)} file(s): {names[:6]}")
            csvs = [n for n in names if n.lower().endswith((".csv", ".dat", ".txt"))]
            if csvs:
                lines = z.open(csvs[0]).read(6000).decode("utf-8", "replace").splitlines()
                print(f"  head of {csvs[0]}:")
                for ln in lines[:3]:
                    print(f"    | {ln[:300]}")
    except Exception as e:  # noqa: BLE001
        print(f"  {label}: FAILED ({e})")


def main() -> None:
    section("CRIME — BOCSAR suburb + postcode zips (direct blob URLs)")
    sample_zip("https://bocsarblob.blob.core.windows.net/bocsar-open-data/SuburbData.zip",
               "SuburbData.zip")
    sample_zip("https://bocsarblob.blob.core.windows.net/bocsar-open-data/PostcodeData.zip",
               "PostcodeData.zip")

    section("PRICES — NSW Valuer General PSI (direct 403 -> Wayback fallback?)")
    for url in ("https://www.valuergeneral.nsw.gov.au/__psi/yearly/2024.zip",):
        try:
            r = requests.get(url, timeout=30, stream=True, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://valuation.property.nsw.gov.au/embed/propertySalesInformation"})
            print(f"GET {url} (browser UA) -> {r.status_code} type={r.headers.get('content-type')}")
            r.close()
        except Exception as e:  # noqa: BLE001
            print(f"GET {url} FAILED ({e})")
    for y in (2024, 2023):
        try:
            js = _get("https://archive.org/wayback/available",
                      params={"url": f"valuergeneral.nsw.gov.au/__psi/yearly/{y}.zip"}).json()
            snap = (js.get("archived_snapshots") or {}).get("closest") or {}
            print(f"wayback {y}.zip: available={snap.get('available')} url={snap.get('url')} ts={snap.get('timestamp')}")
        except Exception as e:  # noqa: BLE001
            print(f"wayback {y}: FAILED ({e})")

    section("RENTS — scrape Fair Trading rental-bond-data page for file links")
    try:
        import re
        html = _get("https://www.fairtrading.nsw.gov.au/about-fair-trading/rental-bond-data").text
        links = sorted(set(re.findall(r'href="([^"]+\.(?:xlsx|csv|xls)[^"]*)"', html, re.I)))
        print(f"{len(links)} file links:")
        for ln in links[:25]:
            print(f"  {ln}")
    except Exception as e:  # noqa: BLE001
        print(f"FAILED ({e})")

    section("TRANSPORT — TfNSW station LOCATIONS (patronage CSV already confirmed)")
    for q in ("train station locations", "location facilities and operators"):
        try:
            for pkg in ckan_search(TFNSW, q, rows=2):
                csv = show_package(pkg, max_res=6)
                if csv:
                    sample_csv(csv["url"], csv.get("name", "")[:50])
        except Exception as e:  # noqa: BLE001
            print(f"FAILED ({e})")

    section("SCHOOLS — full header of the NSW master dataset")
    try:
        r = _get("https://data.nsw.gov.au/data/dataset/78c10ea3-8d04-4c9c-b255-bbf8547e37e7/"
                 "resource/3e6d5f6a-055c-440d-a690-fc0537c31095/download/master_dataset.csv",
                 stream=True)
        first = next(r.iter_content(16384)).decode("utf-8", "replace").splitlines()[0]
        print("columns:")
        for c in first.split(","):
            print(f"  - {c}")
        r.close()
    except Exception as e:  # noqa: BLE001
        print(f"FAILED ({e})")

    section("ZONING — EPI Land Zoning layer fields + sample features")
    base = "https://mapprod3.environment.nsw.gov.au/arcgis/rest/services"
    for svc, lids in (("ePlanning/Planning_Portal_Principal_Planning", (17, 19)),
                      ("Planning/EPI_Primary_Planning_Layers", None)):
        try:
            if lids is None:
                js = _get(f"{base}/{svc}/MapServer?f=json").json()
                print(f"\n{svc} layers:")
                lids = []
                for lyr in js.get("layers", []):
                    mark = "   <-- ZONING" if "zoning" in lyr["name"].lower() else ""
                    if mark:
                        lids.append(lyr["id"])
                    print(f"  [{lyr['id']:>3}] {lyr['name']}{mark}")
            for lid in list(lids)[:2]:
                meta = _get(f"{base}/{svc}/MapServer/{lid}?f=json").json()
                fields = meta.get("fields") or []
                print(f"\n{svc} layer {lid} ({meta.get('name')}): type={meta.get('type')} "
                      f"minScale={meta.get('minScale')} fields={[f['name'] for f in fields][:18]}")
                q = _get(f"{base}/{svc}/MapServer/{lid}/query", params={
                    "geometry": "151.21,-33.87", "geometryType": "esriGeometryPoint",
                    "inSR": 4326, "spatialRel": "esriSpatialRelIntersects",
                    "outFields": "*", "returnGeometry": "false", "f": "json",
                }).json()
                feats = q.get("features", [])
                print(f"  point query Sydney CBD: {len(feats)} feature(s) "
                      f"{('error: ' + json.dumps(q.get('error'))[:200]) if q.get('error') else ''}")
                if feats:
                    print(f"    {json.dumps(feats[0]['attributes'])[:400]}")
        except Exception as e:  # noqa: BLE001
            print(f"{svc}: FAILED ({e})")


if __name__ == "__main__":
    main()
