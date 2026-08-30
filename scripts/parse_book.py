#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Parse "Razon de los nombres.pdf" (extracted via `pdftotext -enc UTF-8 -layout`)
into a structured spreadsheet of Buenos Aires street/park/barrio names and the
story behind each name.

Input:  data/raw_text.txt
Output: data/entries.csv, data/unparsed_blocks.txt (for QA)
"""
import csv
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_TXT = ROOT / "data" / "raw_text.txt"
OUT_CSV = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "entries.csv"
OUT_UNPARSED = ROOT / "data" / "unparsed_blocks.txt"
OVERRIDES_CSV = ROOT / "data" / "overrides.csv"

# Running header/footer lines that repeat on every page - capture the page
# number as we go, then drop the line from the content stream.
FOOTER_RE = re.compile(r'^Origen y raz[oó]n de sus nombres\s+(\d{1,4})\s*$')
HEADER_RE = re.compile(r'^(\d{1,4})\s+Barrios, calles y plazas de la Ciudad de Buenos Aires\s*$')

# Stop parsing once we hit the appendix / ordinance transcription / bibliography
# at the back of the book (dictionary body ends well before this).
STOP_MARKERS = [
    "Ordenanza General de",
    "Nomenclatura de Calles",
]

NAME_CHARS = r"A-ZÁÉÍÓÚÑÜ0-9´’"
# A header segment: NAME (tipo). - tipo must be lowercase so this can't
# match an inline "(1900-1954)" birth-death parenthetical instead. Curly
# quotes are allowed in the name for quoted nicknames ("ERNESTO “CHE”").
# A few headers use a comma instead of the period after "(tipo)" (a book
# typo), so both are accepted.
HEADER_SEG_RE = re.compile(
    r'([' + NAME_CHARS + r'][' + NAME_CHARS + r' ,\.\'“”º°/&\-]{0,90}?)'
    r'\s*\(([a-záéíóúñü][a-záéíóúñü \-/]{1,58})\)[.,]\s*'
)


SENTENCE_BOUNDARY_RE = re.compile(r'[.!?]\s+|\d\s+(?=[A-ZÁÉÍÓÚÑÜ])')


def find_headers(joined):
    """Find every header-shaped match, only at block start or right after a
    sentence boundary - avoids matching an ALL-CAPS cross-reference or a
    date greedily absorbed mid-sentence."""
    boundaries = sorted({0, *(bm.end() for bm in SENTENCE_BOUNDARY_RE.finditer(joined))})
    out = []
    last_end = -1
    for b in boundaries:
        if b < last_end:
            continue  # falls inside a header span already matched
        m = HEADER_SEG_RE.match(joined, b)
        if m:
            out.append(m)
            last_end = m.end()
    return out
VEASE_RE = re.compile(
    r'^\s*([' + NAME_CHARS + r'][' + NAME_CHARS + r' ,\.\'º°/&\-]{0,90}?)'
    r'\s+[Vv][eé]ase\s+(.+?)\.?\s*$'
)
FOOTNOTE_RE = re.compile(r'(?<=[a-záéíóúñü\)])\.(\d{1,3})(?=\s|$)')

# A sentence belongs to the legal citation, not the story, if it mentions
# a legal instrument or reference number anywhere - citations often have a
# long lead-in before the actual keyword, so this isn't anchored to the
# sentence start.
LEGAL_KEYWORDS = (
    r'(?:Ordenanzas?|Ley(?:es)?|Decretos?(?:-Ordenanzas?)?|Resoluci[oó]n(?:es)?|'
    r'Disposici[oó]n(?:es)?|Planos?|BM|BO|BB\.MM)'
)
LEGAL_MENTION_RE = re.compile(rf'\b{LEGAL_KEYWORDS}\b|N[°º]', re.IGNORECASE)
# Exceptions: a biography can mention a law in passing while describing the
# person's career, and a definition can mention its subject's founding
# decree. Both are narrative regardless of what they go on to mention.
BIO_START_RE = re.compile(
    r"[A-ZÁÉÍÓÚÑÜ][\wÀ-ſ'.]*(?:\s+[A-Za-zÀ-ſ'.]+){0,5}\s*\([^)]{1,30}-[^)]{1,30}\)"
)
DEFINITION_START_RE = re.compile(r"^[A-ZÁÉÍÓÚÑÜ][^:]{0,80}:\s")


def is_narrative_start(s):
    return bool(BIO_START_RE.search(s) or DEFINITION_START_RE.match(s))


def is_legal_sentence(s):
    """Fallback only (see split_legal_and_narrative): a sentence with no
    legal keyword isn't necessarily narrative - it can be an aside inside a
    still-ongoing citation (a map's multi-clause title, a closing remark
    tied to the decree). Used only when nothing in the remaining text
    matches a recognized narrative opening."""
    if is_narrative_start(s):
        return False
    return bool(LEGAL_MENTION_RE.search(s))


SENTENCE_BREAK_RE = re.compile(r'(?<=[.!?])\s+')
# Title abbreviations ending in a period ("Dr.", "Gral.") that aren't a
# sentence end; a single-letter initial ("Juan A. Ambrosetti") is the same
# problem but checked separately since it can be any letter.
ABBREVIATIONS = {
    "dr", "dra", "sr", "sra", "srta", "gral", "cnel", "cte", "cmte", "cap",
    "ing", "arq", "prof", "mons", "fray", "pbro", "rvdo", "excmo", "av",
    "avda", "nro", "nros", "gob", "pdte", "vdo", "vda", "tte", "alte",
    "sgto", "sto", "sta", "dtor", "gdor",
}


def split_sentences(text):
    """Split into sentences, then merge back breaks that weren't a real
    sentence end: an abbreviation/initial ending in a period, or a period
    inside a still-open parenthetical."""
    parts = SENTENCE_BREAK_RE.split(text)
    merged = []
    for part in parts:
        if merged:
            m = re.search(r"(\w+)\.$", merged[-1])
            is_abbrev = m and (len(m.group(1)) == 1 and m.group(1).isupper() or m.group(1).lower() in ABBREVIATIONS)
            unbalanced_parens = merged[-1].count("(") > merged[-1].count(")")
            if is_abbrev or unbalanced_parens:
                merged[-1] = merged[-1] + " " + part
                continue
        merged.append(part)
    return merged


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def load_lines():
    """Read raw_text.txt, drop page header/footer lines, and return
    (content_lines, page_of_line) where page_of_line[i] is the page the
    i-th content line belongs to."""
    text = RAW_TXT.read_text(encoding="utf-8").replace("\x0c", "\n")
    lines = text.split("\n")
    content = []
    pages = []
    current_page = 1
    for line in lines:
        m = FOOTER_RE.match(line)
        if m:
            current_page = int(m.group(1))
            continue
        m = HEADER_RE.match(line)
        if m:
            current_page = int(m.group(1))
            continue
        content.append(line)
        pages.append(current_page)
    return content, pages


def find_stop_index(content):
    joined_start = None
    for i, line in enumerate(content):
        if line.strip() in STOP_MARKERS:
            # Confirm this is the real appendix divider (title-cased, short
            # standalone line), not a coincidental match inside prose.
            if i + 1 < len(content) and content[i + 1].strip() == "Nomenclatura de Calles":
                joined_start = i
                break
    return joined_start if joined_start is not None else len(content)


def dehyphenate_join(block_lines):
    """Join the physical lines of one block into a single logical string,
    fixing PDF line-wrap hyphenation (e.g. 'Ordenan-' + 'za' -> 'Ordenanza')."""
    out = ""
    for line in block_lines:
        line = line.strip()
        if not line:
            continue
        if out.endswith("-") and len(out) >= 2 and out[-2].isalpha() and out[-2].islower() and line[:1].islower():
            out = out[:-1] + line
        elif out:
            out = out + " " + line
        else:
            out = line
    return out


def clean_text(s: str) -> str:
    s = FOOTNOTE_RE.sub(r".", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def split_blocks(content, pages, stop_at):
    """Split the content lines (up to stop_at) into blocks separated by one
    or more blank lines. Each block keeps its own lines and the page number
    of its first non-blank line."""
    blocks = []
    cur_lines = []
    cur_page = None
    for i in range(stop_at):
        line = content[i]
        if line.strip() == "":
            if cur_lines:
                blocks.append((cur_page, cur_lines))
                cur_lines = []
                cur_page = None
            continue
        if cur_page is None:
            cur_page = pages[i]
        cur_lines.append(line)
    if cur_lines:
        blocks.append((cur_page, cur_lines))
    return blocks


def split_legal_and_narrative(span):
    """Split one header's trailing text into (its own legal citation, the
    narrative that follows it). Pure-citation spans return "" for the
    narrative."""
    span = span.strip()
    if not span:
        return "", ""
    sentences = split_sentences(span)
    i = 0
    while i < len(sentences) and is_legal_sentence(sentences[i].strip()):
        i += 1
    return " ".join(sentences[:i]).strip(), " ".join(sentences[i:]).strip()


def finalize_members(page, members, narrative):
    """Combine consecutive same-name members into one row each, keeping
    their own legal citation(s) but sharing the one narrative."""
    grouped = []
    for mem in members:
        if grouped and grouped[-1]["name"] == mem["name"]:
            grouped[-1]["types"].append(mem["type"])
            if mem["legal_ref"]:
                grouped[-1]["legal_refs"].append(mem["legal_ref"])
        else:
            grouped.append({
                "name": mem["name"], "types": [mem["type"]],
                "legal_refs": [mem["legal_ref"]] if mem["legal_ref"] else [],
            })
    return [{
        "name": g["name"], "feature_types": "; ".join(g["types"]),
        "legal_ref": clean_text(" ".join(g["legal_refs"])),
        "detail_text": clean_text(narrative),
        "see_also": "", "source_page": page,
    } for g in grouped]


def build_entries(page, joined, header_matches):
    """Walk a block's headers in order. The book lists one or more named
    locations, each with its own citation, then one shared narrative for
    all of them - so accumulate members until one's own trailing span
    contains actual narrative text, then share that story back across
    everything accumulated so far. A member whose own span is already a
    complete narrative (two same-named entries typeset back to back with
    unrelated stories) closes its group immediately instead of waiting."""
    pending = []
    rows = []
    for i, m in enumerate(header_matches):
        start = m.end()
        end = header_matches[i + 1].start() if i + 1 < len(header_matches) else len(joined)
        legal_ref, narrative = split_legal_and_narrative(joined[start:end])
        pending.append({"name": m.group(1).strip(), "type": m.group(2).strip(), "legal_ref": legal_ref})
        if narrative or i == len(header_matches) - 1:
            rows.extend(finalize_members(page, pending, narrative))
            pending = []
    return rows


def resplit_embedded_headers(rows):
    """A continuation merged across a stray page-boundary blank line can
    smuggle in more headers that build_entries never saw as part of the
    same block. Re-scan each row's detail_text for header-shaped matches
    and re-run the same shared-narrative logic on whatever's found."""
    out = []
    for r in rows:
        header_matches = find_headers(r["detail_text"])
        if not header_matches:
            out.append(r)
            continue
        lead = clean_text(r["detail_text"][:header_matches[0].start()])
        out.append({**r, "detail_text": lead})
        out.extend(build_entries(r["source_page"], r["detail_text"], header_matches))
    return out


def load_overrides():
    """A few entries have a legal citation that reads as narrative (or a
    narrative that reads as citation) in a way no lexical rule can tell
    apart from the ordinary case without breaking it elsewhere. Rather than
    special-case the parser, fix these by hand here - keyed by (name,
    feature_types) so a future re-parse still finds and fixes them."""
    if not OVERRIDES_CSV.exists():
        return {}
    with OVERRIDES_CSV.open(encoding="utf-8-sig", newline="") as f:
        return {(r["name"], r["feature_types"]): r for r in csv.DictReader(f)}


def apply_overrides(rows):
    overrides = load_overrides()
    if not overrides:
        return rows
    seen = set()
    for r in rows:
        key = (r["name"], r["feature_types"])
        if key in overrides:
            o = overrides[key]
            r["legal_ref"] = o["legal_ref"]
            r["detail_text"] = o["detail_text"]
            seen.add(key)
    stale = overrides.keys() - seen
    if stale:
        print(f"\nWARNING: {len(stale)} override(s) didn't match any parsed row"
              " (name/feature_types may have changed upstream):")
        for name, types in sorted(stale):
            print(f"  {name!r} / {types!r}")
    print(f"Overrides applied: {len(seen)}/{len(overrides)}")
    return rows


def parse_block(page, joined):
    """Try to parse one joined block string into one or more (name, types,
    legal_ref, detail_text, see_also) rows. Returns (rows, ok) where
    ok=False means the block didn't match the dictionary-entry shape (kept
    for QA review)."""
    # Redirect entry: "NAME vease OTHER."
    m = VEASE_RE.match(joined)
    if m:
        name, target = m.group(1).strip(), m.group(2).strip()
        return [{
            "name": name, "feature_types": "", "legal_ref": "", "detail_text": "",
            "see_also": target, "source_page": page,
        }], True

    header_matches = find_headers(joined)
    if not header_matches or header_matches[0].start() != 0:
        return [], False

    return build_entries(page, joined, header_matches), True


SECTION_LETTER_RE = re.compile(r'^[' + NAME_CHARS + r']$')
FOOTNOTE_BLOCK_RE = re.compile(r'^\d{1,3}\.\s')


def main():
    content, pages = load_lines()
    stop_at = find_stop_index(content)
    blocks = split_blocks(content, pages, stop_at)

    rows = []
    unparsed = []
    last_row_idx = None
    in_notes = False
    for page, block_lines in blocks:
        joined = dehyphenate_join(block_lines)
        joined = clean_text(joined)
        if not joined:
            continue

        if joined == "Bibliografía":
            break  # everything from here on is back matter

        if SECTION_LETTER_RE.match(joined):
            last_row_idx = None
            in_notes = False
            continue

        if joined.lower() == "notas":
            in_notes = True
            last_row_idx = None
            continue

        if in_notes:
            if FOOTNOTE_BLOCK_RE.match(joined):
                continue  # footnote text - not needed in the spreadsheet
            parsed_rows, ok = parse_block(page, joined)
            if not ok:
                # Wrapped continuation of a footnote (split across a page
                # boundary) - drop it rather than risk merging it into an
                # unrelated real entry.
                continue
            in_notes = False  # a real entry resumed
        else:
            parsed_rows, ok = parse_block(page, joined)

        if ok:
            rows.extend(parsed_rows)
            last_row_idx = len(rows) - 1
        elif last_row_idx is not None:
            # Continuation of the previous entry, split across a page/column
            # boundary by a stray blank line.
            rows[last_row_idx]["detail_text"] = clean_text(
                rows[last_row_idx]["detail_text"] + " " + joined
            )
        else:
            unparsed.append((page, joined))

    rows = resplit_embedded_headers(rows)
    rows = apply_overrides(rows)

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["name", "feature_types", "legal_ref", "detail_text", "see_also", "source_page"])
        w.writeheader()
        for r in rows:
            w.writerow(r)

    with OUT_UNPARSED.open("w", encoding="utf-8") as f:
        for page, text in unparsed:
            f.write(f"--- page {page} ---\n{text}\n\n")

    print(f"Blocks total: {len(blocks)}")
    print(f"Parsed rows:  {len(rows)}")
    print(f"Unparsed blocks: {len(unparsed)}")

    from collections import Counter
    type_counts = Counter()
    for r in rows:
        for t in r["feature_types"].split(";"):
            t = t.strip().lower()
            if t:
                type_counts[t] += 1
    print("\nTop feature types:")
    for t, c in type_counts.most_common(30):
        print(f"  {c:5d}  {t}")


if __name__ == "__main__":
    main()
