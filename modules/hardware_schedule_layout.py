"""
HARDWARE SCHEDULE -- template layout constants
Companion to hardware_schedule_template.pdf. That file is deliberately
just borders/header/column labels -- no placeholder content -- since
future code (the LHH image lookup work) inserts real images/text
directly onto it via page.insert_image()/page.insert_text(). These
constants are the exact coordinates that code needs, so positions never
have to be re-derived or eyeballed from the PDF itself.

Usage sketch for whoever builds the actual fill-in logic later:

    import fitz
    from hardware_schedule_layout import row_rects_for_page, ROWS_PER_PAGE

    doc = fitz.open("hardware_schedule_template.pdf")
    items = [...]  # one dict per hardware item: {'code', 'image_bytes', 'description'}

    for page_num, page_items in enumerate(chunked(items, ROWS_PER_PAGE)):
        if page_num > 0:
            doc.insert_pdf(fitz.open("hardware_schedule_template.pdf"))
        page = doc[page_num]
        for row_index, item in enumerate(page_items):
            layout = row_rects_for_page()[row_index]
            page.insert_image(layout['image_rect'], stream=item['image_bytes'])
            page.insert_text(layout['code_origin'], item['code'], fontsize=9, fontname='helv')
            page.insert_textbox(
                fitz.Rect(layout['text_origin'][0], layout['row_rect'].y0 + 8,
                          PAGE_WIDTH - MARGIN_X - 8, layout['row_rect'].y1 - 8),
                item['description'], fontsize=9, fontname='helv',
            )
"""

import fitz

PAGE_WIDTH  = 595
PAGE_HEIGHT = 842   # A4

MARGIN_X       = 40
HEADER_HEIGHT  = 90     # logo + title band
TABLE_TOP_Y    = 120    # where the column-header row starts
COL_HEADER_H   = 22
ROW_HEIGHT     = 100    # each hardware item's row
ROWS_PER_PAGE  = 6

COL_CODE_X0  = MARGIN_X
COL_CODE_W   = 70
COL_IMAGE_X0 = COL_CODE_X0 + COL_CODE_W
COL_IMAGE_W  = 90
COL_DESC_X0  = COL_IMAGE_X0 + COL_IMAGE_W
COL_DESC_W   = PAGE_WIDTH - MARGIN_X - COL_DESC_X0

IMAGE_PAD = 8   # inset so a photo doesn't touch the row's border


def row_rects_for_page():
    """
    Returns a list of ROWS_PER_PAGE dicts (index 0 = top row of the
    page), each with:
        'row_rect'    : fitz.Rect of the whole row (for reference/debug)
        'image_rect'  : fitz.Rect to pass directly to page.insert_image()
        'text_origin' : (x, y) -- left edge of the description column,
                        y is the row's top; build your own text box down
                        from here with page.insert_textbox() for wrapping
        'code_origin' : (x, y) -- vertically centered in the row, for a
                        single-line page.insert_text() call
    Identical for every page -- each new page starts this same sequence
    over again from row 0.
    """
    rows = []
    for i in range(ROWS_PER_PAGE):
        row_y0 = TABLE_TOP_Y + COL_HEADER_H + i * ROW_HEIGHT
        row_y1 = row_y0 + ROW_HEIGHT
        row_rect = fitz.Rect(MARGIN_X, row_y0, PAGE_WIDTH - MARGIN_X, row_y1)
        image_rect = fitz.Rect(
            COL_IMAGE_X0 + IMAGE_PAD, row_y0 + IMAGE_PAD,
            COL_IMAGE_X0 + COL_IMAGE_W - IMAGE_PAD, row_y1 - IMAGE_PAD,
        )
        rows.append({
            'row_rect':    row_rect,
            'image_rect':  image_rect,
            'text_origin': (COL_DESC_X0 + 8, row_y0 + 18),
            'code_origin': (COL_CODE_X0 + 8, row_y0 + ROW_HEIGHT / 2),
        })
    return rows
