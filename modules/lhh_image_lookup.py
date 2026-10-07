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

BACKGROUND LOADING: the sheet read, the Drive folder walk and the image
downloads are slow, and nothing needs them until the Hardware Schedule
step. get_hardware_loader() (bottom of the SHEET/DRIVE sections) starts
all of that on a background thread the first time it's called and returns
immediately, so uploading a schedule and the first few steps can happen
while it runs. See HardwareLoader.

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
import threading
import time
from concurrent.futures import ThreadPoolExecutor

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

# Product photos in the Drive folder are much larger than the schedule
# needs (~1800 x 2400 px for a box about 22 x 30 mm, i.e. ~2000 pixels per
# inch). Each one is shrunk to this many pixels per inch AT ITS PRINTED
# SIZE before being inserted, matching the PDF download's own image
# setting in app.py (dpi_target=1000), so nothing visible is lost and the
# working document stays small. Photos already at or below this are
# inserted unchanged.
HARDWARE_IMAGE_PPI = 1000
# JPEG quality used when a shrunk photo has no transparency (matches the
# download's quality=95). Photos WITH transparency are kept as PNG, which
# is lossless, so their transparent backgrounds survive.
HARDWARE_IMAGE_JPEG_QUALITY = 95


# ═════════════════════════════════════════════════════════════════════════
#  SHEET LOOKUP
# ═════════════════════════════════════════════════════════════════════════

def _lookup_from_rows(rows):
    """
    Turn one tab's rows (a list of lists of cell strings, header row
    first) into {code: {'description': ...}}.
    Fixed column positions -- column D (index 3) for Code, column I
    (index 8) for Description -- rather than searching for those words
    in the header row, since that search wasn't reliably landing on the
    right cells. Row 1 is still assumed to be the header (skipped);
    everything from row 2 down is read as data.
    """
    if len(rows) < 2:
        return {}

    CODE_COL = 1    # column B
    DESC_COL = 6    # column G

    lookup = {}
    for row in rows[1:]:
        code = row[CODE_COL].strip() if CODE_COL < len(row) else ''
        if not code:
            continue   # blank row -- skip
        description = row[DESC_COL].strip() if DESC_COL < len(row) else ''
        lookup[code] = {'description': description}
    return lookup


def _read_lookup_from_worksheet(worksheet):
    """Read a single tab (one Sheets request) -- kept for anything that still uses it."""
    return _lookup_from_rows(worksheet.get_all_values())


def _load_lhh_lookup_uncached(creds=None):
    """
    Read EVERY tab of the LHH sheet and merge them into one combined
    {code: {'description': ...}} lookup. If the same code somehow
    appears on more than one tab, whichever tab is read last wins --
    tabs are read in the order gspread reports them (left to right, as
    shown in the sheet's own tab bar).

    Takes explicit credentials (default: build them from st.secrets) so
    the background thread can use credentials that were created on the
    main thread -- st.secrets shouldn't be touched from a worker thread.
    """
    creds = creds or get_google_credentials()
    gc = gspread.authorize(creds)
    spreadsheet = gc.open_by_key(LHH_SHEET_ID)

    # ONE request for every tab's columns A-G (values_batch_get), rather
    # than one request per tab. Google allows this app's account a limited
    # number of Sheets reads per minute, shared by everyone using the app,
    # and reading tab by tab used most of it on its own.
    titles = [ws.title for ws in spreadsheet.worksheets()]
    if not titles:
        return {}
    ranges = ["'{}'!A:G".format(title.replace("'", "''")) for title in titles]
    response = spreadsheet.values_batch_get(ranges)

    combined_lookup = {}
    for value_range in response.get('valueRanges', []):
        # An empty tab comes back with no 'values' at all.
        combined_lookup.update(_lookup_from_rows(value_range.get('values', [])))
    return combined_lookup


@st.cache_data(ttl=300)
def load_lhh_lookup():
    """Blocking, cached version -- kept for anything that still wants it."""
    return _load_lhh_lookup_uncached()


# ═════════════════════════════════════════════════════════════════════════
#  DRIVE FOLDER
# ═════════════════════════════════════════════════════════════════════════

def _drive_service(creds=None):
    """Authenticated Drive API client, shared by list/download helpers."""
    creds = creds or get_google_credentials()
    return build('drive', 'v3', credentials=creds)


def _copy_creds(creds):
    """
    A private copy of the credentials for one worker thread. Drive
    service objects (and token refreshes) aren't safe to share between
    threads, so every worker gets its own.
    """
    try:
        return creds.with_scopes(creds.scopes)
    except Exception:
        return creds


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


def _walk_drive_tree(service):
    """
    Return {filename: file_id} for every image file found ANYWHERE in
    the shared Drive folder's tree -- the folder itself, plus every
    subfolder at any depth (images are organized into subfolders like
    "LHH0"/"LHH1"/"LHH2"/"LHH3" now, rather than sitting in one flat
    folder). The service account must have the root folder shared with
    it (view access is enough, and that access extends to everything
    inside it) -- same account used for the Sheets connections.
    """
    images = {}
    folders_to_visit = [LHH_DRIVE_FOLDER_ID]

    while folders_to_visit:
        current_folder = folders_to_visit.pop()
        subfolder_ids, folder_images = _list_children(service, current_folder)
        images.update(folder_images)
        folders_to_visit.extend(subfolder_ids)

    return images


@st.cache_data(ttl=300)
def list_drive_images():
    """Blocking, cached version -- kept for anything that still wants it."""
    return _walk_drive_tree(_drive_service())


def _download_with_service(service, file_id):
    request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buffer.getvalue()


def download_drive_image(file_id, creds=None):
    """Download a single image file's raw bytes from Drive by its file ID."""
    return _download_with_service(_drive_service(creds), file_id)


def _download_many(file_ids, creds, on_done=None, workers=6):
    """
    Download several Drive files in parallel, one Drive service per
    worker thread. Returns {file_id: bytes} for the ones that worked; a
    file that fails is simply left out (the caller treats that as "no
    image for that row"). `on_done(file_id, data)` is called as each one
    finishes -- the background loader uses it to fill its cache bit by bit.
    """
    local = threading.local()

    def work(file_id):
        try:
            if not hasattr(local, 'service'):
                local.service = _drive_service(_copy_creds(creds))
            data = _download_with_service(local.service, file_id)
        except Exception:
            return file_id, None
        if on_done:
            on_done(file_id, data)
        return file_id, data

    if not file_ids:
        return {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return {fid: data for fid, data in pool.map(work, file_ids) if data}


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


def _shrink_image(image_bytes, pixmap, img_rect):
    """
    Return image bytes sized for img_rect (the box the photo is printed
    in, in points): at most HARDWARE_IMAGE_PPI pixels per inch. Returns
    the original bytes untouched if the photo is already small enough,
    or if anything goes wrong -- a full-size photo is better than none.

    pixmap is fitz.Pixmap(image_bytes), already made by the caller.
    """
    try:
        target_w = round(img_rect.width / 72 * HARDWARE_IMAGE_PPI)
        target_h = round(img_rect.height / 72 * HARDWARE_IMAGE_PPI)
        if pixmap.width <= target_w or pixmap.height <= target_h:
            return image_bytes

        small = fitz.Pixmap(pixmap, target_w, target_h)   # resample to the new size
        if small.alpha:
            return small.tobytes('png')                   # keep the transparency
        if small.colorspace and small.colorspace.n not in (1, 3):
            small = fitz.Pixmap(fitz.csRGB, small)        # e.g. CMYK -> RGB for JPEG
        return small.tobytes('jpeg', jpg_quality=HARDWARE_IMAGE_JPEG_QUALITY)
    except Exception:
        return image_bytes


def build_hardware_schedule(codes, lookup, drive_images, image_cache=None):
    """
    Build the Hardware Schedule as a standalone fitz.Document -- one or
    more pages, ROWS_PER_PAGE items per page, in the order `codes` is
    given (find_all_lhh_codes_in_doc() already sorts them).

    A code with no sheet entry still gets a row (just the code itself,
    blank description) rather than being silently dropped -- same "show
    the gap, don't hide it" principle as the Certificate Creator's
    missing-fields handling. Same for a code with no matching Drive
    image: the row just has no image rather than erroring out.

    image_cache: optional {file_id: bytes} (the background loader's
    cache). Anything already in it isn't downloaded again; whatever is
    missing is downloaded here, in parallel, and added to it.

    Returns the fitz.Document -- caller is responsible for closing it
    (or inserting its pages into another doc and then closing it).
    """
    code_to_file_id = build_code_to_file_id_map(drive_images)
    if image_cache is None:
        image_cache = {}

    missing = [code_to_file_id[c] for c in codes
               if c in code_to_file_id and code_to_file_id[c] not in image_cache]
    if missing:
        image_cache.update(_download_many(list(dict.fromkeys(missing)), get_google_credentials()))

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

        image_bytes = image_cache.get(code_to_file_id.get(code))
        if image_bytes:
            try:
                pixmap = fitz.Pixmap(image_bytes)
                img_rect = fit_image_rect(layout['image_box'], pixmap.width, pixmap.height)
                page.insert_image(img_rect, stream=_shrink_image(image_bytes, pixmap, img_rect))
            except Exception:
                pass   # unreadable image -> row just has no image

        row_index += 1

    return schedule_doc


# ═════════════════════════════════════════════════════════════════════════
#  BACKGROUND LOADER
# ═════════════════════════════════════════════════════════════════════════

LOADER_MAX_AGE     = 900   # seconds before the sheet/folder data is refreshed
# Seconds before a failed load is retried automatically. A full minute,
# because Google's Sheets read limit is per minute: retrying sooner after a
# "quota exceeded" error just uses up the next minute's allowance too.
ERROR_RETRY_AFTER  = 60
MAX_PREFETCH       = 500   # don't pre-download every image if the folder is huge


class HardwareLoader:
    """
    Loads everything the Hardware Schedule step needs on a background
    thread, in this order:

        1. the LHH sheet (code -> description)
        2. the Drive folder index (filename -> file id)      -> status 'ready'
        3. every image's bytes, in parallel (optional extra) -> prefetching

    'ready' means steps 1-2 are done, which is all the schedule step
    needs -- any image not downloaded yet is fetched on demand when the
    schedule is built. Step 3 only makes that instant.

    The thread never calls st.* and never touches st.secrets: the
    credentials are built by the caller on the main thread and handed in.
    While a REFRESH is running the previous (ready) loader stays usable
    as `fallback`, so a refresh never makes the data disappear.
    """

    def __init__(self, creds, fallback=None, prefetch=True):
        self._creds = creds
        self._fallback = fallback
        self._prefetch = prefetch
        self.status = 'loading'            # 'loading' | 'ready' | 'error'
        self.stage = 'Starting...'
        self.error = None
        self.lookup = None                 # {code: {'description': ...}}
        self.images = None                 # {filename: file_id}
        self.image_cache = dict(fallback.image_cache) if fallback else {}
        self.prefetching = False
        self.prefetch_total = 0
        self.started_at = time.time()
        self.finished_at = None
        self._thread = threading.Thread(target=self._run, daemon=True, name='hardware-loader')

    def start(self):
        self._thread.start()

    def _run(self):
        try:
            self.stage = 'reading hardware sheet'
            self.lookup = _load_lhh_lookup_uncached(_copy_creds(self._creds))
            self.stage = 'indexing Drive images'
            self.images = _walk_drive_tree(_drive_service(_copy_creds(self._creds)))
        except Exception as e:
            self.error = f'{type(e).__name__}: {e}'
            self.status = 'error'
            self.finished_at = time.time()
            return
        self.status = 'ready'
        self.stage = 'ready'
        self.finished_at = time.time()
        self._fallback = None              # new data is live -- release the old copy
        if self._prefetch:
            self._prefetch_images()

    def _prefetch_images(self):
        ids = list(dict.fromkeys(build_code_to_file_id_map(self.images).values()))
        ids = [i for i in ids if i not in self.image_cache]
        if not ids or len(ids) > MAX_PREFETCH:
            return
        self.prefetch_total = len(self.image_cache) + len(ids)
        self.prefetching = True
        try:
            _download_many(ids, self._creds, on_done=self.image_cache.__setitem__)
        except Exception:
            pass                           # prefetch is best-effort only
        finally:
            self.prefetching = False

    def _live(self):
        """Whichever loader currently has usable data (self, else the old one), or None."""
        if self.status == 'ready':
            return self
        fb = self._fallback
        return fb if fb is not None and fb.status == 'ready' else None

    def data(self):
        """(lookup, images, image_cache) once usable, otherwise None."""
        live = self._live()
        return (live.lookup, live.images, live.image_cache) if live else None

    def snapshot(self):
        """Plain dict for the UI -- safe to read at any moment."""
        live = self._live()
        return {
            'status': self.status,
            'ready': live is not None,
            'stage': self.stage,
            'error': self.error,
            'codes': len(live.lookup) if live else 0,
            'images': len(live.images) if live else 0,
            'prefetching': self.prefetching,
            'cached': len(self.image_cache),
            'prefetch_total': self.prefetch_total,
        }


_loader = None
_loader_lock = threading.Lock()


def get_hardware_loader(force=False):
    """
    The one shared loader. The first call starts loading in the background
    and returns straight away; later calls just return the same object
    (until its data is LOADER_MAX_AGE old, or it failed ERROR_RETRY_AFTER
    seconds ago, or force=True -- then a fresh load starts).

    Must be called from the Streamlit script (main) thread, because that's
    where the credentials get built from st.secrets.
    """
    global _loader
    with _loader_lock:
        ld = _loader
        stale = (
            ld is not None and ld.finished_at is not None and
            time.time() - ld.finished_at > (ERROR_RETRY_AFTER if ld.status == 'error' else LOADER_MAX_AGE)
        )
        if ld is None or stale or force:
            fallback = None
            if ld is not None:
                fallback = ld if ld.status == 'ready' else ld._live()
                ld._fallback = None if ld is not fallback else ld._fallback
            _loader = HardwareLoader(get_google_credentials(), fallback=fallback)
            _loader.start()
        return _loader
