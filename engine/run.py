"""CLI entry point: python -m engine.run [--city SLUG] [--geo-only]"""
import argparse
import sys

from . import build, config, geo


def main() -> None:
    ap = argparse.ArgumentParser(description="Build a city's Property dataset.")
    ap.add_argument("--city", default="melbourne", choices=sorted(config.CITIES),
                    help="which city profile to build (default: melbourne)")
    ap.add_argument("--geo-only", action="store_true", help="rebuild only the boundary GeoJSON")
    ap.add_argument("--force", action="store_true", help="re-download cached source files")
    args = ap.parse_args()
    config.set_city(args.city)
    if not config.CITY["ready"] and not args.geo_only:
        # Boundaries come from the national ABS shapefile, so --geo-only works
        # for any profile; a full build needs the state's source adapters.
        sys.exit(
            f"City '{args.city}' has a profile but its {config.STATE_CODE} source "
            "adapters (crime, prices, rents, zoning, transport) aren't built yet — "
            "see docs/AUSTRALIA.md. `--geo-only` works already."
        )
    if args.geo_only:
        geo.build_geojson(force=args.force)
    else:
        build.build()


if __name__ == "__main__":
    main()
