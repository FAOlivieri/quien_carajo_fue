#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pull street, park/plaza, and barrio (neighborhood) geometry for CABA
(Ciudad Autonoma de Buenos Aires) from OpenStreetMap via the Overpass API,
and convert it into plain GeoJSON files under data/osm_*.geojson.

CABA's OSM boundary relation is 3082668 -> Overpass area id 3603082668
(confirmed interactively: a query for the "Arenales" street inside this
area correctly returns its way segments).
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
CABA_AREA = 3603082668

QUERIES = {
    "osm_streets_raw.json": f"""
        [out:json][timeout:180];
        way["highway"~"^(motorway|trunk|primary|secondary|tertiary|unclassified|residential|living_street|pedestrian|footway|service|path)$"]["name"](area:{CABA_AREA});
        out geom;
    """,
    "osm_parks_raw.json": f"""
        [out:json][timeout:180];
        (
          way["leisure"~"^(park|garden)$"]["name"](area:{CABA_AREA});
          relation["leisure"~"^(park|garden)$"]["name"](area:{CABA_AREA});
          way["landuse"="recreation_ground"]["name"](area:{CABA_AREA});
          relation["landuse"="recreation_ground"]["name"](area:{CABA_AREA});
        );
        out geom;
    """,
    "osm_barrios_raw.json": f"""
        [out:json][timeout:180];
        relation["boundary"="administrative"]["admin_level"="9"]["name"](area:{CABA_AREA});
        out geom;
    """,
    "osm_caba_boundary_raw.json": """
        [out:json][timeout:180];
        relation(3082668);
        out geom;
    """,
}


def fetch(query: str) -> dict:
    data = ("data=" + query).encode("utf-8")
    req = urllib.request.Request(OVERPASS_URL, data=data, headers={
        "User-Agent": "buenos-aires-history-map-research/1.0 (ljubetic.lab@gmail.com)"
    })
    with urllib.request.urlopen(req, timeout=200) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    for fname, query in QUERIES.items():
        out_path = DATA / fname
        if out_path.exists() and "--force" not in sys.argv:
            print(f"skip {fname} (already exists, pass --force to refetch)")
            continue
        print(f"fetching {fname} ...")
        for attempt in range(3):
            try:
                result = fetch(query)
                break
            except Exception as e:
                print(f"  attempt {attempt+1} failed: {e}")
                time.sleep(5)
        else:
            print(f"  giving up on {fname}")
            continue
        out_path.write_text(json.dumps(result), encoding="utf-8")
        print(f"  saved {len(result.get('elements', []))} elements -> {out_path}")
        time.sleep(2)  # be polite to the shared Overpass instance


if __name__ == "__main__":
    main()
