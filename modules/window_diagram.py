"""
WINDOW DIAGRAM
Draws a to-scale window/door diagram from width/height in mm: a frame
rectangle with an inset glass pane, plus dimension lines (width along
the bottom, height along the right) showing the actual numbers.

Pure vector drawing (fitz/PyMuPDF, the same library used everywhere
else in this project) rather than any raster/tiling approach -- see the
Window Diagram Creator tab's own discussion for why. The key property
this guarantees: aspect ratio is always EXACT, never approximate. One
scale factor is computed from width_mm/height_mm and applied uniformly
to both axes, so the drawn rectangle's proportions always exactly match
the real window's, by construction -- there's no code path that could
distort it.
"""

import fitz

# ── Layout constants ────────────────────────────────────────────────────
MAX_DRAWING_W = 400   # available space for the window graphic itself, in points
MAX_DRAWING_H = 220
MARGIN_LEFT   = 30
MARGIN_TOP    = 30
DIM_GAP       = 25    # gap between the drawing and its dimension line
DIM_TICK      = 8     # length of the little end-ticks on dimension lines
LABEL_FONTSIZE = 16

FRAME_THICKNESS_RATIO = 0.045   # frame border as a fraction of the shorter side
FRAME_COLOR = (0.91, 0.82, 0.63)   # tan
GLASS_COLOR = (0.75, 0.24, 0.62)   # magenta, matching the reference image


def draw_window_diagram(width_mm, height_mm, frame_color=FRAME_COLOR, glass_color=GLASS_COLOR, dpi=100):
    """
    Returns PNG bytes for a to-scale window diagram.

    width_mm, height_mm: the real window dimensions. Must both be > 0.
    frame_color, glass_color: RGB tuples, each channel 0-1 (fitz's
        convention), overridable per call if a specific job needs
        different colours than the defaults.
    dpi: rasterization resolution for the returned PNG -- controls
        actual image QUALITY (how many real pixels get drawn), not
        display size. Keep this high; control how big the diagram
        appears on screen separately, via st.image()'s width= in
        app.py, which just scales a crisp high-res image down rather
        than generating a genuinely lower-resolution (blurrier) one.
    """
    if width_mm <= 0 or height_mm <= 0:
        raise ValueError(f"width_mm and height_mm must both be positive (got {width_mm}, {height_mm})")

    scale = min(MAX_DRAWING_W / width_mm, MAX_DRAWING_H / height_mm)
    draw_w = width_mm * scale
    draw_h = height_mm * scale

    page_w = MARGIN_LEFT + draw_w + 90   # extra room for the height dimension label
    page_h = MARGIN_TOP + draw_h + DIM_GAP + 40

    doc = fitz.open()
    page = doc.new_page(width=page_w, height=page_h)

    x0, y0 = MARGIN_LEFT, MARGIN_TOP
    x1, y1 = x0 + draw_w, y0 + draw_h
    outer = fitz.Rect(x0, y0, x1, y1)

    frame_thickness = min(draw_w, draw_h) * FRAME_THICKNESS_RATIO
    inner = fitz.Rect(x0 + frame_thickness, y0 + frame_thickness,
                       x1 - frame_thickness, y1 - frame_thickness)

    page.draw_rect(outer, color=(0.2, 0.2, 0.2), fill=frame_color, width=1.2)
    page.draw_rect(inner, color=(0.2, 0.2, 0.2), fill=glass_color, width=1.2)

    # Frame construction seams: the LEFT and RIGHT stiles run the FULL
    # outer height, corner to corner -- the top and bottom rails are
    # shorter, fitted in the gap between the left/right stiles rather
    # than reaching the corners themselves. A short line at each corner,
    # perpendicular to the frame edge, marks where a stile's edge
    # crosses over a rail -- four lines total, one per corner.
    seam_color = (0.2, 0.2, 0.2)
    top_rail_y    = y0 + frame_thickness
    bottom_rail_y = y1 - frame_thickness
    page.draw_line((x0, top_rail_y), (x0 + frame_thickness, top_rail_y), color=seam_color, width=1)
    page.draw_line((x1 - frame_thickness, top_rail_y), (x1, top_rail_y), color=seam_color, width=1)
    page.draw_line((x0, bottom_rail_y), (x0 + frame_thickness, bottom_rail_y), color=seam_color, width=1)
    page.draw_line((x1 - frame_thickness, bottom_rail_y), (x1, bottom_rail_y), color=seam_color, width=1)

    # Width dimension line (below)
    dim_y = y1 + DIM_GAP
    page.draw_line((x0, dim_y), (x1, dim_y), color=(0.15, 0.15, 0.15), width=1)
    page.draw_line((x0, dim_y - DIM_TICK / 2), (x0, dim_y + DIM_TICK / 2), color=(0.15, 0.15, 0.15), width=1)
    page.draw_line((x1, dim_y - DIM_TICK / 2), (x1, dim_y + DIM_TICK / 2), color=(0.15, 0.15, 0.15), width=1)
    width_label = str(int(round(width_mm)))
    label_w = fitz.get_text_length(width_label, fontsize=LABEL_FONTSIZE)
    page.insert_text(((x0 + x1) / 2 - label_w / 2, dim_y + 22), width_label,
                      fontsize=LABEL_FONTSIZE, color=(0.1, 0.1, 0.1))

    # Height dimension line (right)
    dim_x = x1 + DIM_GAP
    page.draw_line((dim_x, y0), (dim_x, y1), color=(0.15, 0.15, 0.15), width=1)
    page.draw_line((dim_x - DIM_TICK / 2, y0), (dim_x + DIM_TICK / 2, y0), color=(0.15, 0.15, 0.15), width=1)
    page.draw_line((dim_x - DIM_TICK / 2, y1), (dim_x + DIM_TICK / 2, y1), color=(0.15, 0.15, 0.15), width=1)
    height_label = str(int(round(height_mm)))
    page.insert_text((dim_x + 10, (y0 + y1) / 2 + 5), height_label,
                      fontsize=LABEL_FONTSIZE, color=(0.1, 0.1, 0.1))

    pix = page.get_pixmap(dpi=dpi)
    png_bytes = pix.tobytes('png')
    doc.close()
    return png_bytes
