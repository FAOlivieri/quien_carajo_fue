#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Build data/caba_boundary.geojson (a single Polygon/MultiPolygon of CABA's
city limits) from data/osm_caba_boundary_raw.json, and print its bounding
box - used by index.html to mask the area outside the city and to clamp
panning/zooming to it.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from match import join_rings, round_coords  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def main():
    raw = json.loads((DATA / "osm_caba_boundary_raw.json").read_text(encoding="utf-8"))
    rel = raw["elements"][0]
    outer_segs = [
        [round_coords([pt["lon"], pt["lat"]]) for pt in mem["geometry"]]
        for mem in rel["members"]
        if mem.get("role") == "outer" and "geometry" in mem
    ]
    rings = join_rings(outer_segs)
    # Keep only substantial rings (drop tiny slivers from any dangling ways).
    rings = [r for r in rings if len(r) >= 10]
    rings.sort(key=len, reverse=True)

    geojson = {
        "type": "Feature",
        "properties": {},
        "geometry": {
            "type": "MultiPolygon",
            "coordinates": [[r] for r in rings],
        },
    }
    (DATA / "caba_boundary.geojson").write_text(json.dumps(geojson), encoding="utf-8")

    lons = [pt[0] for r in rings for pt in r]
    lats = [pt[1] for r in rings for pt in r]
    bbox = [min(lons), min(lats), max(lons), max(lats)]
    print(f"Rings kept: {len(rings)} (sizes: {[len(r) for r in rings[:5]]}{'...' if len(rings) > 5 else ''})")
    print(f"Bounding box [minLon, minLat, maxLon, maxLat]: {bbox}")
    print("Wrote data/caba_boundary.geojson")


if __name__ == "__main__":
    main()
