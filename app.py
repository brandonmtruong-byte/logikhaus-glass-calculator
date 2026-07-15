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

            # Glass line — only use code if exactly one LHG code present
            if full_text.startswith('Glass:') or full_text.startswith('glass:'):
                lhg_matches    = re.findall(r'LHG\d+', full_text)
                lhg_code_found = lhg_matches[0] if len(lhg_matches) == 1 else None
                last           = spans[-1]
                bbox           = last['bbox']
                glass_lines.append({
                    'y_mid':     (bbox[1] + bbox[3]) / 2,
                    'y_base':    bbox[1] + last['size'] * 0.85,
                    'font_size': last['size'],
                    'lhg_code':  lhg_code_found,
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
    Given one glass line matched to one size entry, compute weight (if possible),
    stamp the weight label onto the page, and return a result row (dict) for the table.
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

    area     = (w / 1000) * (h / 1000)
    lhg_code = glass_line['lhg_code']

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

    # Multiple codes or unrecognised code — no annotation written to PDF
    return {
        'Size':      f'{w} × {h} mm',
        'LHG Code':  lhg_code or 'Multiple codes — skipped',
        'Thickness': '—',
        'Area (m²)': f'{area:.3f}',
        'Weight':    'No LHG match' if lhg_code else 'Multiple codes — skipped',
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
#  ORCHESTRATOR — runs the three modules above, in order, on the uploaded PDF
# ═════════════════════════════════════════════════════════════════════════

def process_pdf(file_bytes, glass_lookup):
    doc     = fitz.open(stream=file_bytes, filetype="pdf")
    results = []

    for page_num, page in enumerate(doc):
        if page_num == 0:
            stamp_logo(page)                                        # Module 1
        results.extend(process_glass_weights(page, glass_lookup))   # Module 2

    legend_status = append_legend_page(doc)                         # Module 3

    out_bytes = doc.tobytes()
    doc.close()
    return out_bytes, results, legend_status


# ═════════════════════════════════════════════════════════════════════════
#  STREAMLIT UI
# ═════════════════════════════════════════════════════════════════════════

# ── Load glass lookup ──────────────────────────────────────────────────────
try:
    with st.spinner('Loading glass data from sheet...'):
        glass_lookup = load_glass_lookup()
    st.markdown(f'<div class="status-box">✓ Glass database loaded — {len(glass_lookup)} codes</div>',
                unsafe_allow_html=True)
except Exception as e:
    st.error(f'Could not connect to Google Sheets: {type(e).__name__}: {e}')
    import traceback
    st.code(traceback.format_exc())
    st.stop()

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
        annotated_bytes, rows, legend_status = process_pdf(file_bytes, glass_lookup)

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

    # ── Download ───────────────────────────────────────────────────────────
    st.markdown("### Download annotated PDF")
    out_name = uploaded.name.replace('.pdf', '_with_weights.pdf')
    st.download_button(
        label="Download annotated PDF",
        data=annotated_bytes,
        file_name=out_name,
        mime="application/pdf",
    )
