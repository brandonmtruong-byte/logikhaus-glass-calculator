"""
LHH HARDWARE SCHEDULE
Scans the working document for every LHH### code mentioned anywhere on
it, looks each one up in the LHH lookup sheet, finds its matching image
in the shared Drive folder, and builds a Hardware Schedule (using
hardware_schedule_layout.py's template) that gets appended to the end
of the document -- see modules/steps.py's apply_hardware_schedule(),
which runs this as the step right before Legend in the stepper.

Sheet layout (row 1 is always the header; confirmed fixed, no guide
rows above it):
    Code | Names | Colour | Description
Columns are found by matching the header text, not by a hardcoded
column letter, so it doesn't matter which literal spreadsheet column
each one lives in as long as row 1 has these exact labels somewhere on
it. Rows where the Code cell is blank are skipped.

Drive folder: one image per code, filename is "<CODE>_<anything>.ext"
-- only the part before the first underscore is used to match a code;
everything after it (and the file extension) is ignored.
"""

import io
import re

import streamlit as st
import gspread
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import fitz

from .config import get_google_credentials
from .hardware_schedule_layout import (
    row_rects_for_page, fit_image_rect, ROWS_PER_PAGE, PAGE_WIDTH, PAGE_HEIGHT,
    HEADER_HEIGHT, TABLE_TOP_Y, COL_HEADER_H, MARGIN_X, COL1_X0, COL2_X0, COL3_X0,
)

# ── Config (kept local to this module -- nothing else needs these) ─────────
LHH_SHEET_ID        = '17j8CUbiV_w-wFTaEGIjN-BM-iaOrfb3a8UBZJMfWjVU'
LHH_DRIVE_FOLDER_ID = '11gVQL1K1xrCm7j_UB7R_NqK63wqZTRtH'

LHH_CODE_PATTERN = r'LHH\d+'

HEADER_COLUMN_NAMES = {
    'code':        'code',
    'name':        'names',
    'colour':      'colour',
    'description': 'description',
}


# ═════════════════════════════════════════════════════════════════════════
#  SHEET LOOKUP
# ═════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=300)
def load_lhh_lookup():
    """
    Read the LHH sheet and return {code: {'name', 'colour', 'description'}}.

    Row 1 is the header -- columns are matched by their header text
    (case-insensitive), not a fixed column letter, so "Code"/"Names"/
    "Colour"/"Description" can live in any column as long as they're
    somewhere in row 1. Rows with a blank Code cell are skipped.
    """
    creds = get_google_credentials()
    gc = gspread.authorize(creds)
    ws = gc.open_by_key(LHH_SHEET_ID).sheet1
    rows = ws.get_all_values()
    if not rows:
        return {}

    header = [cell.strip().lower() for cell in rows[0]]
    col_index = {}
    for key, header_name in HEADER_COLUMN_NAMES.items():
        if header_name in header:
            col_index[key] = header.index(header_name)

    if 'code' not in col_index:
        return {}   # header row doesn't have a "Code" column at all -- nothing to read

    lookup = {}
    for row in rows[1:]:
        def cell(key):
            idx = col_index.get(key)
            return row[idx].strip() if idx is not None and idx < len(row) else ''

        code = cell('code')
        if not code:
            continue   # blank row -- skip
        lookup[code] = {
            'name':        cell('name'),
            'colour':      cell('colour'),
            'description': cell('description'),
        }
    return lookup


# ═════════════════════════════════════════════════════════════════════════
#  DRIVE FOLDER
# ═════════════════════════════════════════════════════════════════════════

def _drive_service():
    """Authenticated Drive API client, shared by list/download helpers."""
    creds = get_google_credentials()
    return build('drive', 'v3', credentials=creds)


@st.cache_data(ttl=300)
def list_drive_images():
    """
    Return {filename: file_id} for every image file in the shared Drive
    folder. The service account must have the folder shared with it
    (view access is enough) -- same account used for the Sheets
    connections.
    """
    service = _drive_service()
    query = (
        f"'{LHH_DRIVE_FOLDER_ID}' in parents "
        f"and mimeType contains 'image/' and trashed = false"
    )
    images = {}
    page_token = None
    while True:
        response = service.files().list(
            q=query,
            fields="nextPageToken, files(id, name)",
            pageToken=page_token,
        ).execute()
        for f in response.get('files', []):
            images[f['name']] = f['id']
        page_token = response.get('nextPageToken')
        if not page_token:
            break
    return images


def download_drive_image(file_id):
    """Download a single image file's raw bytes from Drive by its file ID."""
    service = _drive_service()
    request = service.files().get_media(fileId=file_id)
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buffer.getvalue()


def build_code_to_file_id_map(drive_images):
    """
    {filename: file_id} -> {code: file_id}, matching on the part of each
    filename before its first underscore (e.g. "LHH001_Roto_non-keyed.png"
    -> code "LHH001"). Everything after the first underscore, including
    the extension, is ignored -- there's exactly one image per code, so
    the first match for a given code wins if the folder somehow has more
    than one file with the same prefix.
    """
    code_map = {}
    for filename, file_id in drive_images.items():
        code = filename.split('_', 1)[0]
        if code and code not in code_map:
            code_map[code] = file_id
    return code_map


# ═════════════════════════════════════════════════════════════════════════
#  CODE EXTRACTION
# ═════════════════════════════════════════════════════════════════════════

def extract_lhh_codes(text):
    """Find every LHH### code mentioned in a chunk of text."""
    return re.findall(LHH_CODE_PATTERN, text)


def find_all_lhh_codes_in_doc(doc):
    """
    Scan every page of the working document for LHH codes and return the
    sorted, de-duplicated list -- the schedule shows each code once,
    regardless of how many times it's mentioned across the document.
    """
    codes = set()
    for page in doc:
        codes.update(extract_lhh_codes(page.get_text()))
    return sorted(codes)


# ═════════════════════════════════════════════════════════════════════════
#  SCHEDULE GENERATION
# ═════════════════════════════════════════════════════════════════════════

def _new_schedule_page(doc):
    """
    Add one fresh Hardware Schedule page (header band + column labels +
    empty row grid) to `doc`, matching hardware_schedule_template.pdf's
    design exactly but drawn directly rather than requiring that file to
    exist on disk -- keeps this module self-contained.
    """
    page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)

    page.draw_rect(fitz.Rect(0, 0, PAGE_WIDTH, HEADER_HEIGHT), color=None, fill=(0.63, 0.20, 0.21))
    page.insert_text((MARGIN_X, 45), 'Logikhaus', fontsize=22, fontname='hebo', color=(1, 1, 1))
    page.insert_text((MARGIN_X, 68), 'Hardware Schedule', fontsize=11, fontname='helv', color=(1, 1, 1))

    header_y = TABLE_TOP_Y
    page.draw_rect(
        fitz.Rect(MARGIN_X, header_y, PAGE_WIDTH - MARGIN_X, header_y + COL_HEADER_H),
        color=(0.63, 0.20, 0.21), fill=(0.97, 0.94, 0.94), width=1,
    )
    page.insert_text((COL1_X0 + 6, header_y + 15), 'Code', fontsize=10, fontname='hebo', color=(0.2, 0.2, 0.2))
    page.insert_text((COL2_X0 + 6, header_y + 15), 'Image', fontsize=10, fontname='hebo', color=(0.2, 0.2, 0.2))
    page.insert_text((COL3_X0 + 6, header_y + 15), 'Description', fontsize=10, fontname='hebo', color=(0.2, 0.2, 0.2))

    rows = row_rects_for_page()
    for row in rows:
        r = row['row_rect']
        page.draw_rect(r, color=(0.7, 0.7, 0.7), width=0.75)
        page.draw_line((COL2_X0, r.y0), (COL2_X0, r.y1), color=(0.7, 0.7, 0.7), width=0.75)
        page.draw_line((COL3_X0, r.y0), (COL3_X0, r.y1), color=(0.7, 0.7, 0.7), width=0.75)

    return page, rows


def build_hardware_schedule(codes, lookup, drive_images):
    """
    Build the Hardware Schedule as a standalone fitz.Document -- one or
    more pages, ROWS_PER_PAGE items per page, in the order `codes` is
    given (find_all_lhh_codes_in_doc() already sorts them).

    A code with no sheet entry still gets a row (just the code itself,
    blank name/colour/description) rather than being silently dropped --
    same "show the gap, don't hide it" principle as the Certificate
    Creator's missing-fields handling. Same for a code with no matching
    Drive image: the row just has no image rather than erroring out.

    Returns the fitz.Document -- caller is responsible for closing it
    (or inserting its pages into another doc and then closing it).
    """
    code_to_file_id = build_code_to_file_id_map(drive_images)
    schedule_doc = fitz.open()

    page, rows = _new_schedule_page(schedule_doc)
    row_index = 0

    for code in codes:
        if row_index >= ROWS_PER_PAGE:
            page, rows = _new_schedule_page(schedule_doc)
            row_index = 0

        layout = rows[row_index]
        info = lookup.get(code, {})

        page.insert_text(layout['code_origin'], code, fontsize=10, fontname='hebo', color=(0, 0, 0))
        if info.get('name'):
            page.insert_text(layout['name_origin'], info['name'], fontsize=8, fontname='helv', color=(0.2, 0.2, 0.2))

        if info.get('colour'):
            page.insert_text(layout['colour_origin'], info['colour'], fontsize=8, fontname='hebo', color=(0, 0, 0))
        if info.get('description'):
            page.insert_textbox(
                layout['description_rect'], info['description'],
                fontsize=8, fontname='helv', color=(0.2, 0.2, 0.2),
            )

        file_id = code_to_file_id.get(code)
        if file_id:
            image_bytes = download_drive_image(file_id)
            pixmap = fitz.Pixmap(image_bytes)
            img_rect = fit_image_rect(layout['image_box'], pixmap.width, pixmap.height)
            page.insert_image(img_rect, stream=image_bytes)

        row_index += 1

    return schedule_doc
