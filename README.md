# ¿Por qué se llama así? — Mapa de Buenos Aires

An interactive map of Buenos Aires where clicking a street, park, plaza or
barrio shows the story behind its name — sourced from Alberto Gabriel
Piñeiro's *Barrios, calles y plazas de la Ciudad de Buenos Aires. Origen y
razón de sus nombres* (Instituto Histórico de la Ciudad de Buenos Aires,
2008), matched against live OpenStreetMap geometry.

## Live files

- **`index.html`** — the map (Leaflet + OpenStreetMap tiles). Open it through
  a local server (see below) or GitHub Pages — it won't load its data over a
  plain `file://` double-click, since `fetch()` is blocked there.
- **`data/entries.csv`** — the spreadsheet: every entry from the book, one
  row per name (`name`, `feature_types`, `detail_text`, `see_also`,
  `source_page`).
- **`data/matched.geojson`** — `entries.csv` merged with OSM geometry; what
  the map actually loads.
- **`data/unmatched.csv`** — book entries that couldn't be matched to OSM
  geometry (mostly small, obscure, or since-removed features — see below).
- **`data/caba_boundary.geojson`** — CABA's city-limit polygon (OSM relation
  3082668), used to mask everything outside the city and to clamp the map's
  pan/zoom so you can't scroll away from Buenos Aires or zoom out past
  "the whole city fits on screen."

## View it locally

```bash
python -m http.server 8000
# then open http://localhost:8000/
```

## Publish it

```bash
git remote add origin <your-repo-url>
git add .
git commit -m "Buenos Aires names map"
git push -u origin main
```

Then in the repo's Settings → Pages, set the source to the `main` branch,
root folder. The site will be live at `https://<you>.github.io/<repo>/`.

## How it was built (and how to re-run it)

Three scripts, run in order, each reading/writing files under `data/`:

1. **`scripts/parse_book.py`** — turns `data/raw_text.txt` (the book, via
   `pdftotext -enc UTF-8 -layout "Razon de los nombres.pdf" data/raw_text.txt`)
   into `data/entries.csv`. The book is a very regular dictionary: `NOMBRE
   (tipo). Referencia legal. Historia del nombre.` — the parser is a
   hand-written regex/state-machine parser (no per-page LLM calls needed),
   handling multi-line hyphenation, entries that share one origin story
   across several feature types (e.g. "ARENALES (calle)... ARENALES
   (plaza)..."), "véase X" cross-references, and the book's footnote
   sections. 2,802 rows recovered from the ~2,800-entry dictionary body
   (pages ~26–450); front matter, the historical essay, and the
   bibliography are intentionally excluded (they're prose, not entries).
2. **`scripts/fetch_osm.py`** — pulls every named street, park/plaza, and
   barrio (neighborhood) polygon inside CABA from the Overpass API (OSM
   relation 3082668) into `data/osm_*_raw.json`. Re-run with `--force` to
   refresh from OSM.
3. **`scripts/match.py`** — matches book entries to that OSM geometry by
   name (normalizing accents/case, un-inverting the book's "Apellido,
   Nombre" and "Apellido, Título Nombre" ordering, stripping honorific
   titles and rank prefixes, undoing Argentine OSM's habit of folding the
   feature class *into* the name - "Plaza Doctor Amadeo Sabattini", "Avenida
   Jujuy" - on both sides, an initials-aware token-overlap fuzzy match, and
   a narrow "unique surname" fallback that only fires when nothing about the
   book's own name or its biography text contradicts the one OSM feature
   that carries that surname), producing `data/matched.geojson` and
   `data/unmatched.csv`. A single row can produce more than one map feature
   when its types span more than one physical thing - e.g. "CHACABUCO" is
   both a calle and the parque that lends its name to the barrio, and
   "THAYS, CARLOS (jardín botánico; parque)" covers two *different* real
   parks (Jardín Botánico Carlos Thays and Parque Carlos Thays are
   separate OSM features, several km apart) - each type is matched with
   its own type-specific candidate so it can't just keep re-finding
   whichever one a generic search hits first, and results are only merged
   back down when two types genuinely resolve to the same feature (e.g.
   "calle; avenida" naming one street two ways). Current match rate:
   **~91%** (2,587 features from 2,724 geocodable rows - the rest are
   largely small/obscure `plazoleta`s, traffic-median `cantero central`s,
   and a few names that plainly aren't in OSM under any spelling I could
   find, like the `Rosales` avenue or the `Plaza Mariano Saavedra`). One
   more deliberate correctness-over-recall trade: a bare surname is never
   allowed to win a match - exact *or* fuzzy - when the book actually gives
   a first name, even if the OSM name it's being compared to has none of
   its own to contradict it with. "Saavedra, Mariano" used to silently grab
   "Parque Saavedra" this way (it cleans down to the bare surname alone,
   with no given name to check against) - which is actually Cornelio de
   Saavedra's park (his father, and a separate, correctly-matched book
   entry), not Mariano's. Mariano's plaza isn't in OSM under any name I
   could find, so this entry is now correctly unmatched instead of
   confidently wrong. One thing deliberately **not** done:
   fuzzy-matching a surname by character similarity (to catch spelling
   variants like "Riccheri"/"Ricchieri") - tested it, and it also happily
   matches "Córdoba"/"Córdova" and "Romero"/"Rovero", which are not the
   same people. Reverted; a few more unmatched rows is a better trade than
   occasionally attaching the wrong person's biography to a street.

Re-running the whole pipeline:

```bash
pdftotext -enc UTF-8 -layout "Razon de los nombres.pdf" data/raw_text.txt
python scripts/parse_book.py
python scripts/fetch_osm.py       # add --force to refresh from OSM
python scripts/match.py
python scripts/build_boundary.py  # rebuilds data/caba_boundary.geojson
```

## Known limitations

- A handful of very long biography entries (well under 1%) still have a
  stray cross-reference mention folded into their text instead of being
  split into their own row.
- Matching is name-based, not a full disambiguation of Buenos Aires streets
  that share a name across different, non-adjacent street segments — in
  rare cases a story could be attached to the wrong segment of a
  discontinuous street.
- `cantero central` (traffic median) entries are matched against the
  street layer (there's usually no separate OSM feature for the median
  itself), so their popup appears on the street, not a strip down its
  middle.
- `Cambios de nombres de calles.pdf`, also in this folder, looks like a
  useful source on renamed streets for a future pass, but isn't used here.

## Data & attribution

- Origin text: Alberto Gabriel Piñeiro, *Barrios, calles y plazas de la
  Ciudad de Buenos Aires. Origen y razón de sus nombres*, Instituto
  Histórico de la Ciudad de Buenos Aires, 2008.
- Map geometry: © [OpenStreetMap](https://www.openstreetmap.org/copyright)
  contributors, ODbL.
