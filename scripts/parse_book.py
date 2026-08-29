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
OUT_CSV = ROOT / "data" / "entries.csv"
OUT_UNPARSED = ROOT / "data" / "unparsed_blocks.txt"

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
# A header segment: NAME (tipo). - the type is required to be a lowercase
# word/phrase so this can't be confused with an inline "(1900-1954)"
# birth-death parenthetical (those follow Title Case names, not ALL CAPS).
HEADER_SEG_RE = re.compile(
    r'([' + NAME_CHARS + r'][' + NAME_CHARS + r' ,\.\'º°/&\-]{0,90}?)'
    r'\s*\(([a-záéíóúñü][a-záéíóúñü \-/]{1,58})\)\.\s*'
)


SENTENCE_BOUNDARY_RE = re.compile(r'[.!?]\s+|\d\s+(?=[A-ZÁÉÍÓÚÑÜ])')


def find_headers(joined):
    """Find every header-shaped match in the block, trying only at the very
    start of the block or right after a sentence boundary (so an ALL-CAPS
    cross-reference inside a narrative paragraph can't be mistaken for the
    start of a new dictionary entry, and a name containing a date like
    "27-11-1893." can't be greedily absorbed starting mid-sentence)."""
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


def parse_block(page, joined):
    """Try to parse one joined block string into one or more (name, types,
    detail_text, see_also) rows. Returns (rows, ok) where ok=False means the
    block didn't match the dictionary-entry shape (kept for QA review)."""
    # Redirect entry: "NAME vease OTHER."
    m = VEASE_RE.match(joined)
    if m:
        name, target = m.group(1).strip(), m.group(2).strip()
        return [{
            "name": name, "feature_types": "", "detail_text": "",
            "see_also": target, "source_page": page,
        }], True

    header_matches = find_headers(joined)
    if not header_matches or header_matches[0].start() != 0:
        return [], False

    rows = group_headers_into_rows(page, joined, header_matches)
    return rows, True


def group_headers_into_rows(page, joined, header_matches):
    """Group consecutive same-name headers (e.g. "ARENALES (calle). ...
    ARENALES (plaza)." share one origin paragraph); a differently-named
    header starts a new group - this also covers two unrelated entries
    glued in one block with no blank line between them (e.g. "CAMPANA
    (calle). ... CAMPANA, JOAQUÍN (cantero central). ...")."""
    groups = []
    for m in header_matches:
        name = m.group(1).strip()
        ftype = m.group(2).strip()
        if groups and groups[-1]["name"] == name:
            groups[-1]["types"].append(ftype)
            groups[-1]["matches"].append(m)
        else:
            groups.append({"name": name, "types": [ftype], "matches": [m]})

    rows = []
    for i, g in enumerate(groups):
        detail_start = g["matches"][-1].end()
        detail_end = groups[i + 1]["matches"][0].start() if i + 1 < len(groups) else len(joined)
        rows.append({
            "name": g["name"], "feature_types": "; ".join(g["types"]),
            "detail_text": clean_text(joined[detail_start:detail_end]),
            "see_also": "", "source_page": page,
        })
    return rows


def resplit_embedded_headers(rows):
    """Cleanup pass: a same-named header that reappears after its own full
    narrative already ran (e.g. a barrio's own story, followed - with no
    blank line - by "NAME (avenida). NAME (plaza)." and a *different*,
    shared biography) looks identical to a normal grouped header while
    parsing and slips through as one oversized row. Re-scan every row's
    detail_text for header-shaped matches and split those off as their own
    row(s)."""
    out = []
    for r in rows:
        header_matches = find_headers(r["detail_text"])
        if not header_matches:
            out.append(r)
            continue
        lead = clean_text(r["detail_text"][:header_matches[0].start()])
        out.append({**r, "detail_text": lead})
        out.extend(group_headers_into_rows(r["source_page"], r["detail_text"], header_matches))
    return out


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

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["name", "feature_types", "detail_text", "see_also", "source_page"])
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
