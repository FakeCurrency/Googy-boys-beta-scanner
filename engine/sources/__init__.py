"""Source adapters, dispatched per state.

census / erp / electricity are national (keyed by SA2 code or clipped by the
city bbox) and are imported directly. The state-specific layers — crime,
prices, rents, zoning, transport, schools — live in per-state namespaces that
all expose the same interface (see docs/AUSTRALIA.md "adapter contracts"):

    crime.get_crime() / get_crime_suburb(names, pops, lgas) / get_postcode_map(names, lgas)
    prices.get_prices(names)
    rents.get_rents(names, lgas)
    zoning.get_zoning(geoms)
    transport.get_stations(points, res_pts)
    schools.get_schools(points, res_pts)

The Victorian modules predate the split and stay at this package level;
NSW lives in sources/nsw/.
"""
from types import SimpleNamespace


def for_state(state_code: str) -> SimpleNamespace:
    """The state-specific adapter set for the active city."""
    if state_code == "VIC":
        from . import crime, prices, rents, schools, transport, zoning
    elif state_code == "NSW":
        from .nsw import crime, prices, rents, schools, transport, zoning
    elif state_code == "QLD":
        from .qld import crime, prices, rents, schools, transport, zoning
    else:
        raise ValueError(f"no source adapters for state {state_code!r} — see docs/AUSTRALIA.md")
    return SimpleNamespace(crime=crime, prices=prices, rents=rents,
                           schools=schools, transport=transport, zoning=zoning)
