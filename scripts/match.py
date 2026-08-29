#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Match book entries (data/entries.csv) against OSM geometry (data/osm_*_raw.json)
and produce data/matched.geojson + data/unmatched.csv.
"""
import csv
import json
import re
import unicodedata
from collections import defaultdict
from difflib import get_close_matches
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

ARTICLES = {"EL", "LA", "LOS", "LAS", "DEL", "DE"}

# Rank/profession honorifics that often prefix a person's name in the book's
# entry ("BUSTILLO, GENERAL JOSÉ MARÍA") but are usually dropped from the
# actual street name in OSM ("José María Bustillo").
HONORIFICS = {
    "DOCTOR", "DOCTORA", "DR", "GENERAL", "CORONEL", "COMODORO", "ALMIRANTE",
    "VICEALMIRANTE", "CONTRAALMIRANTE", "PRESIDENTE", "VICEPRESIDENTE",
    "INGENIERO", "INGENIERA", "ARQUITECTO", "ARQUITECTA", "PADRE", "MONSEÑOR",
    "SARGENTO", "MAYOR", "CAPITAN", "CAPITÁN", "TENIENTE", "SUBTENIENTE",
    "BRIGADIER", "DIPUTADO", "DIPUTADA", "SENADOR", "SENADORA", "PROFESOR",
    "PROFESORA", "MAESTRO", "MAESTRA", "ESCRIBANO", "COMISARIO", "INTENDENTE",
    "GOBERNADOR", "GOBERNADORA", "MECANICO", "MECÁNICO", "MILITAR",
    "NACIONAL", "PROVINCIAL", "JUEZ", "FRAY", "SOR", "ARZOBISPO", "OBISPO",
    "CARDENAL", "RABINO", "EMBAJADOR", "MINISTRO", "MINISTRA", "JEFE",
    "VICEJEFE", "MONSENOR", "VIRREY", "LIBERTADOR",
}

STREET_TYPES = {
    "calle", "avenida", "pasaje", "pasaje peatonal", "autopista", "paseo",
    "calle peatonal", "calle-paseo", "avenida-autopista", "avenida-boulevard",
    "avenida costanera", "avenida portuaria", "avenida y cantero central",
    "calle y plaza", "cantero", "cantero central", "canteros centrales",
    "encauzadores de tránsito", "puente peatonal", "vereda peatonal y jardín",
}
PARK_TYPES = {
    "plaza", "plazoleta", "parque", "espacio verde", "espacio público",
    "jardín", "jardines", "jardín botánico", "parque y centro deportivo",
    "parque deportivo municipal", "patio de recreación", "patio recreativo",
    "paseo peatonal", "plazoleta y paseo peatonal", "sector parque",
    "paseo/espigón",
    # bare "paseo" is ambiguous in the book - sometimes a paved street-like
    # promenade (also in STREET_TYPES), sometimes a park-like green paseo
    # (e.g. OSM's "Jardín Paseo de la Chacarita de los Colegiales", leisure=
    # park) - try both layers rather than guessing which one it is.
    "paseo",
}
BARRIO_TYPES = {"barrio"}


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def normalize(s: str) -> str:
    s = strip_accents(s).upper()
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def strip_leading_articles(s: str) -> str:
    words = s.split()
    while words and words[0] in ARTICLES:
        words = words[1:]
    return " ".join(words)


# Argentine OSM mappers routinely fold the feature class into the `name` tag
# itself ("Plaza Doctor Amadeo Sabattini", "Avenida Jujuy") rather than
# keeping it in a separate tag. Book entries never carry that word (or, for
# streets, sometimes do via our own AVENIDA/PASAJE/AUTOPISTA candidates) so
# OSM names need it strippable too, along with any honorific buried after it
# ("Doctor", "General", ...).
STREET_CLASS_WORDS = {"AVENIDA", "AV", "PASAJE", "PJE", "AUTOPISTA", "CALLE", "DIAGONAL"}
PARK_CLASS_WORDS = {
    "PLAZA", "PLAZOLETA", "PARQUE", "PASEO", "JARDIN", "JARDINES", "ESPACIO",
    "VERDE", "PATIO", "SECTOR",
}


def strip_leading_words(s: str, wordset) -> str:
    words = s.split()
    while words and words[0] in wordset:
        words = words[1:]
    return " ".join(words)


def clean_name(name: str, class_words) -> str:
    n = normalize(name)
    return strip_honorifics(strip_leading_articles(strip_leading_words(n, class_words)))


def index_key_variants(name: str, class_words):
    """All normalized forms of an OSM name worth indexing: as-is, with
    leading articles dropped, and aggressively cleaned (leading class word +
    honorifics anywhere stripped)."""
    n = normalize(name)
    variants = {n, strip_leading_articles(n)}
    cleaned = clean_name(name, class_words)
    if cleaned:
        variants.add(cleaned)
    return variants


def strip_honorifics(s: str) -> str:
    return " ".join(w for w in s.split() if w not in HONORIFICS)


def candidates_for_book_name(raw_name: str):
    cands = []
    base = normalize(raw_name)
    cands.append(base)
    left_n = ""
    if "," in raw_name:
        left, right = raw_name.split(",", 1)
        left_n, right_n = normalize(left), normalize(right)
        if right_n:
            cands.append(f"{right_n} {left_n}".strip())
        if left_n:
            cands.append(left_n)
        right_stripped = strip_honorifics(right_n)
        if right_stripped and right_stripped != right_n:
            cands.append(f"{right_stripped} {left_n}".strip())
    cands.append(strip_leading_articles(base))
    cands.append(strip_honorifics(base))
    # Argentine OSM mappers often fold the road class into the name tag
    # itself ("Avenida Jujuy" rather than just "Jujuy") - try that too.
    for prefix in ("AVENIDA", "PASAJE", "AUTOPISTA"):
        cands.append(f"{prefix} {base}")
        cands.append(f"{prefix} {strip_leading_articles(base)}")
    seen, out = set(), []
    for c in cands:
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    # Anchor is a *single* word required to survive in a fuzzy match (the
    # surname, or its last word for compound surnames like "Montes de Oca" -
    # kwords are individual tokens, so a multi-word anchor could never match).
    anchor_phrase = left_n or base
    anchor = anchor_phrase.split()[-1] if anchor_phrase else ""
    return out, anchor


def round_coords(coords, nd=5):
    return [round(c, nd) for c in coords]


def join_rings(segments):
    """Join way segments (lists of [lon,lat]) sharing endpoints into closed
    rings. Best-effort - used for park/barrio relation outer members."""
    segments = [list(seg) for seg in segments if len(seg) >= 2]
    rings = []
    while segments:
        ring = segments.pop(0)
        changed = True
        while changed and segments:
            changed = False
            for i, seg in enumerate(segments):
                if ring[-1] == seg[0]:
                    ring = ring + seg[1:]
                elif ring[-1] == seg[-1]:
                    ring = ring + list(reversed(seg))[1:]
                elif ring[0] == seg[-1]:
                    ring = seg[:-1] + ring
                elif ring[0] == seg[0]:
                    ring = list(reversed(seg))[:-1] + ring
                else:
                    continue
                segments.pop(i)
                changed = True
                break
        if ring[0] != ring[-1]:
            ring.append(ring[0])
        rings.append(ring)
    return rings


def load_json(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def build_street_index():
    raw = load_json("osm_streets_raw.json")
    idx = defaultdict(list)  # normalized name -> list of [[lon,lat],...]
    # registry: one entry per *real* OSM name (a multi-segment street shares
    # one entry across all its ways) - used to tell "this surname is
    # genuinely unique" apart from "this surname's *index key* is unique",
    # which isn't the same thing once one name expands into 2-3 keys.
    registry = {}
    for el in raw["elements"]:
        if el["type"] != "way" or "geometry" not in el:
            continue
        name = el.get("tags", {}).get("name")
        if not name:
            continue
        coords = [round_coords([pt["lon"], pt["lat"]]) for pt in el["geometry"]]
        if len(coords) < 2:
            continue
        for key in index_key_variants(name, STREET_CLASS_WORDS):
            idx[key].append(coords)
        rep = clean_name(name, STREET_CLASS_WORDS) or normalize(name)
        registry.setdefault(rep, set(rep.split()))
    return idx, registry


def build_park_index():
    raw = load_json("osm_parks_raw.json")
    idx = defaultdict(list)  # normalized name -> list of rings (each closed [[lon,lat],...])
    registry = {}
    for el in raw["elements"]:
        name = el.get("tags", {}).get("name")
        if not name:
            continue
        rings = []
        if el["type"] == "way" and "geometry" in el:
            coords = [round_coords([pt["lon"], pt["lat"]]) for pt in el["geometry"]]
            if len(coords) >= 3:
                if coords[0] != coords[-1]:
                    coords.append(coords[0])
                rings.append(coords)
        elif el["type"] == "relation" and "members" in el:
            outer_segs = []
            for mem in el["members"]:
                if mem.get("role") == "outer" and "geometry" in mem:
                    outer_segs.append([round_coords([pt["lon"], pt["lat"]]) for pt in mem["geometry"]])
            if outer_segs:
                rings.extend(join_rings(outer_segs))
        if not rings:
            continue
        for key in index_key_variants(name, PARK_CLASS_WORDS):
            idx[key].append(rings)
        rep = clean_name(name, PARK_CLASS_WORDS) or normalize(name)
        registry.setdefault(rep, set(rep.split()))
    return idx, registry


def build_barrio_index():
    raw = load_json("osm_barrios_raw.json")
    idx = {}
    registry = {}
    for el in raw["elements"]:
        if el["type"] != "relation":
            continue
        name = el.get("tags", {}).get("name")
        if not name:
            continue
        outer_segs = []
        for mem in el.get("members", []):
            if mem.get("role") == "outer" and "geometry" in mem:
                outer_segs.append([round_coords([pt["lon"], pt["lat"]]) for pt in mem["geometry"]])
        if not outer_segs:
            continue
        rings = join_rings(outer_segs)
        n = normalize(name)
        for key in {n, strip_leading_articles(n)}:
            idx[key] = rings
        registry.setdefault(n, set(n.split()))
    return idx, registry


def words_compatible(wa: str, wb: str) -> bool:
    """True if two words could denote the same name component - identical,
    or one is an initial of the other ("P" <-> "Pascual", from the book's
    "Tamborini, José P." vs OSM's "José Pascual Tamborini")."""
    if wa == wb:
        return True
    if len(wa) == 1 and wb.startswith(wa):
        return True
    if len(wb) == 1 and wa.startswith(wb):
        return True
    return False


def word_set_dice(a: set, b: set) -> float:
    """Dice coefficient over word sets, but treating an initial ("P") as a
    match for any full word it's the initial of ("Pascual") so abbreviated
    middle names don't tank an otherwise-correct match."""
    if not a or not b:
        return 0.0
    a_rest, b_rest, matched = set(a), set(b), 0
    for wa in list(a_rest):
        for wb in b_rest:
            if words_compatible(wa, wb):
                matched += 1
                a_rest.discard(wa)
                b_rest.discard(wb)
                break
    return 2 * matched / (len(a) + len(b))


NAME_BEFORE_PAREN_RE = re.compile(r'([A-ZÁÉÍÓÚÑÜ][\w.À-ſ]*(?:\s+[A-ZÁÉÍÓÚÑÜ][\w.À-ſ]*){0,3})\s*\(')


def story_name_words(detail_text: str):
    """The book's biography almost always reads '<legal citation>. <Full
    Name> (birth-death), profession...' - pull the capitalized run right
    before that first parenthesis as the person's actual name, to
    cross-check against a candidate OSM match (catches e.g. a book bio for
    "Leonardo Rosales" almost matching an unrelated "Vicente Pérez
    Rosales" street just because both end in "Rosales")."""
    m = NAME_BEFORE_PAREN_RE.search(detail_text)
    if not m:
        return set()
    return set(normalize(m.group(1)).split())


def find_match(candidates, anchor, index, index_keys_words, registry, cutoff=0.90, dice_cutoff=0.75, story_words=None):
    for c in candidates:
        if c in index:
            return c, "exact"
    # Token-set fuzzy fallback: best Dice-coefficient match across all
    # candidates, required to also contain the entry's most distinctive
    # word (its surname/first significant word) to avoid false positives.
    best_key, best_score, best_words = None, 0.0, None
    for c in candidates:
        words = set(c.split())
        if not words:
            continue
        for key, kwords in index_keys_words.items():
            if anchor and anchor not in kwords:
                continue
            score = word_set_dice(words, kwords)
            if score > best_score:
                best_score, best_key, best_words = score, key, words
    if best_key and best_score >= dice_cutoff:
        return best_key, "fuzzy"
    # A bare surname ("VIEYTES", no given name in the book entry at all) can
    # safely match a fuller OSM name ("Hipólito Vieytes") *if* that surname
    # is unique across the whole index - no other street/plaza shares it.
    # This is intentionally narrower than just "surname is unique": if the
    # book candidate carries other words (a given name) that contradict the
    # unique hit's remaining words ("Juan" vs the indexed "Manuel Gálvez"),
    # that's almost certainly a *different* person of the same surname, so
    # it's rejected rather than guessed - wrong-but-confident is worse than
    # unmatched for a project about getting the history right.
    #
    # Uniqueness is checked against `registry` (one entry per real OSM
    # name), not the expanded `index` keys - a single name like "Plaza
    # Intendente Francisco Seeber" legitimately produces 2-3 index key
    # variants (raw, cleaned, ...) that all contain "Seeber"; that's one
    # feature, not multiple, and must count as unique.
    if anchor:
        holders = [rep for rep, words in registry.items() if anchor in words]
        if len(holders) == 1:
            key = holders[0]
            key_extra = registry[key] - {anchor}
            # Use the fullest candidate (all given-name words present, none
            # truncated away) - checking a truncated candidate here would
            # let a name like "Gálvez, Juan" slip through on its bare-
            # surname candidate alone, defeating the whole safety check.
            # Honorifics are stripped here too: they were already stripped
            # from the OSM side (key_extra), so an untouched "Intendente"
            # left in cand_extra would never find anything to agree with
            # and wrongly read as a contradiction.
            cand_extra = set(strip_honorifics(candidates[0]).split()) - {anchor}
            header_ok = all(any(words_compatible(w, kw) for kw in key_extra) for w in cand_extra)
            # When the header itself is a bare surname (cand_extra empty,
            # so header_ok is only vacuously true), that's not real
            # evidence - fall back to the biography's own name mention, if
            # any, and require it to actually agree with the OSM name's
            # other words rather than just not-contradict them.
            if header_ok and cand_extra:
                return key, "fuzzy-unique-surname"
            if header_ok and not cand_extra:
                story_extra = (story_words or set()) - {anchor}
                if not story_extra or (key_extra and any(
                    any(words_compatible(w, kw) for kw in key_extra) for w in story_extra
                )):
                    return key, "fuzzy-unique-surname"
    # last resort: plain character-sequence fuzzy match (catches near-typos)
    close = get_close_matches(candidates[0], list(index.keys()), n=1, cutoff=cutoff)
    if close:
        return close[0], "fuzzy-char"
    return None, None


def main():
    rows = list(csv.DictReader(open(DATA / "entries.csv", encoding="utf-8-sig")))
    street_idx, street_registry = build_street_index()
    park_idx, park_registry = build_park_index()
    barrio_idx, barrio_registry = build_barrio_index()
    print(f"OSM street names: {len(street_registry)}, park/plaza names: {len(park_registry)}, barrios: {len(barrio_registry)}")

    street_words = {k: set(k.split()) for k in street_idx}
    park_words = {k: set(k.split()) for k in park_idx}
    barrio_words = {k: set(k.split()) for k in barrio_idx}

    features = []
    unmatched = []
    match_stats = defaultdict(int)

    for r in rows:
        if r["see_also"]:
            continue  # redirects carry no geometry of their own
        types = [t.strip().lower() for t in r["feature_types"].split(";") if t.strip()]
        if not types:
            continue
        candidates, anchor = candidates_for_book_name(r["name"])

        # A row can carry types spanning more than one physical feature (the
        # book's "CHACABUCO (calle; parque)" is both a street AND the park
        # that gave the surrounding barrio its name) - try every layer its
        # types touch, and emit one feature per layer that actually matches,
        # instead of stopping at the first hit and silently dropping the
        # rest.
        wants_street = any(t in STREET_TYPES or t not in (PARK_TYPES | BARRIO_TYPES) for t in types)
        wants_park = any(t in PARK_TYPES for t in types)
        wants_barrio = any(t in BARRIO_TYPES for t in types)

        story_words = story_name_words(r["detail_text"])

        row_matches = []
        if wants_street:
            key, method = find_match(candidates, anchor, street_idx, street_words, street_registry, story_words=story_words)
            if key:
                geom = {"type": "MultiLineString", "coordinates": street_idx[key]}
                row_matches.append(("street", method, geom))
        if wants_park:
            key, method = find_match(candidates, anchor, park_idx, park_words, park_registry, story_words=story_words)
            if key:
                coords = [ring for group in park_idx[key] for ring in group]
                geom = {"type": "MultiPolygon", "coordinates": [[ring] for ring in coords]}
                row_matches.append(("park", method, geom))
        if wants_barrio:
            key, method = find_match(candidates, anchor, barrio_idx, barrio_words, barrio_registry, cutoff=0.93, story_words=story_words)
            if key:
                geom = {"type": "MultiPolygon", "coordinates": [[ring] for ring in barrio_idx[key]]}
                row_matches.append(("barrio", method, geom))

        if row_matches:
            for kind, method, geom in row_matches:
                match_stats[f"{kind}:{method}"] += 1
                features.append({
                    "type": "Feature",
                    "geometry": geom,
                    "properties": {
                        "name": r["name"],
                        "feature_types": r["feature_types"],
                        "kind": kind,
                        "detail_text": r["detail_text"],
                        "source_page": r["source_page"],
                    },
                })
        else:
            match_stats["unmatched"] += 1
            unmatched.append(r)

    geojson = {"type": "FeatureCollection", "features": features}
    (DATA / "matched.geojson").write_text(json.dumps(geojson, ensure_ascii=False), encoding="utf-8")

    with open(DATA / "unmatched.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["name", "feature_types", "detail_text", "see_also", "source_page"])
        w.writeheader()
        for r in unmatched:
            w.writerow(r)

    geocodable_rows = sum(1 for r in rows if not r["see_also"] and r["feature_types"].strip())
    matched_rows = geocodable_rows - match_stats["unmatched"]
    print(f"\nGeocodable rows: {geocodable_rows}  (matched: {matched_rows}, unmatched: {match_stats['unmatched']})")
    print(f"Features written (some rows produce 2+, e.g. a calle *and* a parque sharing one name):")
    for k, v in sorted(match_stats.items(), key=lambda kv: -kv[1]):
        print(f"  {v:5d}  {k}")
    print(f"\nMatch rate: {matched_rows / geocodable_rows * 100:.1f}%")
    print(f"Wrote {len(features)} features -> data/matched.geojson")
    print(f"Wrote {len(unmatched)} unmatched rows -> data/unmatched.csv")


if __name__ == "__main__":
    main()
