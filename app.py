import streamlit as st
import fitz
import re
import gspread
import pandas as pd
from google.oauth2.service_account import Credentials
import os

# ── Page config ────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Logikhaus Glass Calculator",
    page_icon="🪟",
    layout="centered"
)

# ── Styling ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&display=swap');

    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

    .block-container { padding-top: 2.5rem; max-width: 760px; }

    h1 { font-size: 1.5rem; font-weight: 600; letter-spacing: -0.02em; color: #111; }
    h3 { font-size: 0.85rem; font-weight: 500; text-transform: uppercase;
         letter-spacing: 0.08em; color: #888; margin-bottom: 0.5rem; }

    .lh-header {
        display: flex; align-items: center; gap: 14px;
        border-bottom: 2px solid #8B1A1A; padding-bottom: 1rem; margin-bottom: 2rem;
    }
    .lh-logo {
        background: #8B1A1A; color: white; font-weight: 700;
        font-size: 0.75rem; padding: 6px 10px; letter-spacing: 0.05em;
    }
    .lh-title { font-size: 1.25rem; font-weight: 600; color: #111; }
    .lh-sub   { font-size: 0.8rem; color: #888; margin-top: 2px; }

    .status-box {
        background: #f7f7f5; border-left: 3px solid #8B1A1A;
        padding: 0.75rem 1rem; border-radius: 0 4px 4px 0;
        font-size: 0.85rem; color: #333; margin-bottom: 1rem;
    }
    .skip-row { color: #aaa; font-style: italic; }

    div[data-testid="stDownloadButton"] button {
        background: #8B1A1A; color: white; border: none;
        font-weight: 500; width: 100%;
    }
    div[data-testid="stDownloadButton"] button:hover { background: #6e1414; }
</style>
""", unsafe_allow_html=True)

# ── Header ─────────────────────────────────────────────────────────────────
col_logo, col_title = st.columns([1, 3])
with col_logo:
    st.image("Logikhaus_logo.jpg", use_container_width=True)
with col_title:
    st.markdown("""
    <div style="padding-top: 1rem;">
        <div class="lh-title">Glass Weight Calculator</div>
        <div class="lh-sub">Logikhaus Pty Ltd — internal tool</div>
    </div>
    """, unsafe_allow_html=True)
st.markdown('<hr style="border: 2px solid #8B1A1A; margin-bottom: 2rem;">', unsafe_allow_html=True)

# ── Constants ──────────────────────────────────────────────────────────────
SHEET_ID      = '1GLWQq3ruw1IARJ1jIQs4Be_KPNk1LXSx-1IAIZCfpY0'
GLASS_DENSITY = 2.5   # kg per m² per mm

LOGO_PATH = os.path.join(os.path.dirname(__file__), "Logikhaus_logo.jpg")
LOGO_RECT = fitz.Rect(20, 25, 138, 118)   # position of the stamped logo on page 1

LEGEND_PDF_PATH = os.path.join(os.path.dirname(__file__), "LEGEND page for Schedule.pdf")
LEGEND_KEYWORDS = ["LEGEND", "Codes (left column) are in alphabetical order"]

# Separate spreadsheet holding frame code definitions (tab "CODES")
# and the matching rules used to pick a code from quote text (tab "RULESUPDATE").
FRAME_SHEET_ID = '1Ieyvx0ZgSBToQFCDGXM8d8xK3zaxqKnXmLdK8ir79n4'
FRAME_RULES_TAB = 'RULESUPDATE'


# ═════════════════════════════════════════════════════════════════════════
#  MODULE 1 — LOGO STAMPER
#  Stamps the Logikhaus logo onto the first page of the PDF.
# ═════════════════════════════════════════════════════════════════════════

def stamp_logo(page):
    """Insert the Logikhaus logo image onto the given page, if the logo file exists."""
    if not os.path.exists(LOGO_PATH):
        return
    with open(LOGO_PATH, "rb") as f:
        logo_bytes = f.read()
    page.insert_image(LOGO_RECT, stream=logo_bytes)


# ═════════════════════════════════════════════════════════════════════════
#  MODULE 2 — GLASS MASS (WEIGHT) CALCULATOR
#  Reads glass sizes + LHG codes off a page, looks up thickness, computes
#  weight, writes the weight label back onto the PDF, and returns row data
#  for the on-screen results table.
# ═════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=300)
def load_glass_lookup():
    """Pull LHG code -> thickness(mm) lookup table from the Google Sheet."""
    creds_dict = dict(st.secrets["gcp_service_account"])
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
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
    creds_dict = dict(st.secrets["gcp_service_account"])
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
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
        }

    area        = (w / 1000) * (h / 1000)
    lhg_code    = glass_line['lhg_code']
    lhg_matches = glass_line.get('lhg_matches', [])

    if lhg_code and lhg_code in glass_lookup:
        thickness = glass_lookup[lhg_code]
        weight    = area * thickness * GLASS_DENSITY

        # Stamp the computed weight back onto the PDF next to the glass line
        page.insert_text(
            (page_width - 90, glass_line['y_base']),
            f'[{weight:.1f} kg]',
            fontsize=glass_line['font_size'],
            fontname='helv',
            color=(0.0, 0.0, 0.0),
        )

        return {
            'Size':      f'{w} × {h} mm',
            'LHG Code':  lhg_code,
            'Thickness': f'{thickness:.0f} mm',
            'Area (m²)': f'{area:.3f}',
            'Weight':    f'{weight:.1f} kg',
            '_skip':     False,
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
        }

    # No code found, OR a single code was found but isn't in glass_lookup —
    # fall back to stamping the area instead of a weight.
    page.insert_text(
        (page_width - 90, glass_line['y_base']),
        f'[{area:.3f} m²]',
        fontsize=glass_line['font_size'],
        fontname='helv',
        color=(0.0, 0.0, 0.0),
    )
    label = lhg_code if lhg_code else 'No LHG code'
    return {
        'Size':      f'{w} × {h} mm',
        'LHG Code':  label,
        'Thickness': '—',
        'Area (m²)': f'{area:.3f}',
        'Weight':    f'No LHG match — area shown ({area:.3f} m²)',
        '_skip':     False,
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


# ═════════════════════════════════════════════════════════════════════════
#  MODULE 3 — LEGEND PAGE ADDER
#  Checks whether the legend page is already in the quote, and appends the
#  standard legend PDF to the end if it's missing.
# ═════════════════════════════════════════════════════════════════════════

def has_legend_page(doc):
    """Return True if any page in doc already contains the legend text."""
    for page in doc:
        text = page.get_text()
        if all(kw in text for kw in LEGEND_KEYWORDS):
            return True
    return False


def append_legend_page(doc):
    """
    Append the legend PDF to the end of doc, unless a legend page is
    already present. Returns a status string for UI feedback:
    'added', 'already_present', or 'missing_file'.
    """
    if has_legend_page(doc):
        return 'already_present'
    if not os.path.exists(LEGEND_PDF_PATH):
        return 'missing_file'
    legend_doc = fitz.open(LEGEND_PDF_PATH)
    doc.insert_pdf(legend_doc)
    legend_doc.close()
    return 'added'

# ═════════════════════════════════════════════════════════════════════════
#  MODULE 4 — FRAME CODE LOOKUP CONNECTION
#  Connects to the FRAME_SHEET_ID spreadsheet and loads:
#    - the CODES tab: frame code (LHF001, ...) -> attributes
#    - the RULESUPDATE tab: rules used to work out those attributes from
#      raw quote text (Category / Code / Match Type / Match Value, one
#      row per rule)
# ═════════════════════════════════════════════════════════════════════════

def _open_frame_sheet():
    """Authenticate and open the frame code spreadsheet (shared helper)."""
    creds_dict = dict(st.secrets["gcp_service_account"])
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    gc = gspread.authorize(creds)
    return gc.open_by_key(FRAME_SHEET_ID)


@st.cache_data(ttl=300)
def load_frame_codes():
    """
    Load the CODES tab: each row maps a Frame code (e.g. LHF001) to its
    attributes (System, Glass type, Opening type, Material, Threshold, ...).
    Returned as a list of dicts, keyed by the sheet's own header row.
    """
    sh = _open_frame_sheet()
    ws = sh.worksheet("CODES")
    return ws.get_all_records()


@st.cache_data(ttl=300)
def load_frame_rules():
    """
    Load the RULESUPDATE tab. This is a flat table:

        Category | Code | Match Type | Match Value | Include | Exclude
        System   | ALU75 | text      | Aluminium 75 |         |
        ...

    Match Type tells the matcher how to use each row:
      - 'text'  : literal substring search in the quote text (Match Value)
      - 'table' : same as 'text' for now (Match Value)
      - 'oType' : depends on the already-resolved Opening Type category
                  (Match Value holds the Opening Type code to compare against)
      - 'logic' : uses the Include / Exclude columns — all Include terms
                  must be present, all Exclude terms must be absent

    Returned as a list of dicts (one per rule row), keyed by the sheet's
    own header row.
    """
    sh = _open_frame_sheet()
    ws = sh.worksheet(FRAME_RULES_TAB)
    return ws.get_all_records()

# ═════════════════════════════════════════════════════════════════════════
#  MODULE 5 — FRAME CODE MATCHER
#  For each window (Pos.no block) on a page: resolve System / Glass Type /
#  Opening Type / Material / Threshold from the quote text using the
#  RULESUPDATE rules, look the 5-tuple up in CODES to get a Frame code,
#  and stamp it above that window's "System:" line. If any of the 5
#  categories can't be pinned down to exactly one code, the window is
#  flagged as an error and nothing is stamped.
# ═════════════════════════════════════════════════════════════════════════

# Order matters: Threshold's 'oType' rules depend on Opening Type already
# being resolved, so Threshold must be resolved last.
CATEGORY_ORDER = ['System', 'Glass Type', 'Opening Type', 'Material', 'Threshold']

# Maps a resolved category name to its column name in the CODES tab.
CODES_COLUMN_MAP = {
    'System':       'System',
    'Glass Type':   'Glass type',
    'Opening Type': 'Opening type',
    'Material':     'MATERIAL',
    'Threshold':    'THRESHOLD',
}


def extract_page_lines(page):
    """Return every text line on the page, top-to-bottom, with position info."""
    blocks = page.get_text('dict')['blocks']
    lines = []
    for b in blocks:
        if 'lines' not in b:
            continue
        for line in b['lines']:
            spans = line['spans']
            if not spans:
                continue
            full_text = ''.join(s['text'] for s in spans).strip()
            if not full_text:
                continue
            bbox = spans[0]['bbox']
            lines.append({
                'y_mid':     (bbox[1] + bbox[3]) / 2,
                'text':      full_text,
                'bbox':      bbox,
                'font_size': spans[0]['size'],
            })
    lines.sort(key=lambda l: l['y_mid'])
    return lines


def split_into_window_blocks(lines):
    """
    Split a page's lines into one block per window, each starting at its
    'Pos.no N: ...' line and running up to (not including) the next one.
    """
    blocks  = []
    current = None
    for line in lines:
        if re.match(r'Pos\.?no\s*\d+', line['text'], re.IGNORECASE):
            if current:
                blocks.append(current)
            current = {'pos_label': line['text'], 'lines': [line]}
        elif current:
            current['lines'].append(line)
    if current:
        blocks.append(current)
    return blocks


def find_system_line(block_lines):
    """Find the line starting with 'System:' within a window block, if any."""
    for line in block_lines:
        if line['text'].lower().startswith('system:'):
            return line
    return None


def group_rules_by_category(frame_rules):
    """Turn the flat RULESUPDATE rows into {category: {code: [rule_rows]}}."""
    grouped = {}
    for row in frame_rules:
        grouped.setdefault(row['Category'], {}).setdefault(row['Code'], []).append(row)
    return grouped

def _get_field_ci(rule_row, field_name):
    """
    Fetch a field from a rule row, tolerant of header mismatches
    (case, leading/trailing whitespace) that would otherwise silently
    return '' via a plain dict lookup on the wrong key.
    """
    target = field_name.strip().lower()
    for key, value in rule_row.items():
        if key.strip().lower() == target:
            return value
    return ''

def contains_normalized(haystack_lower, needle):
    """
    Whitespace- and line-break-insensitive substring check. Handles two
    quirks: (1) stray spaces mid-word from PDF text extraction (e.g.
    'I nward opening'), and (2) phrases that get word-wrapped across two
    separate PDF text lines, which our own block-text joining then
    separates with ' | ' (e.g. '1- | seal threshold'). Stripping both
    whitespace and '|' before comparing makes matching tolerant of both.
    """
    compact_haystack = re.sub(r'[\s|]+', '', haystack_lower)
    compact_needle    = re.sub(r'[\s|]+', '', needle.lower())
    return compact_needle in compact_haystack


def evaluate_logic_rule(rule_row, text_lower):
    """
    Evaluate a 'logic' rule using its Include/Exclude columns, e.g.:
      Include: fitting          Exclude: Wheels          -> present AND absent
      Include: (blank)          Exclude: HS:- ZERO, ECO PASS  -> both absent
    All Include terms must be present; all Exclude terms must be absent.
    """
    includes = [t.strip() for t in str(_get_field_ci(rule_row, 'Include')).split(',') if t.strip()]
    excludes = [t.strip() for t in str(_get_field_ci(rule_row, 'Exclude')).split(',') if t.strip()]
    return (all(contains_normalized(text_lower, t) for t in includes)
            and all(not contains_normalized(text_lower, t) for t in excludes))


def extract_lhg_code(block_text):
    """
    Find the LHG code within a window's raw (non-lowercased) block text,
    e.g. from its 'Glass: ... LHG012 ...' line. If multiple codes are
    found on the line, just use the first one — good enough for looking
    up Glass Type (DG/TG/VT/VP), even though it's ambiguous for the mass
    calculator's own weight lookup (handled separately in Module 2).
    Returns None only if zero codes are found at all.
    """
    matches = re.findall(r'LHG\d+', block_text)
    return matches[0] if matches else None


def evaluate_rule(rule_row, block_text_lower, resolved_so_far, glass_type_lookup=None, lhg_code=None):
    """Evaluate a single RULESUPDATE row against a window's block text."""
    match_type  = rule_row['Match Type'].strip().lower()
    match_value = str(rule_row['Match Value']).strip()

    if match_type == 'text':
        return contains_normalized(block_text_lower, match_value)
    if match_type == 'table':
        # Glass Type: look up the window's LHG code in the glass sheet's
        # column G (DG/TG/VT/VP) rather than searching quote text directly.
        if not lhg_code or not glass_type_lookup:
            return False
        looked_up = glass_type_lookup.get(lhg_code)
        if not looked_up:
            return False
        return looked_up.strip().lower() == match_value.lower()
    if match_type == 'otype':
        return resolved_so_far.get('Opening Type') == match_value
    if match_type == 'logic':
        return evaluate_logic_rule(rule_row, block_text_lower)
    return False   # unknown match type — never matches


def resolve_categories(block_text, rules_by_category, glass_type_lookup=None):
    """
    Resolve all 5 categories for one window's block text.
    Returns (resolved_dict, error_list). error_list is empty only when all
    5 categories resolved to exactly one code each.
    """
    block_text_lower = block_text.lower()
    lhg_code          = extract_lhg_code(block_text)
    resolved = {}
    errors   = []

    for category in CATEGORY_ORDER:
        rules_for_category = rules_by_category.get(category, {})
        matched_codes = [
            code for code, rule_rows in rules_for_category.items()
            if any(evaluate_rule(r, block_text_lower, resolved, glass_type_lookup, lhg_code)
                   for r in rule_rows)
        ]
        if len(matched_codes) == 1:
            resolved[category] = matched_codes[0]
        elif len(matched_codes) == 0:
            errors.append(f'{category}: no match found')
        else:
            errors.append(f'{category}: ambiguous ({", ".join(matched_codes)})')

    return resolved, errors


def match_frame_code(resolved, frame_codes):
    """Look up the resolved 5-tuple in the CODES tab. Returns (frame_code, error)."""
    matches = [
        row for row in frame_codes
        if all(str(row.get(CODES_COLUMN_MAP[cat], '')).strip() == resolved[cat]
               for cat in CATEGORY_ORDER)
    ]
    if len(matches) == 1:
        return matches[0].get('Frame code'), None
    if len(matches) == 0:
        return None, 'No matching row in CODES tab'
    return None, f'Multiple CODES rows match ({len(matches)})'


def process_frame_codes(page, frame_codes, rules_by_category, glass_type_lookup=None):
    """
    Full frame-code pass for a single page: split into window blocks,
    resolve + look up a frame code for each, stamp it above 'System:',
    and return a result row per window for the on-screen debug table.

    Every result row always has one column per category (System, Glass
    Type, Opening Type, Material, Threshold) — filled in with whatever was
    resolved, blank if that category failed — plus Frame Code and Details,
    so partial progress is visible even on an ERROR row.
    """
    lines          = extract_page_lines(page)
    window_blocks  = split_into_window_blocks(lines)
    results        = []

    for block in window_blocks:
        block_text  = ' | '.join(l['text'] for l in block['lines'])
        system_line = find_system_line(block['lines'])

        resolved, errors = resolve_categories(block_text, rules_by_category, glass_type_lookup)

        # Base row always shows what was (or wasn't) resolved per category
        row = {
            'Window':     block['pos_label'],
            'Frame Code': 'ERROR',
            **{cat: resolved.get(cat, '') for cat in CATEGORY_ORDER},
            'Details':    '',
            'Block Text': block_text,
        }

        if errors:
            row['Details'] = '; '.join(errors)
            results.append(row)
            continue

        frame_code, lookup_error = match_frame_code(resolved, frame_codes)
        if lookup_error:
            row['Details'] = lookup_error
            results.append(row)
            continue

        if system_line:
            page.insert_text(
                (system_line['bbox'][0], system_line['bbox'][1] - 2),
                f'[{frame_code}]',
                fontsize=system_line['font_size'],
                fontname='helv',
                color=(0.0, 0.0, 0.0),
            )

        row['Frame Code'] = frame_code
        row['Details']    = 'OK'
        results.append(row)

    return results

# ═════════════════════════════════════════════════════════════════════════
#  ORCHESTRATOR — runs Modules 1, 2, 3, and 5 on the uploaded PDF.
# ═════════════════════════════════════════════════════════════════════════

def process_pdf(file_bytes, glass_lookup, frame_codes=None, frame_rules=None, glass_type_lookup=None):
    doc     = fitz.open(stream=file_bytes, filetype="pdf")
    results = []
    frame_results = []

    rules_by_category = group_rules_by_category(frame_rules) if frame_rules else {}

    for page_num, page in enumerate(doc):
        if page_num == 0:
            stamp_logo(page)                                        # Module 1
        results.extend(process_glass_weights(page, glass_lookup))   # Module 2
        if frame_codes is not None and frame_rules is not None:
            frame_results.extend(
                process_frame_codes(page, frame_codes, rules_by_category, glass_type_lookup)  # Module 5
            )

    legend_status = append_legend_page(doc)                         # Module 3

    out_bytes = doc.tobytes()
    doc.close()
    return out_bytes, results, legend_status, frame_results


# ═════════════════════════════════════════════════════════════════════════
#  STREAMLIT UI
# ═════════════════════════════════════════════════════════════════════════

# ── Load glass lookup ──────────────────────────────────────────────────────
try:
    with st.spinner('Loading glass data from sheet...'):
        glass_lookup      = load_glass_lookup()
        glass_type_lookup = load_glass_type_lookup()
    st.markdown(f'<div class="status-box">✓ Glass database loaded — {len(glass_lookup)} codes</div>',
                unsafe_allow_html=True)
except Exception as e:
    st.error(f'Could not connect to Google Sheets: {type(e).__name__}: {e}')
    import traceback
    st.code(traceback.format_exc())
    st.stop()

# ── Load frame code data (Module 4 connection) ──────────────────────────────
frame_codes, frame_rules = None, None
try:
    with st.spinner('Loading frame code data...'):
        frame_codes = load_frame_codes()
        frame_rules = load_frame_rules()
    st.markdown(
        f'<div class="status-box">✓ Frame code data loaded — '
        f'{len(frame_codes)} codes, {len(frame_rules)} rules</div>',
        unsafe_allow_html=True
    )
    with st.expander("Debug: preview CODES / RULESUPDATE tabs"):
        st.write("CODES tab — first 3 rows:")
        st.write(frame_codes[:3])
        st.write("RULESUPDATE tab — first 5 rows:")
        st.write(frame_rules[:5])
except Exception as e:
    st.warning(f'Could not load frame code sheet — frame code matching will be skipped. '
               f'({type(e).__name__}: {e})')

# ── File upload ────────────────────────────────────────────────────────────
st.markdown("### Upload schedule")
uploaded = st.file_uploader(
    "Drop a Logikhaus PDF schedule here",
    type="pdf",
    label_visibility="collapsed"
)

if uploaded:
    st.markdown("---")
    with st.spinner('Processing PDF...'):
        file_bytes = uploaded.read()
        annotated_bytes, rows, legend_status, frame_results = process_pdf(
            file_bytes, glass_lookup, frame_codes, frame_rules, glass_type_lookup
        )

    # ── Legend status feedback ──────────────────────────────────────────────
    if legend_status == 'added':
        st.markdown('<div class="status-box">✓ Legend page appended to end of quote</div>',
                     unsafe_allow_html=True)
    elif legend_status == 'already_present':
        st.markdown('<div class="status-box">Legend page already present — not duplicated</div>',
                     unsafe_allow_html=True)
    elif legend_status == 'missing_file':
        st.warning('LEGEND_page_for_Schedule.pdf not found in the app folder — legend page was not added.')

    # ── Summary table ──────────────────────────────────────────────────────
    st.markdown("### Results")
    df = pd.DataFrame([{k: v for k, v in r.items() if k != '_skip'} for r in rows])

    def highlight_row(row):
        original = rows[row.name]
        if original.get('_skip'):
            return ['color: #bbb'] * len(row)
        if 'No LHG' in str(row.get('Weight', '')) or 'skipped' in str(row.get('Weight', '')):
            return ['color: #c0392b'] * len(row)
        return [''] * len(row)

    st.dataframe(
        df.style.apply(highlight_row, axis=1),
        use_container_width=True,
        hide_index=True,
    )

    # Totals
    weights = []
    for r in rows:
        if not r['_skip'] and 'kg' in str(r['Weight']):
            try:
                weights.append(float(r['Weight'].replace(' kg', '')))
            except ValueError:
                pass

    if weights:
        col1, col2 = st.columns(2)
        col1.metric("Total glass items", len(rows))
        col2.metric("Total estimated weight", f"{sum(weights):.1f} kg")

    st.markdown("---")

    # ── Frame code results ───────────────────────────────────────────────────
    if frame_results:
        st.markdown("### Frame codes")
        frame_df = pd.DataFrame(frame_results)

        def highlight_frame_row(row):
            if row.get('Frame Code') == 'ERROR':
                return ['color: #c0392b'] * len(row)
            return [''] * len(row)

        display_df = frame_df.drop(columns=['Block Text'], errors='ignore')
        st.dataframe(
            display_df.style.apply(highlight_frame_row, axis=1),
            use_container_width=True,
            hide_index=True,
        )
        error_count = sum(1 for r in frame_results if r['Frame Code'] == 'ERROR')
        if error_count:
            st.warning(f'{error_count} window(s) could not be matched to a frame code — see Details above.')

        with st.expander("Debug: raw block text per window (what the matcher actually saw)"):
            for r in frame_results:
                st.write(f"**{r['Window']}** ({r['Frame Code']})")
                st.code(r.get('Block Text', ''), language=None)

        st.markdown("---")

    # ── Download ───────────────────────────────────────────────────────────
    st.markdown("### Download annotated PDF")
    out_name = uploaded.name.replace('.pdf', '_with_weights.pdf')
    st.download_button(
        label="Download annotated PDF",
        data=annotated_bytes,
        file_name=out_name,
        mime="application/pdf",
    )
