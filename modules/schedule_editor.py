"""
SCHEDULE EDITOR -- the Schedule Text Editor step (find-and-replace in the PDF)

Everything for this step is in this one file:

  PART 1 -- THE ENGINE (process() and its helpers)
      Reads the instructions .xlsx and does the actual find-and-replace /
      delete in the PDF. Copied from the jennynt-LGH/Schedule-Editor GitHub
      repo (pdf_text_editor.py, latest commit "Debug output added"), with
      four LOCAL CHANGES marked in the code:
        - overlapping rows (one row's text inside another's, or the same
          row entered twice) are only applied once, so a line is never
          printed twice -- see _drop_overlapping_hits(). A delete row that
          overlaps a replacement is skipped for the same reason.
        - one line stays one field: when a replacement lands partway along
          a line (e.g. after "Glass: "), the WHOLE line, label included, is
          redrawn as one piece of text, so the PDF doesn't end up holding
          "Glass:" and "LHG026_4/4 (26) CN" as two separate fields -- see
          _plan_whole_line_rewrite().
        - original font, size and bold/italic kept: every part of a
          redrawn line keeps its OWN font, size, style and colour at its
          original position (a bold "9. DOSTAWA EXPORT - 2 quantity:" label
          stays bold, the italic " - LS kit form charge" after it stays
          italic); a replacement takes the style of the text it replaces.
          A character missing from the embedded font is taken from another
          embedded copy of the same font; only one that no copy has falls
          back to a built-in font of the same bold/italic style. Characters
          the original PDF had painted over are painted over again -- see
          _font_runs() and find_hidden_chars().
        - the preview images get every edited region drawn as a yellow box
          (the saved PDF is never touched by this).
      To update from GitHub later: replace PART 1 with the new
      pdf_text_editor.py code, then re-apply the four LOCAL CHANGES.

  PART 2 -- THE APP STEP (apply_text_replace())
      What steps.py calls. process() works on file paths, so this saves the
      working document to a temp file, runs process(), and hands back the
      edited document plus the results for app.py to show.

Can still be run on its own from the command line:
    python -m modules.schedule_editor INPUT.pdf INSTRUCTIONS.xlsx OUTPUT.pdf [--previews DIR]

INSTRUCTIONS SPREADSHEET FORMAT
-------------------------------
Find-and-replace / delete text inside a PDF, driven by an Excel
instructions file, while trying to keep the new text matching the
original font style, size, and position.

Instructions file format (first sheet):

    Table 1 (a row containing the header "Replace from this" starts it):
        Replace from this | to this | Only here | Skip this (don't apply to these) | Font size of new text | (anything else, ignored)
        <old text>         | <new>   | Pos no. 12 | page 9          | 12.08
        ...
        (a blank row ends the table)

    Columns are found by their header text, so their order doesn't matter.
    "Font size of new text" is OPTIONAL -- the column can be left out of
    the sheet entirely, or any cell in it left blank. Either way the new
    text keeps the size of the text it replaces.

    "Replace from this" can list several exact alternatives for the SAME
    "to this" text, separated by "|" -- e.g. "jonied onsite | joined
    onsiet" both becoming "joined onsite". This is for different known
    ways the same intended text can turn up broken (matching is always
    an exact literal substring, never a pattern/wildcard, so each
    alternative has to be spelled out), not for genuinely different
    replacements -- those still need their own separate row.

    Table 2 (a row containing "Delete these words from PDF" starts it),
    which optionally takes the SAME "Only here" / "Skip this" columns:
        Delete these words from PDF | Only here | Skip this (don't apply to these)
        <word or phrase to delete>   | Pos no. 3  |
        the whole line of "<text>"   |            | page 9
        ...
        (a blank row ends the table)

A delete row's phrase can either be:
    - a literal word/phrase that appears in the PDF -- only that text is
      removed, or
    - "the whole line of "<text>"" -- finds <text> in the PDF, then
      removes the ENTIRE line it's on (useful for removing a whole
      "U-value (W/m2K)= 1.39" style line by only naming part of it).

"Only here" and "Skip this (don't apply to these)" both accept the same
kind of value in either table: blank, "-", a page number/numbers ("page
9", "pages 3, 5"), or a POS number/numbers ("Pos no. 12", "POS #3, 7").
Whether a cell means pages or POS numbers is decided by whether the word
"pos" appears in it anywhere (any spacing/punctuation/case: "POS 12",
"pos.no 12", "POS #12" all count) -- otherwise the numbers in it are
treated as page numbers.
    - "Only here": the rule applies ONLY at the listed page(s)/POS
      number(s), and is skipped everywhere else in the document.
    - "Skip this (don't apply to these)": the rule applies everywhere
      EXCEPT the listed page(s)/POS number(s) (this column has also been
      called "Exception" / "Except for this" in older sheets -- all three
      headers are recognized).
A POS number refers to the "Pos.no N:" label the PDF itself prints next
to each item -- not a spreadsheet row number.

Anything that is NOT part of the two tables above is ignored by design,
so the spreadsheet can carry human-readable notes without confusing the
parser. Concretely:
    - Any row(s) above the "Replace from this" header row (e.g. a title,
      or a "Guide for users" row explaining how to fill the sheet in) are
      skipped, since scanning only starts once that exact header is found.
    - Each table ends at its first fully blank row. Anything below that
      blank row -- e.g. a closing reminder like "Before finalising, add a
      visual check of the whole page..." -- is never read as data, even
      if it's in the same column as the delete-phrase list above it.
This means notes/instructions meant for a *person* filling in the sheet
(or for whoever reviews the finished PDF) can sit right in the sheet
without needing to be removed before uploading it.
"""


import argparse
import os
import re
import sys
import tempfile

import fitz  # PyMuPDF
import openpyxl

# ═════════════════════════════════════════════════════════════════════════
# PART 1 -- THE ENGINE (from jennynt-LGH/Schedule-Editor, see top of file)
# ═════════════════════════════════════════════════════════════════════════


# ---------------------------------------------------------------------------
# Instructions parsing
# ---------------------------------------------------------------------------

def _norm(cell):
    return str(cell).strip().lower() if cell is not None else ""


def _expand_range_tokens(s):
    """Turn a comma-separated cell of numbers/ranges into a set of ints.

    Each comma-separated chunk is either a single number ("9") or a range
    ("3-7"). A chunk counts as a range whenever it contains a "-" AND at
    least two numbers -- so "POS 1-8", "1-3", "POS 1-POS 6", and "6-POS 9"
    all resolve the same way (only the digits and the dash matter; any
    words like "POS" in between are ignored). A lone number, or a chunk
    with a dash but only one number in it (e.g. a stray trailing "-"), is
    treated as a single value rather than a range. Whichever of the two
    numbers is larger becomes the range's end, so "8-3" behaves the same
    as "3-8".
    """
    nums = set()
    for chunk in s.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = re.findall(r"\d+", chunk)
        if not parts:
            continue
        if "-" in chunk and len(parts) >= 2:
            start, end = int(parts[0]), int(parts[-1])
            if start > end:
                start, end = end, start
            nums.update(range(start, end + 1))
        else:
            nums.update(int(p) for p in parts)
    return nums


def _parse_location_cell(raw):
    """Parse an "Only here" / "Except for this" style cell. Returns
    (pages, pos_numbers) -- a pair of sets of ints, at most one non-empty.

    Accepts blank, "-", a page reference ("page 9", "pages 3, 5",
    "pages 3-7", "page 1-page 6"), or a POS-number reference ("Pos no.
    12", "POS #3, 7", "POS 1-8", "POS 1-3, POS 6-8", "POS 1-POS 6").
    Ranges ("a-b") are expanded to every number in between, inclusive.
    Whether a cell means pages or POS numbers is decided by whether "pos"
    appears anywhere in the cell (case-insensitive, any spacing/
    punctuation); otherwise any numbers found are treated as page
    numbers. Matching is case-insensitive throughout.
    """
    if raw is None:
        return set(), set()
    s = str(raw).strip()
    if s == "" or s == "-":
        return set(), set()
    nums = _expand_range_tokens(s)
    if not nums:
        return set(), set()
    if "pos" in s.lower():
        return set(), nums
    return nums, set()


def parse_instructions(xlsx_path):
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    ws = wb.worksheets[0]
    rows = list(ws.iter_rows(values_only=True))

    replace_rules = []
    delete_phrases = []

    i, n = 0, len(rows)
    while i < n:
        row = rows[i]
        norm_row = [_norm(c) for c in row]

        if any("replace from this" in c for c in norm_row):
            col_from = next(j for j, c in enumerate(norm_row) if "replace from this" in c)
            col_to = next((j for j, c in enumerate(norm_row) if "to this" in c), col_from + 1)
            # "Only here" is the newer inclusion column; older sheets won't
            # have it at all, so col_only can legitimately stay None.
            col_only = next((j for j, c in enumerate(norm_row) if "only" in c), None)
            # "except"/"skip" covers all the header wordings seen so far:
            # the original "Exception", and the newer "Except for this" /
            # "Skip this (don't apply to these)".
            # The "Font size of new text" column is OPTIONAL: when the sheet
            # has no such header, col_size stays None and every replacement
            # keeps the size of the text it replaces (the same as leaving a
            # font size cell blank). Columns are only ever read by their
            # header -- never guessed by position -- so a sheet without this
            # column can't have some other column read as a font size.
            col_size = next((j for j, c in enumerate(norm_row) if "font size" in c), None)
            col_exc = next(
                (j for j, c in enumerate(norm_row) if "except" in c or "skip" in c),
                (col_only + 1) if col_only is not None else col_from + 2,
            )
            # The guessed fallback above must never land on a column that
            # already has a known job (e.g. "Only here" followed straight by
            # "Font size" with no Skip column) -- a font size like 12.08
            # would otherwise be read as "skip pages 12 and 8".
            if col_exc in (col_from, col_to, col_only, col_size):
                col_exc = None
            i += 1
            while i < n:
                r = rows[i]
                old = r[col_from] if col_from < len(r) else None
                if old is None or str(old).strip() == "":
                    break
                new = r[col_to] if col_to < len(r) else None
                only_raw = r[col_only] if (col_only is not None and col_only < len(r)) else None
                exc_raw = r[col_exc] if (col_exc is not None and col_exc < len(r)) else None
                size_raw = r[col_size] if (col_size is not None and col_size < len(r)) else None

                only_pages, only_pos = _parse_location_cell(only_raw)
                except_pages, except_pos = _parse_location_cell(exc_raw)

                size = None
                try:
                    if size_raw not in (None, ""):
                        size = float(size_raw)
                except (TypeError, ValueError):
                    size = None
                if size is not None and size <= 0:
                    size = None  # 0 / negative means "not set", not invisible text

                # "Replace from this" can list several exact alternatives,
                # separated by "|", that should all become the SAME "to
                # this" text -- e.g. two different known-broken spellings
                # of the same word (a PDF-generator glyph-ordering defect
                # can scramble a word differently in different contexts)
                # that both need to end up as the same correct text.
                # Since matching is always an exact literal substring (no
                # wildcards), each alternative becomes its own internal
                # rule here, but they're written as one row for the user.
                old_alternatives = [alt.strip() for alt in str(old).split("|")]
                old_alternatives = [alt for alt in old_alternatives if alt]
                row_group_id = i  # shared by every alternative from this one row

                for old_alt in old_alternatives:
                    replace_rules.append({
                        "old": old_alt,
                        "new": "" if new is None else str(new).strip(),
                        "only_pages": only_pages,
                        "only_pos": only_pos,
                        "except_pages": except_pages,
                        "except_pos": except_pos,
                        "size": size,
                        "row_group_id": row_group_id,
                    })
                i += 1
            continue

        if any("delete these words" in c for c in norm_row):
            col_phrase = next(j for j, c in enumerate(norm_row) if "delete these words" in c)
            col_only = next((j for j, c in enumerate(norm_row) if "only" in c), None)
            col_skip = next((j for j, c in enumerate(norm_row) if "except" in c or "skip" in c), None)
            i += 1
            while i < n:
                r = rows[i]
                phrase = r[col_phrase] if col_phrase < len(r) else None
                if phrase is None or str(phrase).strip() == "":
                    break
                only_raw = r[col_only] if (col_only is not None and col_only < len(r)) else None
                skip_raw = r[col_skip] if (col_skip is not None and col_skip < len(r)) else None
                only_pages, only_pos = _parse_location_cell(only_raw)
                except_pages, except_pos = _parse_location_cell(skip_raw)
                delete_phrases.append({
                    "phrase": str(phrase).strip(),
                    "only_pages": only_pages,
                    "only_pos": only_pos,
                    "except_pages": except_pages,
                    "except_pos": except_pos,
                })
                i += 1
            continue

        i += 1

    return replace_rules, delete_phrases


# ---------------------------------------------------------------------------
# PDF helpers
# ---------------------------------------------------------------------------

def get_spans(page):
    """Extract every text span on the page, using PyMuPDF's "rawdict" mode
    so each span carries its individual characters' bounding boxes (not
    just the span's own overall bbox). This lets us locate a substring's
    exact rectangle directly from the page's own extracted text, instead
    of re-querying the page with page.search_for() -- which, empirically,
    can occasionally fail to find text that unambiguously exists (this
    surfaced on one particular summary line where search_for() silently
    returned no match at all for a phrase clearly present in the page's
    own text). Searching within the extracted text we already trust
    removes that failure mode entirely.

    Each span also gets a "line_idx" -- a per-page counter identifying
    which of PyMuPDF's own "line" groupings it belongs to -- so spans
    that make up one continuous printed line can be found and searched
    together (see build_lines / search_text_in_lines), even when that
    line happens to be split into several spans. It also gets a
    "block_idx", identifying which of PyMuPDF's own "block" groupings
    (a level above "line") it belongs to -- some PDF generators draw a
    whole multi-line attribute paragraph as one shared block/text object,
    and this lets code elsewhere detect "these two edits fall in the same
    underlying block" to avoid a redaction-corruption failure mode that's
    specific to editing such a block more than once.
    """
    spans = []
    d = page.get_text("rawdict")
    line_idx = 0
    for block_idx, block in enumerate(d["blocks"]):
        if block.get("type") != 0:  # skip image blocks
            continue
        for line in block.get("lines", []):
            line_bbox = line["bbox"]
            for span in line["spans"]:
                span = dict(span)
                span["line_bbox"] = line_bbox
                span["line_idx"] = line_idx
                span["block_idx"] = block_idx
                chars = span.get("chars", [])
                span["text"] = "".join(c["c"] for c in chars)
                span["_chars"] = chars
                spans.append(span)
            line_idx += 1
    return spans


def build_lines(spans):
    """Group spans back into the printed lines PyMuPDF originally split
    them from (via the line_idx get_spans tagged them with), and build
    one continuous text string per line by concatenating that line's
    spans left-to-right -- along with a per-character map back to
    (span, local_char_index).

    This exists because a single printed line isn't always one span: a
    PDF generator will sometimes need a different embedded font for just
    one character in the middle of an otherwise plain line -- most often
    a diacritic (e.g. "osłonek") missing from the main subset font --
    which silently splits that line into 2 or 3 spans even though it
    looks completely uniform. Searching only within individual spans (as
    a plain page-text search effectively does) will never find a phrase
    that happens to cross such a split; searching each line's full
    reassembled text does.
    """
    by_line = {}
    for span in spans:
        by_line.setdefault(span["line_idx"], []).append(span)

    lines = []
    for line_spans in by_line.values():
        line_spans.sort(key=lambda s: s["bbox"][0])
        text_parts = []
        char_owners = []  # parallel to the concatenated text below
        for span in line_spans:
            for local_idx in range(len(span["_chars"])):
                text_parts.append(span["_chars"][local_idx]["c"])
                char_owners.append((span, local_idx))
        lines.append({"text": "".join(text_parts), "char_owners": char_owners})
    return lines


def search_text_in_lines(lines, text):
    """Find every exact, case-sensitive occurrence of `text` within each
    line's full reassembled text (see build_lines) -- so a match can span
    more than one underlying PDF span/font-run. Returns a list of dicts:
    rect (built from the matched characters' own bounding boxes, across
    however many spans they came from), the "primary" span the match
    STARTS in (used for the replacement's font/size/baseline -- the
    common case is a match entirely inside one span anyway, where this
    is simply that span), the line, and the match's [start, end) character
    offsets within that line's text (used later to bound how far a
    suffix can be reflowed without overrunning a different, later hit on
    the same line)."""
    results = []
    for line in lines:
        line_text = line["text"]
        owners = line["char_owners"]
        start = 0
        while True:
            idx = line_text.find(text, start)
            if idx == -1:
                break
            end = idx + len(text)
            matched_owners = owners[idx:end]
            if matched_owners:
                boxes = [owners[i][0]["_chars"][owners[i][1]]["bbox"] for i in range(idx, end)]
                x0 = min(b[0] for b in boxes)
                y0 = min(b[1] for b in boxes)
                x1 = max(b[2] for b in boxes)
                y1 = max(b[3] for b in boxes)
                results.append({
                    "rect": fitz.Rect(x0, y0, x1, y1),
                    "span": matched_owners[0][0],
                    "line": line,
                    "start": idx,
                    "end": end,
                })
            start = end
    return results


_POS_LABEL_RE = re.compile(r"pos\.?\s*no\.?\s*(\d+)", re.IGNORECASE)


def build_pos_blocks(spans, page_bottom):
    """Each item in the schedule PDF is introduced by a "Pos.no N:" label.
    This finds every such label on the page and works out the vertical
    range of the page that belongs to each one (from its own label down
    to the start of the next one, or the bottom of the page for the last
    item) -- so a match's y-position can be mapped back to "which POS
    number is this text part of". Returns a list of (y_start, y_end,
    pos_number) tuples.
    """
    labels = []
    for span in spans:
        m = _POS_LABEL_RE.search(span["text"])
        if m:
            labels.append((span["bbox"][1], int(m.group(1))))
    labels.sort(key=lambda t: t[0])
    blocks = []
    for idx, (y0, pos_num) in enumerate(labels):
        y_end = labels[idx + 1][0] if idx + 1 < len(labels) else page_bottom
        blocks.append((y0, y_end, pos_num))
    return blocks


def pos_number_for_rect(pos_blocks, rect):
    """Which POS number's block a given match rectangle falls into, or
    None if the page has no recognizable "Pos.no N:" labels at all."""
    cy = (rect.y0 + rect.y1) / 2
    for y_start, y_end, pos_num in pos_blocks:
        if y_start <= cy < y_end:
            return pos_num
    return None


_WHOLE_LINE_RE = re.compile(r"whole line(?:s)?\s+of\b\s*(.*)", re.IGNORECASE)


def parse_delete_phrase(raw):
    """A "delete" row is normally a literal phrase to remove. But it can
    also be written as an instruction FOR A PERSON describing what to
    remove, e.g. 'the whole line of "U-value (W/m2K)"' -- that sentence
    itself will never appear in the PDF, so searching for it literally
    would silently find and delete nothing.

    Detect that pattern and return (search_text, whole_line) where
    search_text is the actual text to locate on the page, and whole_line
    means: once found, remove the ENTIRE line it's on (not just the
    matched substring). Anything that doesn't match the pattern is
    treated as a plain literal phrase, unchanged from before.
    """
    s = raw.strip()
    m = _WHOLE_LINE_RE.search(s)
    if m:
        inner = m.group(1).strip()
        inner = inner.strip("\"'“”‘’").strip()
        inner = inner.rstrip(".").strip()
        if inner:
            return inner, True
    return s, False


def find_containing_span(spans, rect):
    cy = (rect.y0 + rect.y1) / 2
    for span in spans:
        bx0, by0, bx1, by1 = span["bbox"]
        if by0 - 1 <= cy <= by1 + 1 and bx0 - 1 <= rect.x0 and rect.x1 <= bx1 + 1:
            return span
    return None


def extract_all_fonts(doc, workdir):
    """Extract every embedded font in the document to disk, keyed by base
    font name (subset prefix like 'ABCDEF+' stripped) -- as a LIST of
    every distinct subset found under that name, not just one.

    PDF generators very commonly re-subset the same font independently
    per page (or per text block), each subset embedding only the glyphs
    THAT one instance actually uses. Two pages' "Arial", for example, can
    be two genuinely different files with different glyph coverage --
    one might include a Polish diacritic the other doesn't. Keeping only
    the last one seen (as an earlier version of this function did) meant
    a later page's lookup of "Arial" could silently get a DIFFERENT,
    incomplete subset that's missing a character the current text
    actually needs, even though some other subset earlier in the
    document has it. Keeping every subset and letting the caller check
    actual glyph coverage (see resolve_font_for_text) avoids that.
    """
    font_files = {}
    seen = set()
    for page in doc:
        for f in page.get_fonts(full=True):
            xref = f[0]
            if xref in seen:
                continue
            seen.add(xref)
            base_name = f[3]
            if "+" in base_name:
                base_name = base_name.split("+", 1)[1]
            try:
                info = doc.extract_font(xref)
            except Exception:
                continue
            ext, buf = info[1], info[3]
            if not buf:
                continue
            path = os.path.join(workdir, f"{base_name}.{xref}.{ext or 'ttf'}")
            with open(path, "wb") as fh:
                fh.write(buf)
            font_files.setdefault(base_name, []).append(path)
    return font_files


def find_overlap_warnings(page, inserted_specs, cover_rects):
    """Automated version of "add a visual check of the whole page (not
    just the edited spot) to catch any unintended text overlaps".

    inserted_specs: list of (x, y, text) tuples for text we just inserted
    on this page.
    cover_rects: the white-out boxes drawn on this page -- used to ignore
    the old text we deliberately hid underneath them (that text is still
    technically present/extractable, by design -- see the module
    docstring -- so it would otherwise "overlap" its own replacement on
    every single edit and drown out real warnings).

    Re-reads the page's text after insertion and flags any case where one
    of *our* inserted spans overlaps a bounding box of some other,
    genuinely still-visible span on the page -- the exact failure pattern
    that previously caused things like a stray leftover "-" bleeding into
    replacement text. Returns a list of human-readable warning strings
    (empty if nothing looks wrong).
    """
    spans = get_spans(page)
    inserted_spans, other_spans = [], []
    for span in spans:
        ox, oy = span["origin"]
        is_ours = any(
            abs(ox - ix) < 1.0 and abs(oy - iy) < 1.0
            for ix, iy, _ in inserted_specs
        )
        (inserted_spans if is_ours else other_spans).append(span)

    warnings = []
    for ins in inserted_spans:
        if not ins["text"].strip():
            continue  # a blank space can't visibly overlap anything
        ins_rect = fitz.Rect(ins["bbox"])
        for other in other_spans:
            other_rect = fitz.Rect(other["bbox"])
            inter = ins_rect & other_rect
            if inter.is_empty:
                continue
            inter_area = inter.width * inter.height
            if inter_area < 1.0:
                continue
            # The old/other text can perfectly legitimately share space
            # with our new text -- that's exactly what happens when we
            # white-out old text and write new text in its place. Only
            # the OVERLAPPING REGION itself needs to be painted over for
            # this to be invisible in the final render; the rest of that
            # other span (e.g. an untouched "Handle:" label before it)
            # is irrelevant. So check coverage of the intersection, not
            # of the whole other span.
            covered = any(
                (inter & cover).width * (inter & cover).height >= 0.9 * inter_area
                for cover in cover_rects
            )
            if covered:
                continue
            warnings.append(
                f"'{ins['text'].strip()}' may overlap "
                f"'{other['text'].strip()}' -- check this page closely"
            )
    return warnings


def _base14_for_style(name):
    """Pick a built-in base-14 font (full standard glyph coverage) that
    matches the bold/italic style implied by an original font's name."""
    lname = (name or "").lower()
    if "bold" in lname and ("italic" in lname or "oblique" in lname):
        return "hebi"
    if "bold" in lname:
        return "hebo"
    if "italic" in lname or "oblique" in lname:
        return "heit"
    return "helv"


def resolve_font_for_text(span_font_name, font_files, text):
    """Return (fontname, fontfile_or_None) for insert_text(), specifically
    chosen so the returned font actually covers every character in `text`
    -- not just assumed to, based on name alone.

    font_files maps a base font name to a LIST of every distinct embedded
    subset found under that name anywhere in the document (see
    extract_all_fonts for why there can be more than one). Different
    subsets of the "same" font can have different glyph coverage, so this
    tries each one against the actual text being inserted here and uses
    the first that works, rather than an arbitrary one that happens to be
    missing a character this particular insertion needs. Falls back to a
    built-in base-14 font (matching bold/italic style) only if none of
    the embedded subsets found under this name cover the text either.
    """
    name = span_font_name or ""
    if "+" in name:
        name = name.split("+", 1)[1]
    for candidate_path in font_files.get(name, []):
        if font_covers_text(name, candidate_path, text):
            return name, candidate_path
    return _base14_for_style(name), None


def font_covers_text(fontkey, fontfile, text):
    """PDFs typically only embed the exact glyphs the original document
    used. A replacement/inserted phrase can easily need a character the
    original never did (e.g. a digit, an accent, a punctuation mark) --
    inserting with a font missing that glyph renders as a blank box
    ("tofu") instead of the character. Check every non-space character in
    `text` actually exists in the chosen font before using it."""
    try:
        font_obj = fitz.Font(fontfile=fontfile) if fontfile else fitz.Font(fontkey)
    except Exception:
        return False
    for ch in text:
        if ch.isspace():
            continue
        if not font_obj.has_glyph(ord(ch)):
            return False
    return True


def _job_width(job):
    """Rendered width of an insert job -- precomputed for the run-based jobs
    from _plan_whole_line_rewrite, measured for the single-font ones."""
    if job.get("width") is not None:
        return job["width"]
    font_obj = fitz.Font(fontfile=job["fontfile"]) if job["fontfile"] else fitz.Font(job["fontkey"])
    return font_obj.text_length(job["text"], fontsize=job["size"])


def resolve_line_overlaps(insert_jobs, cover_rects):
    """When two different replacements land on the same visual line close
    together (e.g. a short bold label right next to a longer description
    on the same row), a replacement text that's LONGER than the text it
    replaced can run into the start of the next insertion and overlap it.

    This measures each insertion's actual rendered width (using the real
    font/size it will be drawn with, not a guess), and for any two
    insertions on the same line where the first would run past where the
    second starts, shifts the second (and anything after it on that line,
    cascading) to the right by exactly the overflow amount -- then widens
    that insertion's own cover rectangle to match its new extent, so the
    now-larger gap is still painted white rather than showing old text.

    This is a backstop for cases the proactive line-flow positioning in
    process() doesn't cover (e.g. a fallback/standalone insertion whose
    baseline happens to coincide with another line). It only nudges
    something when there's genuine overlap -- not a plain "settle any two
    insertions on any line a bit apart", since the calling code has
    already positioned suffix-linked hits exactly flush with no gap on
    purpose, and adding one back in here would silently reintroduce the
    "unwanted extra space" this whole approach exists to avoid.
    """
    from collections import defaultdict

    lines = defaultdict(list)
    for job in insert_jobs:
        # Group by baseline, tolerating tiny rounding differences between
        # jobs that are genuinely on the same printed line.
        lines[round(job["y"])].append(job)

    epsilon = 0.05  # floating-point safety margin only, not a visible gap
    for jobs in lines.values():
        if len(jobs) < 2:
            continue
        jobs.sort(key=lambda j: j["x"])
        for i in range(len(jobs) - 1):
            cur = jobs[i]
            cur_end = cur["x"] + _job_width(cur)
            nxt = jobs[i + 1]
            if cur_end <= nxt["x"] + epsilon:
                continue
            shift = cur_end - nxt["x"]
            nxt["x"] += shift
            nxt_width = _job_width(nxt)
            cover = cover_rects[nxt["cover_idx"]]
            cover.x1 = max(cover.x1, nxt["x"] + nxt_width)



def find_near_miss_texts(spans, old):
    """A replace rule only matches text that is EXACTLY the same as `old`.
    If the PDF has a slightly different version of that text nearby (an
    extra word, a typo, different spacing -- e.g. the rule says "Aluclad
    Timber 68 PEFC Jointed Pine" but this page actually says "Aluclad
    Timber 68x80 PEFC Jointed Pine"), the rule silently skips it with no
    error at all, which is easy to miss.

    `old` is usually only PART of a span's text (e.g. it sits after a
    "System: " label), so we can't assume it starts at position 0 of the
    span. Instead: take a long leading chunk of `old` and check whether
    that chunk shows up anywhere inside a span's text that ISN'T an exact
    match -- a strong sign a near-duplicate slipped through. Returns the
    list of distinct near-miss texts found.
    """
    chunk_len = max(10, int(len(old) * 0.4))
    chunk = old[:chunk_len].lower()
    seen = set()
    variants = []
    for span in spans:
        text = span["text"].strip()
        if not text or old in text:
            continue
        if chunk in text.lower() and text not in seen:
            seen.add(text)
            variants.append(text)
    return variants


def _left_neighbours(line, all_lines, busy_line_ids):
    """Lines that continue `line` to its LEFT on the same printed row: same
    baseline, ending right where the next one starts (no more than about a
    space apart). Some PDFs store e.g. "Alu-clad colour:" and "RAL extra"
    as two separate lines even though they print as one. Their style
    doesn't matter -- each piece is redrawn in its own font (see
    _plan_whole_line_rewrite).

    Returns (list_of_lines_left_to_right, joiner_after_each) -- joiner is
    " " where there's a visible gap and no space character already, so the
    redrawn text still reads "Alu-clad colour: RAL extra". Lines that have
    their own replacements (busy_line_ids) are never pulled in.
    """
    owners = line["char_owners"]
    first_char = owners[0][0]["_chars"][owners[0][1]]
    base_y = first_char["origin"][1]
    size = owners[0][0]["size"]
    left_x = first_char["bbox"][0]
    left_text = line["text"]
    found_lines, joiners = [], []
    used = {id(line)}
    while True:
        found = None
        for cand in all_lines:
            co = cand["char_owners"]
            if not co or id(cand) in used or id(cand) in busy_line_ids:
                continue
            last_char = co[-1][0]["_chars"][co[-1][1]]
            if abs(last_char["origin"][1] - base_y) > 0.5:
                continue
            gap = left_x - last_char["bbox"][2]
            if -0.5 <= gap <= 0.6 * size:
                found = (cand, gap)
                break
        if found is None:
            break
        cand, gap = found
        used.add(id(cand))
        joiner = ""
        if gap > 0.15 * size and not cand["text"][-1:].isspace() and not left_text[:1].isspace():
            joiner = " "
        found_lines.insert(0, cand)
        joiners.insert(0, joiner)
        left_x = cand["char_owners"][0][0]["_chars"][cand["char_owners"][0][1]]["bbox"][0]
        left_text = cand["text"]
    return found_lines, joiners


# ---------------------------------------------------------------------------
# Keeping the original font, size and bold/italic style
# ---------------------------------------------------------------------------

_FONT_CACHE = {}


def _font_obj(key_or_path, is_file):
    """fitz.Font objects are slow-ish to build -- make each one once."""
    ck = (key_or_path, is_file)
    if ck not in _FONT_CACHE:
        try:
            _FONT_CACHE[ck] = fitz.Font(fontfile=key_or_path) if is_file else fitz.Font(key_or_path)
        except Exception:
            _FONT_CACHE[ck] = None
    return _FONT_CACHE[ck]


def _base14_for_span(span):
    """Built-in fallback font matching a span's bold/italic style, judged
    by the font's name AND PyMuPDF's style flags (bit 1 = italic, bit 4 =
    bold) -- some fonts' names don't say "Bold"/"Italic" at all."""
    name = (span.get("font") or "").lower()
    flags = span.get("flags", 0) or 0
    bold = "bold" in name or "black" in name or "heavy" in name or bool(flags & 16)
    italic = "italic" in name or "oblique" in name or bool(flags & 2)
    if bold and italic:
        return "hebi"
    if bold:
        return "hebo"
    if italic:
        return "heit"
    return "helv"


_STYLE_WORDS_RE = re.compile(r"(bold|black|heavy|semibold|demibold|italic|oblique|regular|roman|book|normal)")


def _family_and_style(font_name, flags=0):
    """("arial", bold, italic) for names like "ABCDEF+Arial-BoldMT",
    "Arial,Bold", "ArialMT" or "Arial" -- so different copies of the same
    font, stored under slightly different names, can stand in for each
    other."""
    name = (font_name or "").split("+", 1)[-1].lower()
    bold = any(w in name for w in ("bold", "black", "heavy")) or bool((flags or 0) & 16)
    italic = "italic" in name or "oblique" in name or bool((flags or 0) & 2)
    family = re.split(r"[,\-]", name)[0]
    family = _STYLE_WORDS_RE.sub("", family)
    family = re.sub(r"(psmt|mt|ps)$", "", family).replace(" ", "").replace("_", "")
    return family, bold, italic


def _font_candidates(span, font_files):
    """Fonts to try for text drawn in `span`'s style, best first:
      1. every embedded copy (subset) of the span's own font, found
         anywhere in the document;
      2. embedded copies of the SAME family and style stored under another
         name (e.g. "ArialMT" for "Arial", "Arial,Bold" for
         "Arial-BoldMT");
      3. a built-in font of the same bold/italic style.
    Copies that can't be used to draw text (no character map -- common
    for "Identity-H" subsets) are left out. Returns [(label, fitz.Font)]."""
    name = (span.get("font") or "").split("+", 1)[-1]
    want = _family_and_style(name, span.get("flags", 0))
    ordered = list(font_files.get(name, []))
    for other, paths in font_files.items():
        if other != name and _family_and_style(other) == want:
            ordered += paths
    cands, seen = [], set()
    for path in ordered:
        if path in seen:
            continue
        seen.add(path)
        f = _font_obj(path, True)
        if f is not None and any(f.has_glyph(c) for c in (32, 48, 65, 97)):
            cands.append((name, f))
    key = _base14_for_span(span)
    f = _font_obj(key, False)
    if f is not None:
        cands.append((key, f))
    return cands


def _has(f, ch):
    return bool(f.has_glyph(ord(ch)))


def _font_runs(text, span, font_files):
    """Split `text` (to be drawn in `span`'s style) into [(text, font)]
    pieces so every character -- spaces included -- is drawn with a font
    that really has it.

    One embedded copy of the original font that covers the whole text is
    used if there is one. Otherwise each character takes the first copy
    that has it, so only a character that NO copy of the original font
    has falls back to the built-in font -- not the whole line, as before.
    Returns (pieces, missing_chars)."""
    cands = _font_candidates(span, font_files)
    if not cands:
        return [], set(text)
    for _, f in cands[:-1]:
        if all(_has(f, ch) for ch in text):
            return [(text, f)], set()
    pieces, missing = [], set()
    cur_font, cur_text = None, ""
    for ch in text:
        if cur_font is not None and _has(cur_font, ch):
            f = cur_font
        else:
            f = next((f for _, f in cands if _has(f, ch)), None)
            if f is None:
                if not ch.isspace():
                    missing.add(ch)
                f = cands[-1][1]
        if f is cur_font:
            cur_text += ch
        else:
            if cur_text:
                pieces.append((cur_text, cur_font))
            cur_font, cur_text = f, ch
    if cur_text:
        pieces.append((cur_text, cur_font))
    return pieces, missing


def _color_tuple(c):
    if isinstance(c, (tuple, list)):
        return tuple(c[:3])
    c = int(c or 0)
    return ((c >> 16) & 255) / 255.0, ((c >> 8) & 255) / 255.0, (c & 255) / 255.0


def find_hidden_chars(page):
    """Characters the PDF prints but then paints over -- e.g. some schedule
    PDFs draw a white box behind an extras line's italic description that
    covers the bold label's trailing ":", so the page shows "2 quantity -
    LS kit form charge", not "2 quantity: - LS kit form charge".

    Redrawn text goes on top of everything, so a covered character would
    suddenly show. This finds them (an opaque fill drawn AFTER the text,
    covering most of the character) so they can be left out of the redraw
    and the line looks exactly as it did. Returns {round(y): [(x,
    cover_rect, cover_colour), ...]} keyed by hidden characters' origins
    -- see _hidden_cover()."""
    hidden = {}
    try:
        fills = [d for d in page.get_drawings()
                 if d.get("fill") is not None and "f" in (d.get("type") or "")
                 and (d.get("fill_opacity") if d.get("fill_opacity") is not None else 1) >= 0.99]
        if not fills:
            return hidden
        for t in page.get_texttrace():
            later = [d for d in fills if d.get("seqno", -1) > t.get("seqno", 0)]
            if not later:
                continue
            for c in t["chars"]:
                bx = fitz.Rect(c[3])
                area = bx.width * bx.height
                if area <= 0:
                    continue
                for d in later:
                    inter = bx & d["rect"]
                    if not inter.is_empty and inter.width * inter.height >= 0.6 * area:
                        hidden.setdefault(round(c[2][1]), []).append(
                            (c[2][0], inter, tuple(d["fill"][:3])))
                        break
    except Exception:
        return {}
    return hidden


def _hidden_cover(ch, hidden):
    """(covered_rect, colour) if the original PDF painted over `ch`, else None."""
    for x, rect, colour in (hidden.get(round(ch["origin"][1]), ()) if hidden else ()):
        if abs(x - ch["origin"][0]) < 0.2:
            return rect, colour
    return None


def _char_groups(chars_with_span, hidden=None):
    """Group a line's characters into stretches that were printed as plain
    running text in ONE style: a new group starts wherever the style
    (span) changes or there's a positioning jump (a column gap, a tab, a
    justified space). Each group can then be redrawn at its exact
    original position in its own font, so nothing moves. A character the
    original PDF had painted over (see find_hidden_chars) gets a group of
    its own carrying that cover, so it can be painted over again."""
    groups = []
    for ch, span in chars_with_span:
        cover = _hidden_cover(ch, hidden)
        if cover is not None:
            groups.append({"span": span, "chars": [ch], "cover": cover})
            continue
        if groups and groups[-1].get("cover") is None:
            g = groups[-1]
            prev = g["chars"][-1]
            jump = abs(ch["origin"][0] - prev["bbox"][2]) > 0.5 or abs(ch["origin"][1] - prev["origin"][1]) > 0.5
            if g["span"] is span and not jump:
                g["chars"].append(ch)
                continue
        groups.append({"span": span, "chars": [ch]})
    for g in groups:
        g["text"] = "".join(c["c"] for c in g["chars"])
        g["x"] = g["chars"][0]["origin"][0]
        g["y"] = g["chars"][0]["origin"][1]
        if g.get("cover") is not None:
            # Cover box relative to the character's own origin, so it moves
            # with the character if the text after an edit shifts.
            rect, colour = g["cover"]
            g["cover"] = (fitz.Rect(rect.x0 - g["x"], rect.y0, rect.x1 - g["x"], rect.y1), colour)
    return groups


def _plan_whole_line_rewrite(line, line_hits, font_files, all_lines=(), busy_line_ids=(), hidden=None):
    """LOCAL CHANGE (keep a replaced line as ONE piece of text, in its
    original fonts and bold/italic styles).

    The old path redrew only the replacement plus everything after it, all
    in ONE font -- the style of the replaced word -- as a separate piece of
    text next to the untouched start of the line. Two problems followed:
      * the PDF held e.g. "Glass:" and "LHG026_4/4 (26) CN" as two separate
        fields, and
      * on a mixed-style line like "9. DOSTAWA EXPORT - 2 quantity:" (bold)
        + " - LS kit form charge" (italic), the italic part came out bold.

    This plans to redraw the WHOLE line (plus any separately-stored label
    just to its left -- see _left_neighbours) in one go, as runs:
      * every original stretch of text is redrawn in its OWN font, size,
        style and colour, at its original position (text after a
        replacement shifts by however much longer/shorter the new text is);
      * each replacement takes the style of the text it replaces, at the
        size from the sheet's Font size column if one is given.
    All runs are written as one text object, so the line stays one field.
    Returns None if the line has no usable characters.
    """
    owners = line["char_owners"]
    if not owners or not line_hits:
        return None

    neighbours, joiners = _left_neighbours(line, all_lines, busy_line_ids)

    runs = []          # dicts: x, y, text, size, span (style source)
    old_chars = []     # every original character being redrawn (for the redaction box)

    # 1. Labels stored as separate lines just to the left: unchanged, at
    #    their own positions.
    for nb, joiner in zip(neighbours, joiners):
        pairs = [(o[0]["_chars"][o[1]], o[0]) for o in nb["char_owners"]]
        old_chars += [c for c, _ in pairs]
        groups = _char_groups(pairs, hidden)
        if not groups:
            continue
        if joiner:
            groups[-1]["text"] += joiner
        for g in groups:
            runs.append({"x": g["x"], "y": g["y"], "text": g["text"],
                         "size": g["span"]["size"], "span": g["span"], "cover": g.get("cover")})

    # 2. This line: original stretches + replacements, left to right.
    pairs = [(o[0]["_chars"][o[1]], o[0]) for o in owners]
    old_chars += [c for c, _ in pairs]
    text = line["text"]
    delta = 0.0   # how far text after the edits so far has to move right

    def _keep(a, b):
        for g in _char_groups(pairs[a:b], hidden):
            runs.append({"x": g["x"] + delta, "y": g["y"], "text": g["text"],
                         "size": g["span"]["size"], "span": g["span"], "cover": g.get("cover")})

    cursor = 0
    for h in line_hits:
        _keep(cursor, h["start"])
        first_ch, first_span = pairs[h["start"]]
        size = h["size"] if h["size"] else first_span["size"]
        new_x = first_ch["origin"][0] + delta
        new_run = {"x": new_x, "y": first_ch["origin"][1], "text": h["new"],
                   "size": size, "span": first_span}
        runs.append(new_run)
        # Where the text after this replacement used to start vs. now.
        if h["end"] < len(pairs):
            old_after = pairs[h["end"]][0]["origin"][0]
        else:
            old_after = pairs[h["end"] - 1][0]["bbox"][2]
        new_width = sum(f.text_length(t, fontsize=size)
                        for t, f in _font_runs(h["new"], first_span, font_files)[0])
        delta = (new_x + new_width) - old_after
        cursor = h["end"]
    _keep(cursor, len(pairs))

    # 3. Pick real fonts for every run and measure.
    out_runs, missing = [], set()
    for r in runs:
        if not r["text"]:
            continue
        pieces, miss = _font_runs(r["text"], r["span"], font_files)
        missing |= miss
        x = r["x"]
        for t, f in pieces:
            w = f.text_length(t, fontsize=r["size"])
            out_runs.append({"x": x, "y": r["y"], "text": t, "font": f, "size": r["size"],
                             "color": _color_tuple(r["span"].get("color", 0)), "width": w,
                             "cover": r.get("cover")})
            x += w
    if not out_runs:
        return None

    x0 = min(r["x"] for r in out_runs)
    x_end = max(r["x"] + r["width"] for r in out_runs)
    for r in out_runs:
        r["dx"] = r["x"] - x0

    boxes = [c["bbox"] for c in old_chars]
    # Height of the area to clear comes from the visible characters only --
    # a stray space from an earlier edit can have a much taller box that
    # would reach into the lines above and below.
    vis = [c["bbox"] for c in old_chars if not c["c"].isspace()] or boxes
    first_span = pairs[line_hits[0]["start"]][1]
    return {
        "x": x0,
        "y": pairs[line_hits[0]["start"]][0]["origin"][1],
        "runs": out_runs,
        "text": "".join(r["text"] for r in out_runs),
        "width": x_end - x0,
        "missing": missing,
        "old_rect": fitz.Rect(min(b[0] for b in boxes), min(b[1] for b in vis),
                              max(b[2] for b in boxes), max(b[3] for b in vis)),
        "line_x1": first_span["line_bbox"][2],
    }


def _hits_overlap(a, b):
    """True if two search hits share at least one character of the same line."""
    return a["line"] is b["line"] and a["start"] < b["end"] and b["start"] < a["end"]


def _drop_overlapping_hits(hits):
    """Keep at most one replacement for any stretch of text on a line.

    Each line's text is searched separately for every row of the sheet, so
    two rows whose "Replace from this" texts overlap -- one inside the
    other, the two sharing a few words, or the same row entered twice --
    both match the same characters. Both replacements were then drawn on
    that line, giving doubled text like "RAL9002 Grey white mattRAL9002...".

    The longest match wins (it's the most specific row); for equal lengths,
    the row higher up the sheet wins. Matches that only touch end-to-start
    don't overlap and are both kept. Returns (kept_hits, [(kept, dropped)]).
    """
    order = sorted(range(len(hits)),
                   key=lambda i: (-(hits[i]["end"] - hits[i]["start"]),
                                  hits[i].get("rule_idx", 0), i))
    kept_idx, dropped = [], []
    for i in order:
        clash = next((hits[k] for k in kept_idx if _hits_overlap(hits[k], hits[i])), None)
        if clash is None:
            kept_idx.append(i)
        else:
            dropped.append((clash, hits[i]))
    kept_idx.sort()  # back to the original order
    return [hits[i] for i in kept_idx], dropped


# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------

def process(input_pdf, xlsx_path, output_pdf, preview_dir=None):
    replace_rules, delete_phrases = parse_instructions(xlsx_path)
    doc = fitz.open(input_pdf)
    workdir = tempfile.mkdtemp()
    font_files = extract_all_fonts(doc, workdir)

    total_replaced = 0
    total_deleted = 0
    modified_pages = set()
    overlap_warnings = {}  # page_num -> list of warning strings
    not_found_warnings = []  # human-readable strings about rules that matched nothing
    debug_notes = []  # diagnostic info surfaced to the person running the tool,
                       # not just to stderr -- font-fallback events, hits with
                       # no identifiable styling, and pages where several
                       # edits land close together (which has been the
                       # single most reliable predictor of a redaction
                       # disturbing nearby, untouched text on some documents)
    edits_per_page = {}  # page_num -> count of true-redaction rects on it

    # raw_hit_counts: every time a rule's "old" text was found on a page
    # this rule wasn't entirely gated out of (used to tell "genuinely not
    # found anywhere" apart from "found, but Only/Except correctly
    # restricted it away").
    raw_hit_counts = [0] * len(replace_rules)
    applied_hit_counts = [0] * len(replace_rules)
    raw_delete_hit_counts = [0] * len(delete_phrases)
    delete_resolved = [parse_delete_phrase(p["phrase"]) for p in delete_phrases]
    near_miss = {}  # rule_idx -> {variant_text: set(page_num, ...)}

    # LOCAL CHANGE: each page's edited regions (the same redaction and mask
    # rects used to clear the old text) so the preview render below can
    # highlight them. Purely additive -- never touches output_pdf, only the
    # separate preview_doc copy opened after saving.
    page_highlight_rects = {}

    num_pages = len(doc)
    for pno in range(num_pages):
        page = doc[pno]
        page_num = pno + 1
        spans = get_spans(page)
        lines = build_lines(spans)
        pos_blocks = build_pos_blocks(spans, page.rect.y1)
        hidden_chars = None  # worked out only if a line on this page is edited

        redact_rects = []  # tight rects around the EXACT old text being
                            # removed/replaced -- these get TRUE redaction
        mask_rects = []    # rects covering only REPOSITIONING territory
                            # (the gap a shorter/longer replacement opens or
                            # closes, or unmatched text being reflowed) --
                            # these get the older, non-destructive white
                            # overlay instead. Splitting the two apart keeps
                            # redaction's footprint as small as possible:
                            # some PDF generators draw a whole multi-line
                            # attribute block as one internal text object,
                            # and redacting a large rect that merely touches
                            # such a block can wipe out far more than
                            # intended. A tight redaction rect around just
                            # the actual old word/phrase is much less likely
                            # to trigger that.
        insert_jobs = []  # list of dicts: x, y, text, fontkey, fontfile, size, cover_idx (-> mask_rects)
        raw_hits = []  # collected across all rules before span-grouping (see below)

        for rule_idx, rule in enumerate(replace_rules):
            old, new = rule["old"], rule["new"]
            if not old:
                continue
            # Page-level gates -- these can be decided before even
            # searching the page, since they're page-number-based.
            if rule["except_pages"] and page_num in rule["except_pages"]:
                continue
            if rule["only_pages"] and page_num not in rule["only_pages"]:
                continue
            for hit in search_text_in_lines(lines, old):
                rect = hit["rect"]
                # search_text_in_lines() only ever returns exact,
                # case-sensitive matches (it searches the literal
                # extracted text directly) -- so no separate case check
                # is needed here the way page.search_for() used to need.
                raw_hit_counts[rule_idx] += 1

                # POS-number-based gates -- these need the actual match
                # location, since a single page can hold several POS items.
                if rule["only_pos"] or rule["except_pos"]:
                    pos_num = pos_number_for_rect(pos_blocks, rect)
                    if rule["only_pos"] and pos_num not in rule["only_pos"]:
                        continue
                    if rule["except_pos"] and pos_num in rule["except_pos"]:
                        continue

                applied_hit_counts[rule_idx] += 1
                raw_hits.append({
                    "rule_idx": rule_idx,
                    "rect": rect, "old": old, "new": new, "size": rule["size"],
                    "span": hit["span"], "line": hit["line"],
                    "start": hit["start"], "end": hit["end"],
                })

            for variant_text in find_near_miss_texts(spans, old):
                near_miss.setdefault(rule_idx, {}).setdefault(variant_text, set()).add(page_num)

        # Two rows can match OVERLAPPING text -- e.g. "kolor alu: RAL extra,
        # ACC1" and, on some POS numbers, just "RAL extra" inside it (or the
        # same row typed twice). Both would be printed, one on top of / just
        # after the other, so the line comes out doubled. Keep only one
        # match for any stretch of text (see _drop_overlapping_hits).
        raw_hits, dropped = _drop_overlapping_hits(raw_hits)
        for kept, lost in dropped:
            debug_notes.append(
                f"Page {page_num}: '{lost['old']}' overlaps '{kept['old']}' on the "
                f"same line -- only '{kept['old']}' -> '{kept['new']}' was applied there."
            )

        # Two different rules can both match text that lives on the SAME
        # underlying printed line (e.g. a summary line like "6. AMSTERDAM
        # F1 - 5 quantity: - Hoppe Amsterdam F1 window handle, no key
        # 303.75", where separate rules target "AMSTERDAM F1" and "Hoppe
        # Amsterdam F1 window handle, no key" within it). Handling each
        # hit in isolation -- covering/rewriting from its match to the end
        # of the WHOLE line -- would make the earlier hit's rewrite
        # duplicate everything the later hit is separately (and correctly)
        # already handling, producing overlapping garbled text. Group hits
        # by their line and bound each one's rewritten region to stop
        # right before the next hit on that same line, instead of running
        # all the way to the line's end.
        pad = 0.4
        hits_by_line = {}
        standalone_hits = []
        for hit in raw_hits:
            span = hit["span"]
            if span is None:
                standalone_hits.append(hit)
            else:
                hits_by_line.setdefault(id(hit["line"]), []).append(hit)

        for hit in standalone_hits:
            print(f"  [warn] page {page_num}: could not find styling for "
                  f"'{hit['old']}' -- using a fallback font/position", file=sys.stderr)
            debug_notes.append(
                f"Page {page_num}: could not find the original styling for "
                f"'{hit['old']}' -- used a fallback font/position instead of "
                f"matching the surrounding text exactly."
            )
            rect = hit["rect"]
            baseline_y = rect.y1 - (rect.y1 - rect.y0) * 0.2
            fontkey, fontfile = "helv", None
            size = hit["size"] or (rect.y1 - rect.y0) * 0.8
            combined_text = hit["new"]
            if not font_covers_text(fontkey, fontfile, combined_text):
                fontkey, fontfile = _base14_for_style(fontkey), None
            redact_rects.append(fitz.Rect(rect.x0 - pad, rect.y0 - pad, rect.x1 + pad, rect.y1 + pad))
            # No containing span was found for this hit (that's what makes
            # it "standalone"), so there's no block_idx to key off of --
            # fall back to the POS-block heuristic instead.
            redact_idx = len(redact_rects) - 1
            # No reflow gap here (no suffix to bridge), but insert_jobs
            # always tracks a mask_rects entry for resolve_line_overlaps to
            # extend if it ever needs to -- start it zero-width.
            mask_rects.append(fitz.Rect(rect.x1 - pad, rect.y0 - pad, rect.x1 + pad, rect.y1 + pad))
            insert_jobs.append({
                "x": rect.x0, "y": baseline_y, "text": combined_text,
                "fontkey": fontkey, "fontfile": fontfile, "size": size,
                "cover_idx": len(mask_rects) - 1,
                "redact_idx": redact_idx,
                "mask_indices": [len(mask_rects) - 1],
            })
            total_replaced += 1
            modified_pages.add(page_num)

        for line_hits in hits_by_line.values():
            line = line_hits[0]["line"]
            line_hits.sort(key=lambda h: h["rect"].x0)

            # LOCAL CHANGE: redraw the whole line as one piece of text when
            # possible, so e.g. "Glass: LHG026_4/4 (26) CN" doesn't end up
            # as two separate fields "Glass:" + "LHG026_4/4 (26) CN" (see
            # _plan_whole_line_rewrite). The old text of the WHOLE line is
            # truly redacted, so nothing is left hidden underneath either.
            if hidden_chars is None:
                hidden_chars = find_hidden_chars(page)
            plan = _plan_whole_line_rewrite(line, line_hits, font_files,
                                            lines, set(hits_by_line.keys()), hidden_chars)
            if plan is not None:
                if plan["missing"]:
                    debug_notes.append(
                        f"Page {page_num}: no available font covers "
                        f"{' '.join(sorted(plan['missing']))} in '{plan['text']}' -- "
                        f"those characters may not render correctly there."
                    )
                old_rect = plan["old_rect"]
                redact_rects.append(fitz.Rect(old_rect.x0 - pad, old_rect.y0 - pad,
                                              old_rect.x1 + pad, old_rect.y1 + pad))
                redact_idx = len(redact_rects) - 1
                cover_x1 = max(plan["line_x1"], plan["x"] + plan["width"])
                mask_rects.append(fitz.Rect(old_rect.x1 - pad, old_rect.y0 - pad,
                                            max(cover_x1, old_rect.x1) + pad, old_rect.y1 + pad))
                mask_idx = len(mask_rects) - 1
                insert_jobs.append({
                    "x": plan["x"], "y": plan["y"], "text": plan["text"],
                    "runs": plan["runs"], "width": plan["width"],
                    "cover_idx": mask_idx,
                    "redact_idx": redact_idx,
                    "mask_indices": [mask_idx],
                })
                total_replaced += len(line_hits)
                modified_pages.add(page_num)
                continue

            flow_x = None  # where the previous hit's rendered text actually ended
            for i, hit in enumerate(line_hits):
                span = hit["span"]
                rect = hit["rect"]
                baseline_y = span["origin"][1]
                idx, end = hit["start"], hit["end"]
                if i + 1 < len(line_hits):
                    suffix_end = line_hits[i + 1]["start"]
                    cover_x1 = line_hits[i + 1]["rect"].x0
                else:
                    suffix_end = len(line["text"])
                    cover_x1 = span["line_bbox"][2]
                suffix = line["text"][end:suffix_end]
                size = hit["size"] if hit["size"] else span["size"]
                combined_text = hit["new"] + suffix

                # The document's embedded font is usually a SUBSET containing
                # only the glyphs the original file actually used, and the
                # SAME font name can have several different subsets across
                # the document with different glyph coverage (see
                # extract_all_fonts). Pick whichever actual subset -- or,
                # failing that, a full-coverage builtin font matching the
                # same bold/italic style -- genuinely covers everything in
                # this specific combined_text (the replacement plus
                # whatever original suffix text is being reflowed with it).
                use_fontkey, use_fontfile = resolve_font_for_text(span["font"], font_files, combined_text)
                if use_fontfile is None and not font_covers_text(use_fontkey, use_fontfile, combined_text):
                    print(f"  [warn] page {page_num}: no available font (embedded or "
                          f"built-in) covers every character needed for '{combined_text}' "
                          f"-- some characters may not render correctly", file=sys.stderr)
                    debug_notes.append(
                        f"Page {page_num}: no available font covers every character "
                        f"needed for '{combined_text}' -- some characters may not "
                        f"render correctly there."
                    )

                # Where to actually draw this hit's text. The FIRST hit on a
                # line keeps its original position. Every hit after that
                # starts exactly where the PREVIOUS hit's own inserted text
                # (combined_text, suffix included) actually ends -- not at
                # its own old position -- because that suffix already
                # contains everything that used to sit between the two
                # hits (e.g. ": "). If we left it at its old position
                # instead, a replacement that's SHORTER than what it
                # replaced (e.g. "Kolor osłonek" -> "Hinge caps") would
                # leave a stretch of dead white space where the extra
                # length used to be, and a LONGER replacement would
                # overlap the next hit -- this single rule fixes both.
                x = rect.x0 if flow_x is None else flow_x
                font_obj = fitz.Font(fontfile=use_fontfile) if use_fontfile else fitz.Font(use_fontkey)
                rendered_width = font_obj.text_length(combined_text, fontsize=size)
                flow_x = x + rendered_width

                # Cover from the start of the old text (or, if this hit's
                # new position was pulled left of that, from the new
                # position instead) through to the start of the next hit on
                # this line, or however far the new text actually reaches
                # if that's further right than the next old hit started --
                # so any trailing text sharing the line, e.g. "OTHER - 3
                # quantity:", gets reflowed after the new text instead of
                # being overlapped by it, without stepping on territory
                # another hit already owns.
                cover_x0 = min(rect.x0, x)
                cover_x1 = max(cover_x1, flow_x)

                # The OLD TEXT ITSELF gets a tight, exact-fit true-redaction
                # rect (see the note on redact_rects/mask_rects above).
                # Everything else in the covered span -- the gap before or
                # after it that only exists to reflow surrounding text --
                # is pure repositioning, not sensitive replaced content, so
                # it gets the safer non-destructive mask instead.
                redact_rects.append(fitz.Rect(rect.x0 - pad, rect.y0 - pad, rect.x1 + pad, rect.y1 + pad))
                redact_idx = len(redact_rects) - 1
                mask_rects.append(fitz.Rect(rect.x1 - pad, rect.y0 - pad, cover_x1 + pad, rect.y1 + pad))
                mask_idx = len(mask_rects) - 1
                mask_indices = [mask_idx]
                if cover_x0 < rect.x0 - 1e-6:
                    mask_rects.append(fitz.Rect(cover_x0 - pad, rect.y0 - pad, rect.x0 + pad, rect.y1 + pad))
                    mask_indices.append(len(mask_rects) - 1)

                insert_jobs.append({
                    "x": x, "y": baseline_y, "text": combined_text,
                    "fontkey": use_fontkey, "fontfile": use_fontfile, "size": size,
                    "cover_idx": mask_idx,
                    "redact_idx": redact_idx,
                    "mask_indices": mask_indices,
                })
                total_replaced += 1
                modified_pages.add(page_num)

        for phrase_idx, phrase_rule in enumerate(delete_phrases):
            if phrase_rule["except_pages"] and page_num in phrase_rule["except_pages"]:
                continue
            if phrase_rule["only_pages"] and page_num not in phrase_rule["only_pages"]:
                continue
            search_text, whole_line = delete_resolved[phrase_idx]
            for hit in search_text_in_lines(lines, search_text):
                rect, span = hit["rect"], hit["span"]
                # search_text_in_lines() only returns exact, case-sensitive
                # matches, so no separate case check is needed here.
                raw_delete_hit_counts[phrase_idx] += 1

                if phrase_rule["only_pos"] or phrase_rule["except_pos"]:
                    pos_num = pos_number_for_rect(pos_blocks, rect)
                    if phrase_rule["only_pos"] and pos_num not in phrase_rule["only_pos"]:
                        continue
                    if phrase_rule["except_pos"] and pos_num in phrase_rule["except_pos"]:
                        continue

                # Text that a replace row is already rewriting isn't deleted
                # as well -- the delete would also wipe out the new text.
                clash = next((r for r in raw_hits if _hits_overlap(r, hit)), None)
                if clash is not None:
                    debug_notes.append(
                        f"Page {page_num}: delete '{phrase_rule['phrase']}' overlaps the "
                        f"replacement '{clash['old']}' -> '{clash['new']}' -- left to the "
                        f"replacement, not deleted."
                    )
                    continue

                pad = 0.4
                # Delete phrases always genuinely remove content (there's no
                # replacement text to reflow around), so everything here
                # goes straight to true redaction.
                if whole_line and span is not None:
                    # The instruction said to remove the entire line this
                    # text lives on, not just the matched words -- e.g.
                    # "the whole line of 'U-value (W/m2K)'" means delete
                    # the whole "U-value (W/m2K)= 1.39" line.
                    lx0, ly0, lx1, ly1 = span.get("line_bbox", span["bbox"])
                    redact_rects.append(fitz.Rect(lx0 - pad, ly0 - pad, lx1 + pad, ly1 + pad))
                    total_deleted += 1
                    modified_pages.add(page_num)
                    continue
                if span is not None:
                    remainder = span["text"].replace(search_text, "", 1)
                    if remainder.strip(" \t-:") == "":
                        # The whole span is essentially just this phrase
                        # (plus separators like " - ") -- remove all of it
                        # so no dangling punctuation is left behind.
                        bx0, by0, bx1, by1 = span["bbox"]
                        redact_rects.append(fitz.Rect(bx0 - pad, by0 - pad, bx1 + pad, by1 + pad))
                        total_deleted += 1
                        modified_pages.add(page_num)
                        continue
                redact_rects.append(fitz.Rect(rect.x0 - pad, rect.y0 - pad, rect.x1 + pad, rect.y1 + pad))
                total_deleted += 1
                modified_pages.add(page_num)

        if not redact_rects and not mask_rects:
            continue

        edits_per_page[page_num] = len(redact_rects)

        resolve_line_overlaps(insert_jobs, mask_rects)

        # LOCAL CHANGE: snapshot this page's finalized edit regions (after
        # resolve_line_overlaps may have widened some masks) before the
        # lists are reset at the top of the next page's iteration.
        # One box per edit: a replacement's redact rect and its mask rect(s)
        # are joined into one, so it isn't drawn as two boxes side by side.
        boxes, used_masks, used_redacts = [], set(), set()
        for job in insert_jobs:
            box = fitz.Rect(redact_rects[job["redact_idx"]])
            used_redacts.add(job["redact_idx"])
            for midx in job["mask_indices"]:
                if mask_rects[midx].width >= 1.0:  # skip zero-width placeholders
                    box |= mask_rects[midx]
                used_masks.add(midx)
            boxes.append(box)
        boxes += [fitz.Rect(r) for i, r in enumerate(redact_rects) if i not in used_redacts]
        boxes += [fitz.Rect(r) for i, r in enumerate(mask_rects) if i not in used_masks]
        # Boxes that overlap (two edits next to each other on one line) are
        # joined too, so each changed stretch of text shows as one box.
        merged = True
        while merged:
            merged = False
            for i in range(len(boxes)):
                for j in range(i + 1, len(boxes)):
                    inter = boxes[i] & boxes[j]
                    if not inter.is_empty and inter.height > 0.5 * min(boxes[i].height, boxes[j].height):
                        boxes[i] |= boxes.pop(j)
                        merged = True
                        break
                if merged:
                    break
        page_highlight_rects[page_num] = boxes

        # Map each redact_rects index to the insert_job (if any) it belongs
        # to, so each hit's full lifecycle -- redact its old text, mask its
        # reflow gap, draw its new text -- can be finished completely
        # before moving to the next hit.
        job_by_redact_idx = {}
        for job in insert_jobs:
            ridx = job.get("redact_idx")
            if ridx is not None:
                job_by_redact_idx[ridx] = job

        def _draw_insert(page, job):
            if job.get("runs"):
                # Every run in its own font/size, written together (one text
                # object per colour) so the line reads back as one field.
                # A character the original PDF had painted over is painted
                # over again straight after it, the same way the original
                # did, so it stays in the text but not on the page.
                writers = {}

                def _flush():
                    for color, tw in writers.items():
                        tw.write_text(page, color=color)
                    writers.clear()

                for r in job["runs"]:
                    tw = writers.get(r["color"])
                    if tw is None:
                        tw = writers[r["color"]] = fitz.TextWriter(page.rect)
                    rx = job["x"] + r["dx"]
                    tw.append((rx, r["y"]), r["text"], font=r["font"], fontsize=r["size"])
                    if r.get("cover") is not None:
                        _flush()
                        rel, colour = r["cover"]
                        page.draw_rect(fitz.Rect(rx + rel.x0, rel.y0, rx + rel.x1, rel.y1),
                                       color=None, fill=colour, fill_opacity=1, overlay=True)
                _flush()
                return
            x, y, text, fontkey, fontfile, size = (
                job["x"], job["y"], job["text"], job["fontkey"], job["fontfile"], job["size"]
            )
            if fontfile:
                page.insert_text((x, y), text, fontsize=size, fontname=fontkey,
                                  fontfile=fontfile, color=(0, 0, 0))
            else:
                page.insert_text((x, y), text, fontsize=size, fontname=fontkey, color=(0, 0, 0))

        # The old text actually being replaced/deleted gets TRUE redaction
        # -- removed from the page's content stream, not just painted over
        # -- so a PDF viewer's search/copy no longer finds it. Kept as
        # tight, minimal rects (see redact_rects/mask_rects note above) to
        # limit how much surrounding content a redaction could ever touch.
        # images=PDF_REDACT_IMAGE_NONE keeps this scoped to text only, so
        # it can't affect the window/door diagrams even if a rect happens
        # to sit close to one.
        #
        # Each hit's redact -> mask -> insert is applied as one complete
        # unit, in sequence, before starting the next hit's -- rather than
        # batching every redaction on the page into one add-all-then-
        # apply-once call. A save-and-reopen between every individual
        # redaction was tried at one point to chase a corruption pattern
        # where an unrelated, unedited line elsewhere on the page would go
        # blank or get mangled once a second redaction landed anywhere
        # nearby -- but that turned out to introduce ITS OWN new
        # corruption (of adjacent lines, even for a single isolated edit)
        # that the plain sequential approach here does not have. If that
        # original multi-edit corruption pattern resurfaces on a document,
        # it's a known open issue -- flag it rather than assuming this
        # sequence is the cause.
        for i, r in enumerate(redact_rects):
            page.add_redact_annot(r, fill=(1, 1, 1))
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
            job = job_by_redact_idx.get(i)
            if job is not None:
                for midx in job["mask_indices"]:
                    page.draw_rect(mask_rects[midx], color=None, fill=(1, 1, 1),
                                    fill_opacity=1, overlay=True)
                _draw_insert(page, job)

        # Any mask rects not tied to a specific redaction (there currently
        # are none by construction, but this keeps behavior correct if that
        # ever changes) still get painted.
        drawn_mask_indices = {midx for job in insert_jobs for midx in job["mask_indices"]}
        for midx, r in enumerate(mask_rects):
            if midx not in drawn_mask_indices:
                page.draw_rect(r, color=None, fill=(1, 1, 1), fill_opacity=1, overlay=True)

        # Any insert job that somehow isn't tied to a redaction (shouldn't
        # happen given how insert_jobs are built, but keeps behavior
        # correct if that ever changes) still gets drawn.
        for job in insert_jobs:
            if job.get("redact_idx") is None:
                _draw_insert(page, job)

        # Automated stand-in for a human eyeballing "the whole page, not
        # just the edited spot": re-check the page we just edited for any
        # inserted text unexpectedly overlapping something else.
        if insert_jobs:
            inserted_specs = []
            for job in insert_jobs:
                if job.get("runs"):
                    inserted_specs += [(job["x"] + r["dx"], r["y"], r["text"]) for r in job["runs"]]
                else:
                    inserted_specs.append((job["x"], job["y"], job["text"]))
            page_warnings = find_overlap_warnings(page, inserted_specs, redact_rects + mask_rects)
            if page_warnings:
                overlap_warnings[page_num] = page_warnings
                for w in page_warnings:
                    print(f"  [OVERLAP WARNING] page {page_num}: {w}", file=sys.stderr)

    doc.save(output_pdf)

    if preview_dir and modified_pages:
        os.makedirs(preview_dir, exist_ok=True)
        preview_doc = fitz.open(output_pdf)
        for pno in sorted(modified_pages):
            preview_page = preview_doc[pno - 1]
            # LOCAL CHANGE: highlight every edited region on the preview
            # only -- output_pdf was already saved above, untouched.
            for rect in page_highlight_rects.get(pno, []):
                preview_page.draw_rect(
                    rect, color=(0.85, 0.55, 0), width=1.2,
                    fill=(1, 0.92, 0.55), fill_opacity=0.45, overlay=True
                )
            preview_page.get_pixmap(dpi=150).save(
                os.path.join(preview_dir, f"page{pno}_preview.png"))

    # Flag any rule/phrase that never matched anywhere in the document --
    # almost always a typo, extra space, or the PDF wording being slightly
    # different from what was typed into the spreadsheet. Note this uses
    # raw_hit_counts (found at all, before Only/Except filtering) rather
    # than applied_hit_counts, so a rule correctly restricted down to zero
    # actual edits by its own Only/Except settings does NOT get flagged --
    # that's the sheet working as intended, not a mistake.
    #
    # A row that listed several "|" alternatives is only flagged if NONE
    # of them matched anything -- finding some alternatives but not
    # others in a given document is exactly what listing alternatives is
    # FOR (different documents can have different known-broken spellings
    # of the same word), not a mistake to warn about.
    warned_groups = set()
    for rule_idx, rule in enumerate(replace_rules):
        group_id = rule.get("row_group_id")
        if raw_hit_counts[rule_idx] == 0:
            sibling_idxs = [
                j for j, r in enumerate(replace_rules)
                if r.get("row_group_id") == group_id
            ]
            if all(raw_hit_counts[j] == 0 for j in sibling_idxs) and group_id not in warned_groups:
                warned_groups.add(group_id)
                if len(sibling_idxs) > 1:
                    alternatives = " | ".join(replace_rules[j]["old"] for j in sibling_idxs)
                    not_found_warnings.append(
                        f"None of the alternatives '{alternatives}' -> '{rule['new']}' "
                        f"were found anywhere in the PDF (outside any Only/Except pages) -- "
                        f"double-check the spelling/spacing matches the PDF exactly."
                    )
                else:
                    not_found_warnings.append(
                        f"Replace rule '{rule['old']}' -> '{rule['new']}' was not "
                        f"found anywhere in the PDF (outside any Only/Except pages) -- "
                        f"double-check the spelling/spacing matches the PDF exactly."
                    )
        variants = near_miss.get(rule_idx)
        if variants:
            for variant_text, pgs in variants.items():
                not_found_warnings.append(
                    f"Your rule '{rule['old']}' -> '{rule['new']}' left "
                    f"\"{variant_text}\" unchanged on page(s) {sorted(pgs)} "
                    f"-- it's close to your rule's text but not identical, "
                    f"so it didn't match. Add a separate row with this exact "
                    f"wording if it should change too."
                )
    for phrase_idx, phrase_rule in enumerate(delete_phrases):
        if raw_delete_hit_counts[phrase_idx] == 0:
            search_text, whole_line = delete_resolved[phrase_idx]
            not_found_warnings.append(
                f"Delete instruction '{phrase_rule['phrase']}' (looking for "
                f"\"{search_text}\") was not found anywhere in the PDF "
                f"(outside any Only/Except pages) -- double-check the "
                f"spelling/spacing matches the PDF exactly."
            )

    # Pages with several edits landing on them are the ones where a
    # redaction disturbing unrelated, nearby text has actually been
    # observed on some documents -- not a certainty for any given page,
    # but worth a look rather than only discovering it by eye later.
    for page_num, count in sorted(edits_per_page.items()):
        if count >= 2:
            debug_notes.append(
                f"Page {page_num}: {count} pieces of text were removed/replaced "
                f"on this page -- when several edits land close together, "
                f"it's occasionally caused an unrelated, untouched line nearby "
                f"to come out blank or garbled on some documents. Worth a look."
            )

    if debug_notes:
        not_found_warnings.append("--- Debug info ---")
        not_found_warnings.extend(debug_notes)

    return total_replaced, total_deleted, sorted(modified_pages), overlap_warnings, not_found_warnings


# ═════════════════════════════════════════════════════════════════════════
# PART 2 -- THE APP STEP
# ═════════════════════════════════════════════════════════════════════════

def apply_text_replace(doc, xlsx_bytes):
    """
    Run the Schedule Text Editor against the working document.

    Returns a dict:
        {
            'doc':               new fitz.Document (already reopened —
                                  swap this into st.session_state.doc)
            'replaced':          int
            'deleted':           int
            'pages':             sorted list of modified page numbers
            'overlap_warnings':  {page_num: [warning str, ...]}
            'not_found_warnings': [warning str, ...]
            'preview_images':    {page_num: png bytes}
        }
    """
    with tempfile.TemporaryDirectory() as workdir:
        pdf_path      = os.path.join(workdir, "input.pdf")
        xlsx_path     = os.path.join(workdir, "instructions.xlsx")
        output_path   = os.path.join(workdir, "output.pdf")
        preview_dir   = os.path.join(workdir, "previews")

        doc.save(pdf_path)
        with open(xlsx_path, "wb") as f:
            f.write(xlsx_bytes)

        replaced, deleted, pages, overlap_warnings, not_found_warnings = process(
            pdf_path, xlsx_path, output_path, preview_dir
        )

        with open(output_path, "rb") as f:
            output_bytes = f.read()

        preview_images = {}
        for pno in pages:
            preview_path = os.path.join(preview_dir, f"page{pno}_preview.png")
            if os.path.exists(preview_path):
                with open(preview_path, "rb") as f:
                    preview_images[pno] = f.read()

    doc.close()
    new_doc = fitz.open(stream=output_bytes, filetype="pdf")

    return {
        'doc':                new_doc,
        'replaced':           replaced,
        'deleted':             deleted,
        'pages':              pages,
        'overlap_warnings':    overlap_warnings,
        'not_found_warnings':  not_found_warnings,
        'preview_images':     preview_images,
    }

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pdf", help="Input PDF file")
    parser.add_argument("xlsx", help="Instructions .xlsx file")
    parser.add_argument("output", help="Output PDF path")
    parser.add_argument("--previews", default=None, help="Directory to save preview PNGs of modified pages")
    args = parser.parse_args()

    replaced, deleted, pages, overlap_warnings, not_found_warnings = process(
        args.pdf, args.xlsx, args.output, args.previews
    )
    print(f"Replaced {replaced} instance(s), deleted {deleted} instance(s).")
    print(f"Modified pages: {pages}")
    if overlap_warnings:
        print("\n*** POSSIBLE TEXT OVERLAP DETECTED -- review these pages before use: ***")
        for pno, warnings in overlap_warnings.items():
            print(f"  Page {pno}:")
            for w in warnings:
                print(f"    - {w}")
    else:
        print("No overlap issues detected on the modified pages.")
    if not_found_warnings:
        print("\n*** SOME RULES DID NOT MATCH ANYTHING -- check these: ***")
        for w in not_found_warnings:
            print(f"  - {w}")
