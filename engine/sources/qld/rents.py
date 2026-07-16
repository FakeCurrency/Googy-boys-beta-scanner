"""QLD weekly rents: no fetchable open source found — Brisbane v1 ships without.

The RTA's median-rents pages moved behind an interactive lookup (all direct
URLs 404), data.qld.gov.au has no RTA median-rent dataset, and the portal's
/download/ endpoints serve HTML wrappers to non-browser clients. The scorer
renormalises; the scorecard rent line is guarded. Future options (RTA lookup
via headed browser in CI, or a QGSO republication) live in docs/AUSTRALIA.md.
"""
from __future__ import annotations


def get_rents(name_by_code: dict[str, str], lga_by_code: dict[str, str]) -> dict[str, dict]:
    print("  rents: no fetchable open QLD median-rent source (RTA is an interactive "
          "lookup) — shipping without rents; see docs/AUSTRALIA.md")
    return {code: {} for code in name_by_code}
