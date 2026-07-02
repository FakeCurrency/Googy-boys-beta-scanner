"""CLI entry point: python -m engine.run [--geo-only]"""
import argparse

from . import build, geo


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the Melbourne Property dataset.")
    ap.add_argument("--geo-only", action="store_true", help="rebuild only the boundary GeoJSON")
    ap.add_argument("--force", action="store_true", help="re-download cached source files")
    args = ap.parse_args()
    if args.geo_only:
        geo.build_geojson(force=args.force)
    else:
        build.build()


if __name__ == "__main__":
    main()
