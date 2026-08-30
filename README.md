# ¿Por qué se llama así? — Mapa de Buenos Aires

An interactive map of Buenos Aires: click a street, park, plaza or barrio to
see the story behind its name. Sourced from Alberto Gabriel Piñeiro's
*Barrios, calles y plazas de la Ciudad de Buenos Aires. Origen y razón de sus
nombres* (Instituto Histórico de la Ciudad de Buenos Aires, 2008), matched
against live OpenStreetMap geometry.

## Files

- **`index.html`** — the map. Needs a local server or GitHub Pages to load
  its data (`fetch()` doesn't work over a plain `file://` double-click).
- **`data/entries.csv`** — the spreadsheet: one row per name, with
  `feature_types`, `legal_ref` (the decree/law citation), `detail_text` (the
  origin story), `see_also`, `source_page`.
- **`data/matched.geojson`** — `entries.csv` merged with OSM geometry; what
  the map actually loads.
- **`data/unmatched.csv`** — book entries not matched to OSM geometry.
- **`data/caba_boundary.geojson`** — CABA's city-limit polygon, used to mask
  the area outside the city and clamp panning/zoom to it.

## Run it locally

```bash
python -m http.server 8000
# open http://localhost:8000/
```

## Publish it

```bash
git remote add origin <your-repo-url>
git add . && git commit -m "Buenos Aires names map" && git push -u origin main
```

Then in the repo's Settings → Pages, set the source to `main`, root folder.

## The pipeline

```bash
pdftotext -enc UTF-8 -layout "Razon de los nombres.pdf" data/raw_text.txt
python scripts/parse_book.py       # -> data/entries.csv
python scripts/fetch_osm.py        # -> data/osm_*_raw.json (--force to refresh)
python scripts/match.py            # -> data/matched.geojson, data/unmatched.csv
python scripts/build_boundary.py   # -> data/caba_boundary.geojson
```

**`parse_book.py`**: the book lists one or more named locations, each with
its own legal citation, followed by one shared story for all of them (e.g.
a barrio and a paseo of a different name, both explained by the same
etymology). The parser accumulates locations until it hits an actual
narrative sentence, then shares that story back across all of them. ~2,800
entries recovered from the dictionary body (pp. ~26–450).

**`match.py`**: matches names to OSM geometry — normalizing accents/case,
un-inverting "Apellido, Nombre" ordering, stripping honorifics, handling
Argentine OSM's habit of folding the feature class into the name ("Avenida
Jujuy"), and a fuzzy fallback with several safety checks against attaching
the wrong person's biography to a place. Match rate: **~91%** (2,586
features from 2,729 geocodable rows).

## Known limitations

- A few long biographies still have a stray cross-reference folded into
  their text instead of their own row.
- Matching is name-based; a street name that recurs on unrelated,
  non-adjacent segments isn't disambiguated.
- `cantero central` (traffic median) entries are matched against the
  street itself, since OSM rarely maps the median as its own feature.
- `Cambios de nombres de calles.pdf`, also in this folder, could enrich
  "formerly known as" history in a future pass — not used here.

## Attribution

- Origin text: Alberto Gabriel Piñeiro, *Barrios, calles y plazas de la
  Ciudad de Buenos Aires. Origen y razón de sus nombres*, Instituto
  Histórico de la Ciudad de Buenos Aires, 2008.
- Map geometry: © [OpenStreetMap](https://www.openstreetmap.org/copyright)
  contributors, ODbL.
