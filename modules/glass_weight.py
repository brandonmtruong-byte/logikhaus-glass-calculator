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


def extract_size_and_glass_lines(page):
    """
    Scan a page's text blocks and pull out:
      - size_entries: list of (y_mid, width_mm, height_mm, is_irregular)
      - glass_lines:  list of dicts with position/font info + LHG code (if any)
    """
    blocks       = page.get_text('dict')['blocks']
    size_entries = []
    glass_lines  = []

    for b in blocks:
        if 'lines' not in b:
            continue
        for line in b['lines']:
            spans     = line['spans']
            full_text = ''.join(s['text'] for s in spans).strip()

            # Size line, e.g. "size (W x H): 1200 x 800"
            m = re.search(r'size \(W x H\):\s*(\d+)\s*x\s*(\d+)', full_text)
            if m:
                w, h  = int(m.group(1)), int(m.group(2))
                y_mid = (spans[0]['bbox'][1] + spans[0]['bbox'][3]) / 2
                size_entries.append((y_mid, w, h, False))

            # Irregular shape markers — flag the size entry just recorded
            if re.search(r'ANGLE EXTRA|ARCH EXTRA', full_text, re.IGNORECASE):
                if size_entries:
                    y, w, h, _ = size_entries[-1]
                    size_entries[-1] = (y, w, h, True)

            # Glass line — keep the raw match list so downstream code can
            # tell "no code found" apart from "multiple codes found"
            if full_text.startswith('Glass:') or full_text.startswith('glass:'):
                lhg_matches    = re.findall(r'LHG\d+', full_text)
                lhg_code_found = lhg_matches[0] if len(lhg_matches) == 1 else None
                last           = spans[-1]
                bbox           = last['bbox']
                glass_lines.append({
                    'y_mid':       (bbox[1] + bbox[3]) / 2,
                    'y_base':      bbox[1] + last['size'] * 0.85,
                    'font_size':   last['size'],
                    'lhg_code':    lhg_code_found,
                    'lhg_matches': lhg_matches,   # full list: [] = none found, 2+ = ambiguous
                })

    return size_entries, glass_lines


def match_glass_to_size(glass_line, size_entries):
    """Find the size entry directly above a given glass line (closest y_mid above it)."""
    above = [(abs(glass_line['y_mid'] - s[0]), s)
             for s in size_entries if s[0] < glass_line['y_mid']]
    if not above:
        return None
    _, size_entry = min(above, key=lambda x: x[0])
    return size_entry


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

        # Stamp the computed weight back onto the PDF next to the glass line
        stamp_text = f'[{weight:.1f} kg]'
        page.insert_text(
            (page_width - 90, glass_line['y_base']),
            stamp_text,
            fontsize=glass_line['font_size'],
            fontname='helv',
            color=(0.0, 0.0, 0.0),
        )
        highlight_rect = _stamp_highlight_rect(
            page_width - 90, glass_line['y_base'], stamp_text, glass_line['font_size']
        )

        return {
            'Size':      f'{w} × {h} mm',
            'LHG Code':  lhg_code,
            'Thickness': f'{thickness:.0f} mm',
            'Area (m²)': f'{area:.3f}',
            'Weight':    f'{weight:.1f} kg',
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
    page.insert_text(
        (page_width - 90, glass_line['y_base']),
        stamp_text,
        fontsize=glass_line['font_size'],
        fontname='helv',
        color=(0.0, 0.0, 0.0),
    )
    highlight_rect = _stamp_highlight_rect(
        page_width - 90, glass_line['y_base'], stamp_text, glass_line['font_size']
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
        rows.append(compute_weight_row(page, glass_line, size_entry, glass_lookup, page_width))
    return rows
