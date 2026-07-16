"""Central configuration for the Melbourne Property build engine.

Tune everything here: which city, where data comes from, and how the two
scores (Liveability + Development potential) are weighted.
"""
from pathlib import Path

# --- Paths -----------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
DATA_RAW = ROOT / "data_raw"          # cached source downloads (gitignored)
PUBLIC = ROOT / "public"
PUBLIC_DATA = PUBLIC / "data"

# --- Cities ------------------------------------------------------------------
# We score ABS SA2 areas ("suburbs") inside one Greater Capital City at a time.
# Each city is a profile here; everything city-specific the frontend needs
# ships inside that city's scores.json (state, regions), and each city's files
# live under public/data/<slug>/. Adding a city = a profile + per-state source
# adapters — see docs/AUSTRALIA.md for the full plan and per-state source matrix.
#
# `regions`: compass-word -> ABS SA4 lists for the Ask box's region filter.
# Curated per city because these are colloquial judgment calls, not string
# matches ("east" must not match "Melbourne - South East"; Sydney's "inner
# west" is its own SA4). ORDER MATTERS: the frontend takes the first key that
# matches, so longer phrases must come before the single words they contain.
CITIES = {
    "melbourne": {
        "slug": "melbourne", "name": "Melbourne",
        "gcc": "Greater Melbourne",   # matches GCC_NAME21 in the ABS shapefile
        "state": "Victoria", "state_code": "VIC",
        "ready": True,                # all source adapters exist
        # geographic envelope (lon0, lat0, lon1, lat1) used to clip national
        # point/line datasets, and the local equirectangular projection origin
        "bbox": (144.2, -38.7, 145.9, -37.1),
        "origin": (145.0, -37.8),
        "regions": {
            "inner west": ["Melbourne - West"],
            "inner north": ["Melbourne - Inner"],
            "inner east": ["Melbourne - Inner East"],
            "inner south": ["Melbourne - Inner South"],
            "outer east": ["Melbourne - Outer East"],
            "north east": ["Melbourne - North East"],
            "north west": ["Melbourne - North West"],
            "south east": ["Melbourne - South East"],
            "inner": ["Melbourne - Inner", "Melbourne - Inner East", "Melbourne - Inner South"],
            "west": ["Melbourne - West", "Melbourne - North West"],
            "north": ["Melbourne - North East", "Melbourne - North West"],
            "east": ["Melbourne - Inner East", "Melbourne - Outer East", "Melbourne - North East"],
            "south": ["Melbourne - Inner South", "Melbourne - South East", "Mornington Peninsula"],
            "mornington": ["Mornington Peninsula"],
            "peninsula": ["Mornington Peninsula"],
        },
    },
    # Profile scaffold: the ABS layers (boundaries, SEIFA, Census, ERP) and the
    # Geoscience Australia grid are national and work as-is, but the NSW source
    # adapters (BOCSAR crime, Valuer General prices, bond-board rents, planning
    # portal zoning, TfNSW stations) are not built yet — engine.run refuses a
    # full build until they are. docs/AUSTRALIA.md has the adapter contracts.
    "sydney": {
        "slug": "sydney", "name": "Sydney",
        "gcc": "Greater Sydney",
        "state": "New South Wales", "state_code": "NSW",
        "ready": True,   # NSW adapters in sources/nsw/ (v1 — see docs/AUSTRALIA.md caveats)
        "bbox": (149.9, -34.6, 151.8, -32.8),   # incl. Central Coast + Blue Mountains foothills
        "origin": (151.0, -33.8),
        "regions": {
            "eastern suburbs": ["Sydney - Eastern Suburbs"],
            "northern beaches": ["Sydney - Northern Beaches"],
            "north shore": ["Sydney - North Sydney and Hornsby", "Sydney - Ryde"],
            "central coast": ["Central Coast"],
            "inner west": ["Sydney - Inner West"],
            "inner south": ["Sydney - City and Inner South"],
            "south west": ["Sydney - South West", "Sydney - Outer South West", "Sydney - Inner South West"],
            "outer west": ["Sydney - Outer West and Blue Mountains", "Sydney - Blacktown"],
            "inner": ["Sydney - City and Inner South", "Sydney - Inner West", "Sydney - Eastern Suburbs"],
            "east": ["Sydney - Eastern Suburbs"],
            "north": ["Sydney - North Sydney and Hornsby", "Sydney - Northern Beaches",
                      "Sydney - Ryde", "Sydney - Baulkham Hills and Hawkesbury"],
            "west": ["Sydney - Parramatta", "Sydney - Blacktown", "Sydney - Outer West and Blue Mountains"],
            "south": ["Sydney - Sutherland", "Sydney - Inner South West", "Sydney - South West"],
            "hills": ["Sydney - Baulkham Hills and Hawkesbury"],
            "shire": ["Sydney - Sutherland"],
            "sutherland": ["Sydney - Sutherland"],
            "parramatta": ["Sydney - Parramatta"],
            "blacktown": ["Sydney - Blacktown"],
        },
    },
    # QLD adapters not built yet — engine.run allows --geo-only but refuses a
    # full build until sources/qld/ exists. Flip ready once they land.
    "brisbane": {
        "slug": "brisbane", "name": "Brisbane",
        "gcc": "Greater Brisbane",
        "state": "Queensland", "state_code": "QLD",
        "ready": False,
        "bbox": (152.0, -28.4, 153.6, -26.4),   # Ipswich to Moreton Bay/Redlands
        "origin": (153.03, -27.47),
        "regions": {
            "inner city": ["Brisbane Inner City"],
            "north side": ["Brisbane - North", "Moreton Bay - South"],
            "south side": ["Brisbane - South", "Logan - Beaudesert"],
            "east": ["Brisbane - East"],
            "bayside": ["Brisbane - East"],
            "redlands": ["Brisbane - East"],
            "west": ["Brisbane - West"],
            "north": ["Brisbane - North", "Moreton Bay - North", "Moreton Bay - South"],
            "south": ["Brisbane - South", "Logan - Beaudesert"],
            "inner": ["Brisbane Inner City", "Brisbane - West"],
            "ipswich": ["Ipswich"],
            "logan": ["Logan - Beaudesert"],
            "moreton bay": ["Moreton Bay - North", "Moreton Bay - South"],
        },
    },
}

# Active city. engine.run --city <slug> switches it via set_city(); the
# module-level aliases below exist so source modules keep reading the same
# names they always have.
CITY = CITIES["melbourne"]
GCC_NAME = CITY["gcc"]
STATE_NAME = CITY["state"]
STATE_CODE = CITY["state_code"]
CITY_REGIONS = CITY["regions"]
CITY_BBOX = CITY["bbox"]
CITY_ORIGIN = CITY["origin"]
CITY_DATA = PUBLIC / "data" / CITY["slug"]   # this city's output directory
BOUNDARIES_NAME = "boundaries.geojson"


def set_city(slug: str) -> None:
    """Point the whole engine at another city profile."""
    global CITY, GCC_NAME, STATE_NAME, STATE_CODE, CITY_REGIONS, CITY_BBOX, CITY_ORIGIN, CITY_DATA
    CITY = CITIES[slug]
    GCC_NAME = CITY["gcc"]
    STATE_NAME = CITY["state"]
    STATE_CODE = CITY["state_code"]
    CITY_REGIONS = CITY["regions"]
    CITY_BBOX = CITY["bbox"]
    CITY_ORIGIN = CITY["origin"]
    CITY_DATA = PUBLIC / "data" / CITY["slug"]

# --- Data sources (all free, public) --------------------------------------
# Boundaries: ABS ASGS Edition 3 SA2 (2021), GDA2020 shapefile (~48 MB).
SA2_SHP_URL = (
    "https://www.abs.gov.au/statistics/standards/"
    "australian-statistical-geography-standard-asgs/edition-3-july-2021-june-2026/"
    "access-and-downloads/digital-boundary-files/SA2_2021_AUST_SHP_GDA2020.zip"
)

# Other source URLs are resolved/confirmed in their own modules
# (engine/sources/crime.py, engine/sources/census.py) so this file stays stable.

# --- GeoJSON simplification ------------------------------------------------
# Douglas-Peucker tolerance in degrees (~0.0004 deg ≈ 35 m at Melbourne's
# latitude) and coordinate decimal places. Tuned to keep the file < ~2 MB.
SIMPLIFY_TOL = 0.0004
COORD_PRECISION = 5

# --- Scoring ---------------------------------------------------------------
# Each input is percentile-normalised across all Greater Melbourne SA2s to a
# 0-100 score (higher = better) before weighting. Weights need not sum to 1;
# they are normalised at runtime.
#
# Liveability: is this a good place to *live* right now? Personal safety leads.
# BASE weights (used in Balanced + Invest modes, where property crime still
# matters for resale/insurance).
LIVE_WEIGHTS = {
    "person_safety": 0.32,   # inverse rate of crimes AGAINST THE PERSON (assault, robbery, sexual)
    "seifa": 0.24,           # SEIFA IRSAD advantage
    "transport": 0.10,       # train-station access (nearest station distance)
    "owner_occ": 0.08,       # owner-occupier share -> stability
    "schools": 0.07,         # school access (nearest primary/secondary + density)
    "property_safety": 0.05, # inverse property-crime rate (secondary, transparent)
    "family_child": 0.05,    # share of children 0-14 (family-area signal)
    "hazard_free": 0.05,     # less flood (LSIO/SBO/FO) + bushfire (BMO) overlay coverage
    "parks": 0.04,           # public park / conservation land share (green space)
}

# FAMILY weights (used in Live / Family-First mode): for a "raise my kid here"
# view, property crime barely matters while family/child + schools lead
# alongside personal safety. Computed as a second Liveability value (live_family).
LIVE_WEIGHTS_FAMILY = {
    "person_safety": 0.32,   # personal safety still the #1 driver
    "seifa": 0.17,           # socio-economic advantage (amenity proxy)
    "family_child": 0.14,    # children 0-14 share weighted up for the family lens
    "schools": 0.12,         # actual school access matters most in this lens
    "owner_occ": 0.08,       # settled owner-occupier base
    "transport": 0.07,       # train access still counts for school-run/commute
    "parks": 0.04,           # green space matters most for the family lens
    "hazard_free": 0.04,     # flood/bushfire overlays matter for a family home
    "property_safety": 0.02, # property crime: minimal weight for a family-living view
}

# Family Suitability sub-score (a highlight/badge, lightly folded into Liveability
# via family_child above). Blends child share, education/occupation, safety, schools.
FAMILY_WEIGHTS = {
    "child": 0.32,           # share of population aged 0-14
    "ieo": 0.28,             # SEIFA Index of Education & Occupation
    "person_safety": 0.22,   # personal-safety percentile
    "schools": 0.18,         # school-access sub-score
}

# School-access sub-score (feeds Liveability + Family).
SCHOOL_WEIGHTS = {
    "primary": 0.45,         # closer to the nearest primary school
    "secondary": 0.35,       # closer to the nearest secondary school
    "density": 0.20,         # more schools within ~3 km (choice)
}

# Development potential = zoning headroom + physical headroom + price growth +
# electricity infra + station access + rental economics. Phase 4 added real
# planning controls (Vicmap zones + Heritage Overlay) and rental yield.
DEV_WEIGHTS = {
    "detached_share": 0.19,  # low-density separate houses -> redevelopment headroom
    "zoning": 0.17,          # share of land zoned for growth (RGZ/MUZ/ACZ/C1Z/HCTZ...)
    "growth": 0.12,          # recent capital growth (VG 3yr CAGR, percentile)
    "infra": 0.12,           # electricity-network support (see INFRA_WEIGHTS)
    "station": 0.10,         # train-station proximity (activity-centre uplift signal)
    "yield": 0.08,           # gross rental yield (unit yield where units dominate)
    "rental_share": 0.07,    # rental share -> turnover / investor activity
    "low_density": 0.05,     # lower current density (persons/km2) -> headroom
    "heritage_free": 0.05,   # less Heritage Overlay coverage -> fewer constraints
    "hazard_free": 0.05,     # less flood/bushfire overlay -> fewer approval/insurance drags
}

# Two development sub-lenses (both percentile-stretched like the headline Dev):
# Greenfield = the land-supply corridor story; Infill = established-area uplift
# (upzoning + station-centred activity-centre policy). Surfaced as their own
# colour-by lenses so the HCTZ/upzoning story isn't buried by UGZ corridors.
DEV_GREENFIELD_WEIGHTS = {
    "ugz": 0.30,             # Urban Growth Zone share — literal greenfield precincts
    "unrestricted": 0.12,    # NOT green wedge/farming/conservation (that land can't be developed)
    "low_density": 0.12,     # land headroom
    "pop_growth": 0.10,      # ERP year-on-year growth — where demand is actually landing
    "growth": 0.10,          # corridor price momentum
    "detached_share": 0.08,  # house-and-land stock
    "yield": 0.10,           # investor economics
    "infra": 0.08,           # grid support for estate-scale build-out
}
DEV_INFILL_WEIGHTS = {
    "upzone": 0.30,          # upzoned share ONLY (RGZ/MUZ/ACZ/HCTZ/commercial — not UGZ)
    "station": 0.20,         # walkable to a station (activity-centre policy)
    "detached_share": 0.15,  # knockdown-rebuild stock within the upzoned fabric
    "heritage_free": 0.10,   # heritage controls kill infill feasibility
    "growth": 0.10,          # market momentum
    "rental_share": 0.10,    # renter demand for the built product
    "hazard_free": 0.05,     # flood/bushfire overlays complicate approvals
}

# Planning-zone groupings (Vicmap ZONE_CODE with trailing schedule digits
# stripped, e.g. GRZ10 -> GRZ). zoning_raw = growth + 0.45*standard - 0.35*restrictive.
ZONES_GROWTH = {"RGZ", "MUZ", "ACZ", "CCZ", "C1Z", "HCTZ", "CDZ", "B1Z", "B2Z", "B4Z", "PDZ"}
ZONES_STANDARD = {"GRZ", "R1Z", "R2Z", "R3Z", "TZ", "UGZ"}      # UGZ = growth-area precincts
ZONES_RESTRICT = {"NRZ", "LDRZ", "GWZ", "GWAZ", "RCZ", "FZ", "RLZ", "PCRZ"}

# Electricity-infrastructure sub-score (Phase 3). Transmission proximity leads:
# it enables larger-scale connection and isn't penalised for new growth areas
# that haven't built out local substations yet (chicken-and-egg). Capacity/
# headroom numbers are commercially sensitive, so these are proximity proxies.
INFRA_WEIGHTS = {
    "transmission": 0.45,    # closer to a high-voltage transmission line
    "substation": 0.30,      # closer to a transmission substation
    "density": 0.25,         # more substations within ~10 km (network depth)
}

# Default blend used for the headline "Overall" score (sliders override in UI).
DEFAULT_BLEND = {"live": 0.5, "dev": 0.5}

# Audience modes set a *starting* Liveability weight (slider stays adjustable).
MODE_PRESETS = {"live": 0.85, "balanced": 0.50, "invest": 0.20}

# Named one-click presets. Each sets the blend slider, which score colours the
# map, and the palette/mode. The manual slider still overrides afterwards.
# `live` = liveability weight 0-100; uses live_family scores when mode == "live".
PRESETS = [
    {"key": "family", "label": "Family First", "live": 85, "mode": "live", "colorBy": "live",
     "blurb": "Where can I raise my kids safely and comfortably? Safety + family lead."},
    {"key": "safety", "label": "Pure Safety", "live": 95, "mode": "live", "colorBy": "live",
     "blurb": "Maximum personal-safety focus — the calm end of the live/rent spectrum."},
    {"key": "balanced", "label": "Balanced Investor", "live": 45, "mode": "balanced", "colorBy": "overall",
     "blurb": "An all-round buy-and-hold that's still genuinely liveable."},
    {"key": "value", "label": "Value-Add / Developer", "live": 20, "mode": "invest", "colorBy": "dev",
     "blurb": "Surfaces redevelopment headroom and the growth corridors."},
]

# SA2s with fewer residents than this are employment precincts (airports,
# industrial estates): per-resident crime rates are meaningless there, so they
# fall back to LGA rates and wear an "Employment precinct" flag.
PRECINCT_POP_FLOOR = 500

# Letter grades. Applied to the *percentile* of the default-blend Overall, so
# they are relative tiers: A+ = top ~10% of Greater Melbourne, A = next 15%,
# B = next 20%, C = next 25%, D = bottom ~30%.
GRADE_CUTOFFS = [("A+", 90), ("A", 75), ("B", 55), ("C", 30), ("D", 0)]


def grade_for(score: float) -> str:
    for label, cut in GRADE_CUTOFFS:
        if score >= cut:
            return label
    return "D"
