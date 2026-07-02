"""Cached HTTP download helper shared by all data-source modules.

Downloads are large government files that rarely change, so we cache them in
data_raw/ and only re-fetch when missing (or force=True).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import requests

from . import config

_HEADERS = {"User-Agent": "Mozilla/5.0 (melb-scorer data build)"}


def fetch(url: str, filename: str | None = None, force: bool = False) -> Path:
    """Download ``url`` into data_raw/ and return the local path (cached).

    Government hosts can be very slow from datacenter IPs (GitHub Actions), so
    retry with a growing timeout before giving up.
    """
    config.DATA_RAW.mkdir(parents=True, exist_ok=True)
    name = filename or url.split("/")[-1].split("?")[0]
    dest = config.DATA_RAW / name
    if dest.exists() and dest.stat().st_size > 0 and not force:
        print(f"  cached  {name} ({dest.stat().st_size/1e6:.1f} MB)")
        return dest

    last_err: Exception | None = None
    for attempt, timeout in enumerate((120, 240, 360), start=1):
        try:
            print(f"  downloading {name}{f' (attempt {attempt})' if attempt > 1 else ''} ...", flush=True)
            with requests.get(url, headers=_HEADERS, stream=True, timeout=timeout) as r:
                r.raise_for_status()
                tmp = dest.with_suffix(dest.suffix + ".part")
                with open(tmp, "wb") as fh:
                    for chunk in r.iter_content(chunk_size=1 << 20):
                        fh.write(chunk)
                tmp.replace(dest)
            print(f"  downloaded  {name} ({dest.stat().st_size/1e6:.1f} MB)")
            return dest
        except Exception as e:  # noqa: BLE001 - retry on any transport error
            last_err = e
            time.sleep(5 * attempt)
    raise RuntimeError(f"Could not download {url} after 3 attempts: {last_err}")


def fetch_wayback(url: str, filename: str, force: bool = False) -> Path:
    """Download a file via the Wayback Machine.

    Some official hosts (e.g. land.vic.gov.au) sit behind a bot-protection WAF
    that 403s automated requests. The Internet Archive keeps clean copies, so we
    resolve the closest snapshot and pull the raw bytes (``id_`` form).

    The availability API is flaky from datacenter IPs (e.g. GitHub Actions), so
    on failure we fall back to Wayback's wildcard-timestamp redirect and finally
    the direct source URL, rejecting HTML error/challenge pages.
    """
    config.DATA_RAW.mkdir(parents=True, exist_ok=True)
    dest = config.DATA_RAW / filename
    if dest.exists() and dest.stat().st_size > 0 and not force:
        print(f"  cached  {filename} ({dest.stat().st_size/1e6:.1f} MB)")
        return dest

    snap_url = None
    for attempt in range(3):
        try:
            avail = requests.get("http://archive.org/wayback/available",
                                 params={"url": url}, headers=_HEADERS, timeout=60).json()
            snap = avail.get("archived_snapshots", {}).get("closest", {})
            if snap.get("available"):
                snap_url = f"https://web.archive.org/web/{snap['timestamp']}id_/{url}"
                break
        except Exception:
            pass
        time.sleep(3 * (attempt + 1))

    # "2id_" = wildcard timestamp: web.archive.org redirects to the nearest snapshot.
    candidates = [u for u in (snap_url, f"https://web.archive.org/web/2id_/{url}", url) if u]
    last_err: Exception | None = None
    for cand in candidates:
        try:
            print(f"  downloading {filename} via {cand.split('/')[2]} ...")
            r = requests.get(cand, headers=_HEADERS, timeout=120, allow_redirects=True)
            r.raise_for_status()
            if r.content[:200].lstrip().lower().startswith((b"<!doctype", b"<html")):
                raise RuntimeError("got an HTML page instead of the file (WAF/error page)")
            dest.write_bytes(r.content)
            print(f"  downloaded  {filename} ({dest.stat().st_size/1e6:.1f} MB)")
            return dest
        except Exception as e:  # noqa: BLE001 - try the next fallback
            last_err = e
    raise RuntimeError(f"Could not fetch {url} via Wayback or directly: {last_err}")


def arcgis_query_all(layer_url: str, out_fields: str, where: str = "1=1") -> list[dict]:
    """Page through an ArcGIS FeatureServer layer and return all attribute dicts."""
    rows: list[dict] = []
    offset = 0
    page = 2000
    while True:
        params = {
            "where": where,
            "outFields": out_fields,
            "returnGeometry": "false",
            "resultOffset": offset,
            "resultRecordCount": page,
            "f": "json",
        }
        r = requests.get(layer_url + "/query", params=params, headers=_HEADERS, timeout=120)
        r.raise_for_status()
        data = r.json()
        feats = data.get("features", [])
        rows.extend(f["attributes"] for f in feats)
        if not data.get("exceededTransferLimit") or not feats:
            break
        offset += len(feats)
    return rows


if __name__ == "__main__":  # pragma: no cover - manual use
    for u in sys.argv[1:]:
        print(fetch(u))
