"""
MODULE 2 — GLASS MASS (WEIGHT) CALCULATOR
Reads glass sizes + LHG codes off a page, looks up thickness, computes
weight, writes the weight label back onto the PDF, and returns row data
for the on-screen results table.
"""

import re
import streamlit as st
import gspread
import fitz

from .config import SHEET_ID, GLASS_DENSITY, get_google_credentials


@st.cache_data(ttl=300)
def load_glass_lookup():
    """Pull LHG code -> thickness(mm) lookup table from the Google Sheet."""
    creds = get_google_credentials()
    gc = gspread.authorize(creds)
    ws = gc.open_by_key(SHEET_ID).get_worksheet_by_id(1019075390)
    rows = ws.get_all_values()
    lookup = {}
    for row in rows[5:]:
        if len(row) >= 6 and row[1].strip().startswith('LHG'):
            code      = row[1].strip().split()[0]
            thickness = row[5].strip()
            if thickness:
                lookup[code] = float(thickness)
    return lookup


@st.cache_data(ttl=300)
def load_glass_type_lookup():
    """
    Pull LHG code -> glass type code (DG/TG/VT/VP, column G) from the same
    glass sheet used by load_glass_lookup. Column B holds the LHG code,
    column G holds the glass type code — used by Module 5's 'table' match
    type to resolve the Glass Type category.
    """
    creds = get_google_credentials()
    gc = gspread.authorize(creds)
    ws = gc.open_by_key(SHEET_ID).get_worksheet_by_id(1019075390)
    rows = ws.get_all_values()
    lookup = {}
    for row in rows[5:]:
        if len(row) >= 7 and row[1].strip().startswith('LHG'):
            code       = row[1].strip().split()[0]
            glass_type = row[6].strip()   # column G
            if glass_type:
                lookup[code] = glass_type
    return lookup


# Stamps this module (or the frame matcher) already wrote, e.g. "[12 kg]" or
# "[LHF003]" -- never read back as part of a line's text.
_STAMP_RE = re.compile(r'^\[[^\]]*\]$')


def extract_text_pieces(page):
    """
    Every piece of text on the page as PyMuPDF splits it, with its position.

    One printed line can come out as several pieces. The Schedule Text
    Editor in particular redraws replaced text as a NEW piece next to the
    old label, e.g. 'Glass:' and 'LHG026_4/4 (26) CN' side by side on the
    same row. See row_text() for how they're joined back together.
    """
    pieces = []
    for b in page.get_text('dict')['blocks']:
        if 'lines' not in b:
            continue
        for line in b['lines']:
            spans = [s for s in line['spans'] if s['text'].strip()]
            if not spans:
                continue
            text = ''.join(s['text'] for s in spans).strip()
            if _STAMP_RE.match(text):
                continue
            first, last = spans[0], spans[-1]
            pieces.append({
                'text':      text,
                'x0':        min(s['bbox'][0] for s in spans),
                'x1':        max(s['bbox'][2] for s in spans),
                'y_mid':     (first['bbox'][1] + first['bbox'][3]) / 2,
                'y_base':    first['bbox'][1] + first['size'] * 0.85,
                'font_size': first['size'],
                'last_span': last,
            })
    return pieces


# How far apart two pieces on one row can be and still count as one line
# (as a share of the font size) -- bigger gaps are a separate column.
ROW_GAP_SHARE = 6.0


def row_text(piece, pieces):
    """
    The full text of the printed line that starts with `piece`: `piece`
    plus every piece to its right on the same row, in left-to-right order
    -- the same idea as the frame code matcher joining a window's text
    before searching it.

    Only pieces that continue the line are added: each must start no more
    than ROW_GAP_SHARE x font size after the previous one ends, so text in
    a separate column further right (e.g. 'Select Spruce') isn't pulled in.
    Returns (text, rightmost_piece, pieces_used) -- pieces_used is the list
    of the separate pieces' texts, for the raw-text debug view.
    """
    size = piece['font_size']
    same_row = sorted(
        (p for p in pieces
         if p is not piece and abs(p['y_mid'] - piece['y_mid']) <= size * 0.5
         and p['x0'] >= piece['x0']),
        key=lambda p: p['x0'])
    text, right_end, last = piece['text'], piece['x1'], piece
    parts = [piece['text']]
    for p in same_row:
        if p['x0'] - right_end > ROW_GAP_SHARE * size:
            break
        text = f"{text} {p['text']}"
        right_end = max(right_end, p['x1'])
        last = p
        parts.append(p['text'])
    return text, last, parts


def extract_size_and_glass_lines(page):
    """
    Scan a page's text and pull out:
      - size_entries: list of (y_mid, width_mm, height_mm, is_irregular)
      - glass_lines:  list of dicts with position/font info + LHG code (if any)

    Each line's FULL row text is used (see row_text()), so a glass line the
    Schedule Text Editor has split into 'Glass:' + 'LHG026_4/4 (26) CN'
    is still read as 'Glass: LHG026_4/4 (26) CN'.
    """
    pieces       = extract_text_pieces(page)
    size_entries = []
    glass_lines  = []
    size_texts   = {}   # size line y_mid -> its raw text, for the debug view

    # Top to bottom, so "the size entry just recorded" below really is the
    # one above an irregular-shape marker.
    for piece in sorted(pieces, key=lambda p: (p['y_mid'], p['x0'])):
        full_text, last, parts = row_text(piece, pieces)

        # Size line, e.g. "size (W x H): 1200 x 800"
        m = re.search(r'size \(W x H\):\s*(\d+)\s*x\s*(\d+)', full_text)
        if m and 'size (W x H)' in piece['text']:
            w, h = int(m.group(1)), int(m.group(2))
            size_entries.append((piece['y_mid'], w, h, False))
            size_texts[piece['y_mid']] = ' | '.join(parts)

        # Irregular shape markers — flag the size entry just recorded
        if re.search(r'ANGLE EXTRA|ARCH EXTRA', piece['text'], re.IGNORECASE):
            if size_entries:
                y, w, h, _ = size_entries[-1]
                size_entries[-1] = (y, w, h, True)

        # Glass line — keep the raw match list so downstream code can
        # tell "no code found" apart from "multiple codes found"
        if piece['text'].startswith('Glass:') or piece['text'].startswith('glass:'):
            lhg_matches    = re.findall(r'LHG\d+', full_text)
            lhg_code_found = lhg_matches[0] if len(lhg_matches) == 1 else None
            span           = last['last_span']
            bbox           = span['bbox']
            glass_lines.append({
                'y_mid':       (bbox[1] + bbox[3]) / 2,
                'y_base':      bbox[1] + span['size'] * 0.85,
                'font_size':   span['size'],
                'lhg_code':    lhg_code_found,
                'lhg_matches': lhg_matches,   # full list: [] = none found, 2+ = ambiguous
                'text':        full_text,
                # Raw pieces as the PDF holds them, separated by ' | ' (the
                # same style as the frame code matcher's Block Text), so a
                # line split by the Schedule Text Editor shows up as e.g.
                # 'Glass: | LHG026_4/4 (26) CN'.
                'raw_text':    ' | '.join(parts),
                'page':        page.number + 1,
                # For the stamp's fit check (see _stamp_position()):
                'x0':          piece['x0'],
                'row_right':   max(p['x1'] for p in pieces
                                   if p is piece or (abs(p['y_mid'] - piece['y_mid']) <= piece['font_size'] * 0.5
                                                     and p['x0'] >= piece['x0'])),
                'line_y_mid':  piece['y_mid'],
                'pieces':      pieces,
            })

    for glass_line in glass_lines:
        glass_line['size_texts'] = size_texts

    return size_entries, glass_lines


def match_glass_to_size(glass_line, size_entries):
    """Find the size entry directly above a given glass line (closest y_mid above it)."""
    above = [(abs(glass_line['y_mid'] - s[0]), s)
             for s in size_entries if s[0] < glass_line['y_mid']]
    if not above:
        return None
    _, size_entry = min(above, key=lambda x: x[0])
    return size_entry


# Where weight / area stamps go. Normally a stamp starts this far in from
# the page's right edge, on the glass line itself.
STAMP_RIGHT_OFFSET = 90
# A stamp moved down a line (see _stamp_position()) is right-aligned so it
# ENDS this far in from the page's right edge -- about where a normal stamp
# ends.
STAMP_RIGHT_MARGIN = 35
# Minimum clear space (points) between a line's text and the stamp.
STAMP_CLEAR_GAP = 4
# How many lines below the glass line to try before giving up.
STAMP_MAX_LINES_DOWN = 3


def _row_right_edge(pieces, y_mid, size, x_from):
    """Right-hand end of all the text on the row at y_mid, from x_from on."""
    edges = [p['x1'] for p in pieces
             if abs(p['y_mid'] - y_mid) <= size * 0.5 and p['x1'] > x_from]
    return max(edges, default=x_from)


def _stamp_position(glass_line, stamp_text, page_width):
    """
    (x, baseline y) for a weight / area stamp.

    Normally: on the glass line, STAMP_RIGHT_OFFSET in from the page edge.

    But a long glass line -- e.g. 'glass: LHG040_VAR-PN_88(48)4/4/4 (48 SB'
    after the Schedule Text Editor -- runs under that spot, and the stamp
    would print on top of it. Then the stamp goes on the next line down
    instead, right-aligned to end STAMP_RIGHT_MARGIN in from the page edge.
    Each line below (in the same column) is tried in turn, up to
    STAMP_MAX_LINES_DOWN, for one whose text ends before the stamp starts.
    If none has room, it stays on the glass line as before.
    """
    size = glass_line['font_size']
    normal_x = page_width - STAMP_RIGHT_OFFSET
    if glass_line.get('row_right') is None or \
            glass_line['row_right'] + STAMP_CLEAR_GAP <= normal_x:
        return normal_x, glass_line['y_base']

    width = fitz.Font('helv').text_length(stamp_text, fontsize=size)
    right_x = page_width - STAMP_RIGHT_MARGIN - width
    pieces = glass_line['pieces']
    x_from = glass_line['x0'] - 5

    # The lines below in the same column, one per row, top to bottom.
    below = sorted(
        (p for p in pieces
         if p['y_mid'] > glass_line['line_y_mid'] + size * 0.5
         and abs(p['x0'] - glass_line['x0']) <= 20),
        key=lambda p: p['y_mid'])
    rows = []
    for p in below:
        if not rows or p['y_mid'] - rows[-1]['y_mid'] > p['font_size'] * 0.5:
            rows.append(p)
    for row in rows[:STAMP_MAX_LINES_DOWN]:
        if _row_right_edge(pieces, row['y_mid'], row['font_size'], x_from) \
                + STAMP_CLEAR_GAP <= right_x:
            return right_x, row['y_base']
    return normal_x, glass_line['y_base']


def _stamp_highlight_rect(x, y_base, text, fontsize, fontname='helv'):
    """
    Bounding rect around a stamped text label, for preview highlighting
    only -- this is never used for redaction/deletion (unlike the
    Schedule Text Editor's cover rects), so it doesn't need to stay
    tight. Padded generously so it's easy to spot in the preview.
    """
    font_obj = fitz.Font(fontname)
    width = font_obj.text_length(text, fontsize=fontsize)
    pad = 2.0
    return fitz.Rect(
        x - pad, y_base - fontsize * 0.85 - pad,
        x + width + pad, y_base + fontsize * 0.25 + pad,
    )


def compute_weight_row(page, glass_line, size_entry, glass_lookup, page_width):
    """
    Given one glass line matched to one size entry:
      - if a single LHG code is found in glass_lookup -> stamp & return the weight
      - if a single LHG code was detected but isn't in glass_lookup -> area fallback
      - if NO LHG code was found on the line at all -> area fallback
      - if multiple LHG codes were found on the line (genuinely ambiguous) -> skip,
        no annotation written
    """
    _, w, h, irregular = size_entry

    if irregular:
        return {
            'Size':      f'{w} × {h} mm',
            'LHG Code':  glass_line['lhg_code'] or '—',
            'Thickness': '—',
            'Area (m²)': '—',
            'Weight':    'Skipped (irregular shape)',
            '_skip':     True,
            '_highlight_rect': None,
        }

    area        = (w / 1000) * (h / 1000)
    lhg_code    = glass_line['lhg_code']
    lhg_matches = glass_line.get('lhg_matches', [])

    if lhg_code and lhg_code in glass_lookup:
        thickness = glass_lookup[lhg_code]
        weight    = area * thickness * GLASS_DENSITY
        # Shown to the nearest whole kg: it's an estimate, so decimals would
        # suggest more precision than it has. Halves round up (72.5 -> 73),
        # unlike Python's round(), which rounds halves to the even number.
        weight_kg = int(weight + 0.5)

        # Stamp the computed weight back onto the PDF next to the glass line
        stamp_text = f'[{weight_kg} kg]'
        stamp_x, stamp_y = _stamp_position(glass_line, stamp_text, page_width)
        page.insert_text(
            (stamp_x, stamp_y),
            stamp_text,
            fontsize=glass_line['font_size'],
            fontname='helv',
            color=(0.0, 0.0, 0.0),
        )
        highlight_rect = _stamp_highlight_rect(
            stamp_x, stamp_y, stamp_text, glass_line['font_size']
        )

        return {
            'Size':      f'{w} × {h} mm',
            'LHG Code':  lhg_code,
            'Thickness': f'{thickness:.0f} mm',
            'Area (m²)': f'{area:.3f}',
            'Weight':    f'{weight_kg} kg',
            '_skip':     False,
            '_highlight_rect': highlight_rect,
        }

    # Genuinely ambiguous: 2+ LHG codes found on the line — skip entirely
    if len(lhg_matches) > 1:
        return {
            'Size':      f'{w} × {h} mm',
            'LHG Code':  'Multiple codes — skipped',
            'Thickness': '—',
            'Area (m²)': f'{area:.3f}',
            'Weight':    'Multiple codes — skipped',
            '_skip':     False,
            '_highlight_rect': None,
        }

    # No code found, OR a single code was found but isn't in glass_lookup —
    # fall back to stamping the area instead of a weight.
    stamp_text = f'[{area:.3f} m²]'
    stamp_x, stamp_y = _stamp_position(glass_line, stamp_text, page_width)
    page.insert_text(
        (stamp_x, stamp_y),
        stamp_text,
        fontsize=glass_line['font_size'],
        fontname='helv',
        color=(0.0, 0.0, 0.0),
    )
    highlight_rect = _stamp_highlight_rect(
        stamp_x, stamp_y, stamp_text, glass_line['font_size']
    )
    label = lhg_code if lhg_code else 'No LHG code'
    return {
        'Size':      f'{w} × {h} mm',
        'LHG Code':  label,
        'Thickness': '—',
        'Area (m²)': f'{area:.3f}',
        'Weight':    f'No LHG match — area shown ({area:.3f} m²)',
        '_skip':     False,
        '_highlight_rect': highlight_rect,
    }


def process_glass_weights(page, glass_lookup):
    """
    Full mass-calculator pass for a single page: extract glass/size data,
    match them up, compute + stamp weights, and return the result rows.
    """
    size_entries, glass_lines = extract_size_and_glass_lines(page)
    page_width = page.rect.width

    rows = []
    for glass_line in glass_lines:
        size_entry = match_glass_to_size(glass_line, size_entries)
        if size_entry is None:
            continue
        row = compute_weight_row(page, glass_line, size_entry, glass_lookup, page_width)
        # Raw text for the "Show raw text" debug view in app.py: the size
        # line and glass line exactly as read, so a missed or wrong LHG
        # code can be traced back to what's actually in the PDF.
        size_raw = glass_line['size_texts'].get(size_entry[0], '')
        row['Raw Text'] = f"{size_raw}\n{glass_line['raw_text']}"
        row['Page'] = glass_line['page']
        rows.append(row)
    return rows
