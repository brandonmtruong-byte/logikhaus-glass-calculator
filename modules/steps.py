"""
STEP APPLY FUNCTIONS — interactive stepper flow
Each function here applies exactly one existing module to the whole
working document and returns whatever the UI needs to show as a result:
a list of table rows, a status string, or None if there's nothing to
preview as a table (e.g. the logo step, which app.py previews as an
image instead).

None of the underlying modules (logo_stamper, glass_weight, etc.) had to
change — these are just per-page loops wired around their existing
functions, same as modules/pipeline.py already does for the "process
everything at once" flow. pipeline.py is left untouched and still works
if you ever want a non-interactive batch mode again.

STEP_ORDER and STEP_LABELS drive the stepper in app.py.

To add a new step to the flow:
  1. Write an apply_xxx(doc, ...) function here.
  2. Add its key to STEP_ORDER and a label to STEP_LABELS.
  3. Add one block in app.py's step-rendering section to call it and
     show its result — follow the shape of the existing steps.
"""

from .logo_stamper import stamp_logo
from .glass_weight import process_glass_weights
from .frame_code_matcher import process_frame_codes, group_rules_by_category
from .legend_page import append_legend_page
from .schedule_editor import apply_text_replace
from .lhh_image_lookup import find_all_lhh_codes_in_doc, load_lhh_lookup, list_drive_images, build_hardware_schedule

STEP_ORDER = ['logo', 'text_replace', 'mass', 'frame', 'hardware_schedule', 'legend']

STEP_LABELS = {
    'logo':              'Logo Stamp',
    'text_replace':      'Schedule Text Editor',
    'mass':              'Glass Weight Calculator',
    'frame':             'Frame Code Matcher',
    'hardware_schedule': 'Hardware Schedule',
    'legend':            'Legend Page',
}


def apply_logo(doc):
    """Stamp the logo onto page 1. No table result — app.py shows a page-1 image preview instead."""
    if len(doc) > 0:
        stamp_logo(doc[0])


def apply_mass(doc, glass_lookup):
    """
    Run the glass weight calculator over every page.
    Returns {'rows': combined result rows, 'pages': sorted list of page
    numbers (1-indexed) that had at least one glass line, 'highlight_rects':
    {page_num: [rects]} for every stamp actually written} so the UI can
    render an image preview of just the affected pages, with highlights.
    """
    rows = []
    pages = []
    highlight_rects = {}
    for i, page in enumerate(doc, start=1):
        page_rows = process_glass_weights(page, glass_lookup)
        if page_rows:
            pages.append(i)
        rects = [r['_highlight_rect'] for r in page_rows if r.get('_highlight_rect')]
        if rects:
            highlight_rects[i] = rects
        rows.extend(page_rows)
    return {'rows': rows, 'pages': pages, 'highlight_rects': highlight_rects}


def apply_frame(doc, frame_codes, frame_rules, glass_type_lookup):
    """
    Run the frame code matcher over every page.
    Returns {'rows': combined result rows, 'pages': sorted list of page
    numbers (1-indexed) that had at least one window, 'highlight_rects':
    {page_num: [rects]} for every stamp actually written} so the UI can
    render an image preview of just the affected pages, with highlights.
    """
    rules_by_category = group_rules_by_category(frame_rules)
    rows = []
    pages = []
    highlight_rects = {}
    for i, page in enumerate(doc, start=1):
        page_rows = process_frame_codes(page, frame_codes, rules_by_category, glass_type_lookup)
        if page_rows:
            pages.append(i)
        rects = [r['_highlight_rect'] for r in page_rows if r.get('_highlight_rect')]
        if rects:
            highlight_rects[i] = rects
        rows.extend(page_rows)
    return {'rows': rows, 'pages': pages, 'highlight_rects': highlight_rects}


def apply_hardware_schedule(doc):
    """
    Scan the whole working document for LHH### codes, look each one up
    (sheet + Drive image), and append the resulting Hardware Schedule
    pages to the end of `doc`. Runs after Frame Codes and before Legend,
    so the schedule ends up sandwiched between the annotated
    schedule/quote content and the Legend page that gets appended after
    it.

    Returns {'codes': sorted list of codes found, 'pages_added': int}
    for the UI to show as a result -- there's no per-item "rows" table
    the way Mass/Frame have, since the generated pages themselves ARE
    the output to review (via the page-image preview toggle, same
    pattern as the other steps).
    """
    codes = find_all_lhh_codes_in_doc(doc)
    if not codes:
        return {'codes': [], 'pages_added': 0}

    lookup = load_lhh_lookup()
    drive_images = list_drive_images()

    schedule_doc = build_hardware_schedule(codes, lookup, drive_images)
    pages_added = schedule_doc.page_count
    doc.insert_pdf(schedule_doc)
    schedule_doc.close()

    return {'codes': codes, 'pages_added': pages_added}


def apply_legend(doc):
    """Append the legend page if it's missing. Returns the status string ('added' / 'already_present' / 'missing_file')."""
    return append_legend_page(doc)
