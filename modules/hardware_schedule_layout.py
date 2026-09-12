"""
HARDWARE SCHEDULE -- template layout constants
Companion to hardware_schedule_template.pdf. That file is deliberately
just borders/header/column labels -- no placeholder content -- since
the actual fill-in code (modules/lhh_image_lookup.py) inserts real
images/text directly onto it via page.insert_image()/insert_text().

Three columns per row:
  1. Code + Name, stacked (two separate lines, e.g. "LHH001" / "Roto
     non-keyed R01.1")
  2. Image
  3. Colour + Description, stacked (two separate lines, e.g. "Anodised
     silver F1" / whatever's in the sheet's Description column -- often
     blank today, and that's fine, it just renders as an empty line)

Usage sketch:

    import fitz
    from hardware_schedule_layout import row_rects_for_page, fit_image_rect, ROWS_PER_PAGE

    for row_index, item in enumerate(page_items):   # up to ROWS_PER_PAGE items
        layout = row_rects_for_page()[row_index]
        page.insert_text(layout['code_origin'], item['code'], fontsize=10, fontname='hebo')
        page.insert_text(layout['name_origin'], item['name'], fontsize=8, fontname='helv')
        page.insert_text(layout['colour_origin'], item['colour'], fontsize=8, fontname='hebo')
        page.insert_textbox(layout['description_rect'], item['description'], fontsize=8, fontname='helv')
        if item.get('image_bytes'):
            img_rect = fit_image_rect(layout['image_box'], item['image_width'], item['image_height'])
            page.insert_image(img_rect, stream=item['image_bytes'])
"""

import fitz

PAGE_WIDTH  = 595
PAGE_HEIGHT = 842   # A4

MARGIN_X       = 40
HEADER_HEIGHT  = 90     # logo + title band
TABLE_TOP_Y    = 120    # where the column-header row starts
COL_HEADER_H   = 22
ROW_HEIGHT     = 110    # each hardware item's row
ROWS_PER_PAGE  = 6

COL1_X0 = MARGIN_X            # Code + Name
COL1_W  = 130
COL2_X0 = COL1_X0 + COL1_W    # Image
COL2_W  = 110
COL3_X0 = COL2_X0 + COL2_W    # Colour + Description
COL3_W  = PAGE_WIDTH - MARGIN_X - COL3_X0

IMAGE_PAD = 8   # inset so a photo doesn't touch the row's/column's border


def row_rects_for_page():
    """
    Returns a list of ROWS_PER_PAGE dicts (index 0 = top row of the
    page), each with:
        'row_rect'          : fitz.Rect of the whole row (reference/debug)
        'code_origin'       : (x, y) for a single-line page.insert_text() call
        'name_origin'       : (x, y) likewise, sits just below code_origin
        'image_box'         : fitz.Rect -- the AVAILABLE space for the
                               image, not the final placement. Pass this
                               into fit_image_rect() to get the actual
                               rect to insert_image() with, since the
                               real placement depends on that specific
                               image's own aspect ratio.
        'colour_origin'     : (x, y) for a single-line page.insert_text() call
        'description_rect'  : fitz.Rect -- pass to page.insert_textbox()
                               for wrapping (description length varies
                               a lot, from blank to multiple sentences)
    Identical for every page -- each new page starts this same sequence
    over again from row 0.
    """
    rows = []
    for i in range(ROWS_PER_PAGE):
        row_y0 = TABLE_TOP_Y + COL_HEADER_H + i * ROW_HEIGHT
        row_y1 = row_y0 + ROW_HEIGHT
        row_rect = fitz.Rect(MARGIN_X, row_y0, PAGE_WIDTH - MARGIN_X, row_y1)

        image_box = fitz.Rect(
            COL2_X0 + IMAGE_PAD, row_y0 + IMAGE_PAD,
            COL2_X0 + COL2_W - IMAGE_PAD, row_y1 - IMAGE_PAD,
        )

        rows.append({
            'row_rect':         row_rect,
            'code_origin':      (COL1_X0 + 8, row_y0 + 22),
            'name_origin':      (COL1_X0 + 8, row_y0 + 40),
            'image_box':        image_box,
            'colour_origin':    (COL3_X0 + 8, row_y0 + 22),
            'description_rect': fitz.Rect(COL3_X0 + 8, row_y0 + 30,
                                           PAGE_WIDTH - MARGIN_X - 8, row_y1 - 8),
        })
    return rows


def fit_image_rect(box, native_width, native_height):
    """
    "Contain" scaling: the largest rect that (a) preserves the image's
    real aspect ratio, (b) fits entirely inside `box` on both axes, and
    (c) is centered within `box`. Never crops, never stretches/distorts.

    For a typical tall/narrow hardware photo (most product shots are
    portrait), this ends up height-bound -- the image fills the row's
    available height, with empty space left/right rather than top/bottom.
    A very wide/short image would instead end up width-bound. Either way
    nothing overflows the cell and nothing gets distorted.
    """
    box_w, box_h = box.width, box.height
    scale = min(box_w / native_width, box_h / native_height)
    final_w = native_width * scale
    final_h = native_height * scale

    x0 = box.x0 + (box_w - final_w) / 2
    y0 = box.y0 + (box_h - final_h) / 2
    return fitz.Rect(x0, y0, x0 + final_w, y0 + final_h)
