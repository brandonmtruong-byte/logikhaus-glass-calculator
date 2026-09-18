"""
LHH HARDWARE SCHEDULE
Scans the working document for every LHH### code mentioned anywhere on
it, looks each one up in the LHH lookup sheet, finds its matching image
in the shared Drive folder, and builds a Hardware Schedule (using
hardware_schedule_layout.py's template) that gets appended to the end
of the document -- see modules/steps.py's apply_hardware_schedule(),
which runs this as the step right before Legend in the stepper.

Sheet layout: the sheet now has MULTIPLE TABS (one per hardware
category, e.g. "LH1 window hinges", "LH2 swing doors"...) -- every tab
is read and merged into one combined lookup. Row 1 is each tab's own
header row; columns are found by matching header text ("Code" / column
D, "Description" / column I in the current layout), not a hardcoded
column letter, so it doesn't matter which literal column they're in as
long as row 1 has those labels somewhere on it. A tab with no "Code"
header at all is skipped entirely (not every tab may follow this
format). Only Code and Description are read -- Hardware/Type/Brand/
Name/Colour/Image columns are ignored, since Description is already a
complete, pre-composed value in the sheet itself.

Drive folder: images now live in a NESTED folder structure (subfolders
like "LHH0", "LHH1", "black set"...) rather than one flat folder, so
the whole tree is walked recursively -- every image found at any depth,
plus any sitting loose in the root folder itself. Filename matching is
unchanged: the LHH### pattern is matched at the start of the filename,
independent of subfolder location or naming (underscore- or
space-separated, or no separator at all).
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


# ═════════════════════════════════════════════════════════════════════════
#  SHEET LOOKUP
# ═════════════════════════════════════════════════════════════════════════

def _read_lookup_from_worksheet(worksheet):
    """
    Read a single tab and return {code: {'description': ...}} from it.
    Fixed column positions -- column D (index 3) for Code, column I
    (index 8) for Description -- rather than searching for those words
    in the header row, since that search wasn't reliably landing on the
    right cells. Row 1 is still assumed to be the header (skipped);
    everything from row 2 down is read as data.
    """
    rows = worksheet.get_all_values()
    if len(rows) < 2:
        return {}

    CODE_COL = 3    # column D
    DESC_COL = 8    # column I

    lookup = {}
    for row in rows[1:]:
        code = row[CODE_COL].strip() if CODE_COL < len(row) else ''
        if not code:
            continue   # blank row -- skip
        description = row[DESC_COL].strip() if DESC_COL < len(row) else ''
        lookup[code] = {'description': description}
    return lookup


@st.cache_data(ttl=300)
def load_lhh_lookup():
    """
    Read EVERY tab of the LHH sheet and merge them into one combined
    {code: {'description': ...}} lookup. If the same code somehow
    appears on more than one tab, whichever tab is read last wins --
    tabs are read in the order gspread reports them (left to right, as
    shown in the sheet's own tab bar).
    """
    creds = get_google_credentials()
    gc = gspread.authorize(creds)
    spreadsheet = gc.open_by_key(LHH_SHEET_ID)

    combined_lookup = {}
    for worksheet in spreadsheet.worksheets():
        combined_lookup.update(_read_lookup_from_worksheet(worksheet))
    return combined_lookup


# ═════════════════════════════════════════════════════════════════════════
#  DRIVE FOLDER
# ═════════════════════════════════════════════════════════════════════════

def _drive_service():
    """Authenticated Drive API client, shared by list/download helpers."""
    creds = get_google_credentials()
    return build('drive', 'v3', credentials=creds)


def _list_children(service, folder_id):
    """
    One folder's direct children (not recursive) -- both subfolders and
    image files, since the real folder can have both at the same level
    (e.g. some loose images sitting alongside the "LHH0"/"LHH1"/...
    subfolders in the root). Returns (subfolder_ids, {filename: file_id}).
    """
    query = f"'{folder_id}' in parents and trashed = false"
    subfolder_ids = []
    images = {}
    page_token = None
    while True:
        response = service.files().list(
            q=query,
            fields="nextPageToken, files(id, name, mimeType)",
            pageToken=page_token,
            # LOCAL CHANGE: without these two flags, files.list() silently
            # excludes anything living in a Shared Drive (a Workspace Team
            # Drive) -- returns zero results with no error, which is very
            # likely why images weren't coming through at all despite the
            # folder structure and sharing being otherwise correct. Safe
            # to leave set even if this ISN'T a Shared Drive -- harmless
            # no-op for regular "My Drive" folders.
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()
        for f in response.get('files', []):
            if f['mimeType'] == 'application/vnd.google-apps.folder':
                subfolder_ids.append(f['id'])
            elif f['mimeType'].startswith('image/'):
                images[f['name']] = f['id']
        page_token = response.get('nextPageToken')
        if not page_token:
            break
    return subfolder_ids, images


@st.cache_data(ttl=300)
def list_drive_images():
    """
    Return {filename: file_id} for every image file found ANYWHERE in
    the shared Drive folder's tree -- the folder itself, plus every
    subfolder at any depth (images are organized into subfolders like
    "LHH0"/"LHH1"/"LHH2"/"LHH3" now, rather than sitting in one flat
    folder). The service account must have the root folder shared with
    it (view access is enough, and that access extends to everything
    inside it) -- same account used for the Sheets connections.
    """
    service = _drive_service()
    images = {}
    folders_to_visit = [LHH_DRIVE_FOLDER_ID]

    while folders_to_visit:
        current_folder = folders_to_visit.pop()
        subfolder_ids, folder_images = _list_children(service, current_folder)
        images.update(folder_images)
        folders_to_visit.extend(subfolder_ids)

    return images


def download_drive_image(file_id):
    """Download a single image file's raw bytes from Drive by its file ID."""
    service = _drive_service()
    request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buffer.getvalue()


def build_code_to_file_id_map(drive_images):
    """
    {filename: file_id} -> {code: file_id}, extracted by regex-matching
    the LHH### pattern at the START of each filename -- not by splitting
    on a specific delimiter. Filenames in the wild have used both
    underscores ("LHH001_Roto_non-keyed.png") and spaces
    ("LHH001 Roto non-keyed R01.1.png"); matching the code pattern
    directly works for either without caring which separator (if any)
    follows it. There's exactly one image per code, so the first match
    for a given code wins if the folder somehow has more than one file
    with the same prefix. A file with no LHH### prefix at all (e.g. a
    loose, not-yet-sorted image) simply doesn't match anything here.
    """
    code_map = {}
    for filename, file_id in drive_images.items():
        match = re.match(LHH_CODE_PATTERN, filename, re.IGNORECASE)
        if match:
            code = match.group(0).upper()
            if code not in code_map:
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
    blank description) rather than being silently dropped -- same "show
    the gap, don't hide it" principle as the Certificate Creator's
    missing-fields handling. Same for a code with no matching Drive
    image: the row just has no image rather than erroring out.

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
