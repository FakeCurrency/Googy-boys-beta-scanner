"""QLD sale prices: no open source exists — Brisbane v1 ships without them.

City Probe recon (runs #1-3) confirmed the bulk QVAS sales data is paid-only,
the titles registry publishes lodgement *counts*, and no CKAN/QSpatial dataset
carries sale prices. The scorer renormalises the missing inputs and the
scorecard's market block has an explicit no-medians branch. Candidate future
sources are tracked in docs/AUSTRALIA.md.
"""
from __future__ import annotations


def get_prices(name_by_code: dict[str, str]) -> dict[str, dict]:
    print("  prices: no open QLD sale-price source (QVAS is paid) — shipping without "
          "medians; see docs/AUSTRALIA.md")
    return {code: {} for code in name_by_code}
