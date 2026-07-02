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

# --- Geography -------------------------------------------------------------
# We score ABS SA2 areas ("suburbs") inside one Greater Capital City.
GCC_NAME = "Greater Melbourne"        # matches GCC_NAME21 in the ABS shapefile
STATE_NAME = "Victoria"

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
    "person_safety": 0.34,   # inverse rate of crimes AGAINST THE PERSON (assault, robbery, sexual)
    "seifa": 0.27,           # SEIFA IRSAD advantage
    "transport": 0.10,       # train-station access (nearest station distance)
    "owner_occ": 0.10,       # owner-occupier share -> stability
    "schools": 0.07,         # school access (nearest primary/secondary + density)
    "property_safety": 0.06, # inverse property-crime rate (secondary, transparent)
    "family_child": 0.06,    # share of children 0-14 (family-area signal)
}

# FAMILY weights (used in Live / Family-First mode): for a "raise my kid here"
# view, property crime barely matters while family/child + schools lead
# alongside personal safety. Computed as a second Liveability value (live_family).
LIVE_WEIGHTS_FAMILY = {
    "person_safety": 0.34,   # personal safety still the #1 driver
    "seifa": 0.19,           # socio-economic advantage (amenity proxy)
    "family_child": 0.16,    # children 0-14 share weighted up for the family lens
    "schools": 0.12,         # actual school access matters most in this lens
    "owner_occ": 0.09,       # settled owner-occupier base
    "transport": 0.07,       # train access still counts for school-run/commute
    "property_safety": 0.03, # property crime: minimal weight for a family-living view
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
    "detached_share": 0.20,  # low-density separate houses -> redevelopment headroom
    "zoning": 0.18,          # share of land zoned for growth (RGZ/MUZ/ACZ/C1Z/HCTZ...)
    "growth": 0.13,          # recent capital growth (VG 3yr CAGR, percentile)
    "infra": 0.13,           # electricity-network support (see INFRA_WEIGHTS)
    "station": 0.10,         # train-station proximity (activity-centre uplift signal)
    "yield": 0.08,           # gross rental yield (house rent vs house price)
    "rental_share": 0.07,    # rental share -> turnover / investor activity
    "low_density": 0.06,     # lower current density (persons/km2) -> headroom
    "heritage_free": 0.05,   # less Heritage Overlay coverage -> fewer constraints
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

# Letter grades from a 0-100 score.
GRADE_CUTOFFS = [("A+", 85), ("A", 72), ("B", 58), ("C", 42), ("D", 0)]


def grade_for(score: float) -> str:
    for label, cut in GRADE_CUTOFFS:
        if score >= cut:
            return label
    return "D"
