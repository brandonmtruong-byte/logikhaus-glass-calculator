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

Optional opening sash ("swing"): draws the opening part of the window on
top of the fixed frame -- a sash rectangle slightly inset from the outer
frame, with its own stiles, rails and glass, plus a handle bar on the
left or right. Sizes come from the reference drawings (see the SASH_*
and HANDLE_* constants below). No swing/opening lines are drawn on the
glass.
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

# ── Opening sash ("swing") ──────────────────────────────────────────────
# Real-world sizes in mm, measured from the reference drawings. They're
# in mm (not a ratio of the window size) because the references show the
# same member sizes on windows of different sizes -- a real sash profile
# doesn't get thicker just because the window is bigger. Each is scaled
# with the same mm-to-points factor as the window itself.
# Margin: how much of the fixed window frame shows around the sash, on
# every side. Bigger = more frame visible, smaller sash. Can also be
# overridden per call via draw_window_diagram(sash_margin_mm=...).
SASH_MARGIN_MM      = 36
# The margin can never exceed this fraction of the fixed frame's drawn
# thickness. Past the full thickness, the fixed window's glass would show
# between the outer frame and the sash; 0.75 also keeps the frame's
# corner seam ticks visible. On most windows this cap won't be reached.
SASH_MARGIN_MAX_FRAME_RATIO = 0.75
SASH_STILE_MM       = 90    # left/right sash members (run the full sash height)
SASH_TOP_RAIL_MM    = 78    # top sash member (fitted between the stiles)
SASH_BOTTOM_RAIL_MM = 90    # bottom sash member (fitted between the stiles)

# Windows with a shorter side below this size get every sash part (the
# gap, stiles, rails and handle) shrunk by the SAME factor, e.g. a
# 1000 x 200 window's shorter side is 200, so everything is drawn at
# 200/800 = 25% size. Shrinking all parts together keeps them in
# proportion with each other on thin or small windows, instead of some
# being squashed while others stay full size. 800 mm is the smallest
# window in the reference drawings that still had full-size parts.
SASH_REFERENCE_SIZE_MM = 800

# Safety net only: no single part may take more than this fraction of the
# sash's width/height. The shrinking above normally keeps parts well
# under this already.
SASH_MEMBER_MAX_RATIO = 0.2

HANDLE_LENGTH_MM    = 115
HANDLE_THICKNESS_MM = 15
# Minimum on-screen size in points: very large windows are drawn at a
# small scale, where a to-scale handle would shrink to an unreadable tick.
HANDLE_MIN_THICKNESS_PT = 2.0
HANDLE_MIN_LENGTH_PT    = 14.0
# Handle's centre height, as a fraction of the window height measured
# up from the bottom (the reference windows sit around 0.40-0.45).
HANDLE_HEIGHT_RATIO = 0.42
HANDLE_COLOR = (0, 0, 0)

LINE_COLOR = (0.2, 0.2, 0.2)


def draw_window_diagram(width_mm, height_mm, frame_color=FRAME_COLOR, glass_color=GLASS_COLOR, dpi=100,
                        swing=False, handle_side='right', sash_margin_mm=SASH_MARGIN_MM):
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
    swing: False draws the plain fixed window. True also draws the
        opening sash and handle on top of it (see _draw_sash()).
    handle_side: 'left' or 'right' -- which side the handle goes on.
        Only used when swing is True.
    sash_margin_mm: how much of the fixed frame shows around the sash,
        in mm (default SASH_MARGIN_MM). Only used when swing is True.
    """
    if width_mm <= 0 or height_mm <= 0:
        raise ValueError(f"width_mm and height_mm must both be positive (got {width_mm}, {height_mm})")
    if handle_side not in ('left', 'right'):
        raise ValueError(f"handle_side must be 'left' or 'right' (got {handle_side!r})")

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

    if swing:
        _draw_sash(page, outer, scale, frame_thickness, frame_color, glass_color, handle_side,
                   sash_margin_mm)

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


def _draw_sash(page, outer, scale, frame_thickness, frame_color, glass_color, handle_side,
               sash_margin_mm):
    """
    Draw the opening sash on top of the already-drawn fixed window.

    outer: the window's outer frame rectangle, in points.
    scale: points per mm, the same factor used for the window itself.
    frame_thickness: the fixed frame's thickness in points, as drawn.

    Parts are drawn at their real mm sizes on windows whose shorter side
    is at least SASH_REFERENCE_SIZE_MM, and shrunk together below that.

    Layout (matching the reference drawings): the sash is inset from the
    outer frame by sash_margin_mm on every side, so a thin strip of the
    fixed frame shows around it. Its stiles run the sash's full height,
    and the top and bottom rails fit between them. The glass fills the
    space inside. The handle is a short thick bar centred on the glass
    edge on the handle side.
    """
    # Points per mm for the sash parts: the window's own scale, times the
    # shrink factor for thin/small windows (see SASH_REFERENCE_SIZE_MM).
    shorter_side_mm = min(outer.width, outer.height) / scale
    part_scale = scale * min(1.0, shorter_side_mm / SASH_REFERENCE_SIZE_MM)

    # Capped against the fixed frame's thickness (see
    # SASH_MARGIN_MAX_FRAME_RATIO), which matters mostly on small windows.
    inset = min(sash_margin_mm * part_scale, frame_thickness * SASH_MARGIN_MAX_FRAME_RATIO)
    sash = fitz.Rect(outer.x0 + inset, outer.y0 + inset,
                     outer.x1 - inset, outer.y1 - inset)

    max_across = sash.width * SASH_MEMBER_MAX_RATIO
    max_down   = sash.height * SASH_MEMBER_MAX_RATIO
    stile       = min(SASH_STILE_MM * part_scale, max_across)
    top_rail    = min(SASH_TOP_RAIL_MM * part_scale, max_down)
    bottom_rail = min(SASH_BOTTOM_RAIL_MM * part_scale, max_down)

    glass = fitz.Rect(sash.x0 + stile, sash.y0 + top_rail,
                      sash.x1 - stile, sash.y1 - bottom_rail)

    page.draw_rect(sash, color=LINE_COLOR, fill=frame_color, width=1.2)
    page.draw_rect(glass, color=LINE_COLOR, fill=glass_color, width=1.2)

    # Stile edges run the full sash height, top to bottom. The glass
    # rectangle's own top and bottom edges already mark where the rails
    # meet the stiles.
    page.draw_line((glass.x0, sash.y0), (glass.x0, sash.y1), color=LINE_COLOR, width=1.2)
    page.draw_line((glass.x1, sash.y0), (glass.x1, sash.y1), color=LINE_COLOR, width=1.2)

    # Handle: centred on the glass edge on the chosen side.
    edge_x   = glass.x1 if handle_side == 'right' else glass.x0
    handle_y = outer.y1 - outer.height * HANDLE_HEIGHT_RATIO
    half_len = max(HANDLE_LENGTH_MM * part_scale, HANDLE_MIN_LENGTH_PT) / 2
    thickness = max(HANDLE_THICKNESS_MM * part_scale, HANDLE_MIN_THICKNESS_PT)
    page.draw_line((edge_x - half_len, handle_y), (edge_x + half_len, handle_y),
                   color=HANDLE_COLOR, width=thickness, lineCap=1)
