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
TOTAL_DIM_GAP = 40    # split windows: extra gap down to the overall-width line
DIM_TICK      = 8     # length of the little end-ticks on dimension lines
LABEL_FONTSIZE = 16

# PDF export (draw_window_diagram_pdf): blank border around the diagram
# on the page, in points (72 pt = 1 inch, so 40 pt is about 14 mm).
PDF_PAGE_MARGIN_PT = 40

# Fixed frame thickness in real mm, measured from reference drawings
# (about 64-66 mm on windows from 800 x 1300 up to 1000 x 2415). A real
# frame profile is the same thickness whatever the window size, so this is
# in mm rather than a fraction of the window. Scaled with the window's own
# mm-to-points factor, like everything else.
FRAME_THICKNESS_MM = 64
# Windows whose shorter side is below this get a proportionally thinner
# frame (e.g. 300 mm -> half thickness), so small windows keep some glass.
# Every reference window's shorter side was at least 600 mm.
FRAME_REFERENCE_SIZE_MM = 600
FRAME_COLOR = (0.95, 0.86, 0.71)   # light tan, #F2DCB6
GLASS_COLOR = (0.82, 0.28, 0.57)   # magenta, #D04891, matching the reference images

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

# Opening lines: the thin dashed lines on the sash glass that show how it
# opens. The sash always gets the side-hung "turn" lines (from the two
# hinge-side corners to the middle of the handle side); tilt and turn adds
# the "tilt" lines too (from the two bottom corners up to the middle of
# the top). Dash pattern is in points: 4.5 pt dash, 3 pt gap.
OPENING_LINE_COLOR = (0.25, 0.25, 0.25)
OPENING_LINE_WIDTH = 0.5
OPENING_LINE_DASHES = '[4.5 3] 0'


def draw_window_diagram(width_mm, height_mm, frame_color=FRAME_COLOR, glass_color=GLASS_COLOR, dpi=100,
                        swing=False, handle_side='right', sash_margin_mm=SASH_MARGIN_MM,
                        tilt=False, split=False, swing_2=False, handle_side_2='left',
                        tilt_2=False):
    """
    Returns PNG bytes for a to-scale window diagram (the on-screen preview).

    width_mm, height_mm: the real window dimensions (the OVERALL size,
        also when split). Must both be > 0.
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
    tilt: True adds the tilt-and-turn opening lines (bottom corners up to
        the middle of the top) to the standard side-hung ones. Only used
        when swing is True.
    split: True divides the window into two equal panes, side by side,
        with a mullion (vertical frame member) between them. The overall
        size stays width_mm x height_mm; each pane is width_mm / 2 wide.
        swing / handle_side / tilt then apply to the LEFT pane, and
        swing_2 / handle_side_2 / tilt_2 to the RIGHT pane. The *_2
        options are ignored when split is False.
    """
    doc = _build_diagram_doc(width_mm, height_mm, frame_color, glass_color, sash_margin_mm,
                             _pane_options(swing, handle_side, tilt, split,
                                           swing_2, handle_side_2, tilt_2))
    pix = doc[0].get_pixmap(dpi=dpi)
    png_bytes = pix.tobytes('png')
    doc.close()
    return png_bytes


def draw_window_diagram_pdf(width_mm, height_mm, frame_color=FRAME_COLOR, glass_color=GLASS_COLOR,
                            swing=False, handle_side='right', sash_margin_mm=SASH_MARGIN_MM,
                            tilt=False, split=False, swing_2=False, handle_side_2='left',
                            tilt_2=False, paper='a4', page_margin_pt=PDF_PAGE_MARGIN_PT):
    """
    Returns PDF bytes: the same diagram as draw_window_diagram(), placed
    on a blank page (A4 by default) and enlarged to fill it, centred.

    The diagram stays VECTOR in the PDF -- lines, fills and numbers are
    drawn shapes and text, not a picture -- so it's sharp at any zoom
    level and prints at the printer's full resolution. The page turns
    landscape automatically when the diagram is wider than it is tall.

    Takes the same drawing arguments as draw_window_diagram() (no dpi,
    since nothing is rasterized), plus:
    paper: any paper size name fitz understands ('a4', 'a3', 'letter', ...).
    page_margin_pt: blank border around the diagram, in points (72 pt = 1 inch).
    """
    diagram = _build_diagram_doc(width_mm, height_mm, frame_color, glass_color, sash_margin_mm,
                                 _pane_options(swing, handle_side, tilt, split,
                                               swing_2, handle_side_2, tilt_2))
    diagram_rect = diagram[0].rect

    paper_rect = fitz.paper_rect(paper)
    if diagram_rect.width > diagram_rect.height:
        paper_rect = fitz.Rect(0, 0, paper_rect.height, paper_rect.width)   # landscape

    out = fitz.open()
    page = out.new_page(width=paper_rect.width, height=paper_rect.height)

    # Largest size that fits inside the margins without distorting,
    # centred on the page.
    avail_w = paper_rect.width - 2 * page_margin_pt
    avail_h = paper_rect.height - 2 * page_margin_pt
    fit = min(avail_w / diagram_rect.width, avail_h / diagram_rect.height)
    w, h = diagram_rect.width * fit, diagram_rect.height * fit
    x0 = (paper_rect.width - w) / 2
    y0 = (paper_rect.height - h) / 2
    page.show_pdf_page(fitz.Rect(x0, y0, x0 + w, y0 + h), diagram, 0)

    pdf_bytes = out.tobytes(garbage=3, deflate=True)
    out.close()
    diagram.close()
    return pdf_bytes


def _pane_options(swing, handle_side, tilt, split, swing_2, handle_side_2, tilt_2):
    """
    Turn the public arguments into one options dict per pane (one pane,
    or two side by side when split), validating the handle sides.
    """
    panes = [dict(swing=swing, handle_side=handle_side, tilt=tilt)]
    if split:
        panes.append(dict(swing=swing_2, handle_side=handle_side_2, tilt=tilt_2))
    for pane in panes:
        if pane['handle_side'] not in ('left', 'right'):
            raise ValueError(f"handle side must be 'left' or 'right' (got {pane['handle_side']!r})")
    return panes


def _format_mm(value):
    """A dimension label: whole numbers as-is ("850"), halves kept ("850.5")."""
    return f'{value:g}'


def _build_diagram_doc(width_mm, height_mm, frame_color, glass_color, sash_margin_mm, panes):
    """
    Draw the diagram onto a new one-page fitz.Document and return it.
    Shared by draw_window_diagram() (PNG preview) and
    draw_window_diagram_pdf() (PDF), so both always show exactly the
    same drawing. panes is the list from _pane_options(): one dict for a
    single window, two for a split one. Other arguments as documented on
    draw_window_diagram(). The caller is responsible for closing the
    returned document.
    """
    if width_mm <= 0 or height_mm <= 0:
        raise ValueError(f"width_mm and height_mm must both be positive (got {width_mm}, {height_mm})")
    split = len(panes) == 2

    scale = min(MAX_DRAWING_W / width_mm, MAX_DRAWING_H / height_mm)
    draw_w = width_mm * scale
    draw_h = height_mm * scale

    page_w = MARGIN_LEFT + draw_w + 90   # extra room for the height dimension label
    page_h = MARGIN_TOP + draw_h + DIM_GAP + 40
    if split:
        page_h += TOTAL_DIM_GAP          # room for the second (overall) width line

    doc = fitz.open()
    page = doc.new_page(width=page_w, height=page_h)

    x0, y0 = MARGIN_LEFT, MARGIN_TOP
    x1, y1 = x0 + draw_w, y0 + draw_h
    xm = (x0 + x1) / 2                   # centre line (the mullion, when split)
    outer = fitz.Rect(x0, y0, x1, y1)

    shorter_side_mm = min(width_mm, height_mm)
    frame_thickness = (FRAME_THICKNESS_MM * scale
                       * min(1.0, shorter_side_mm / FRAME_REFERENCE_SIZE_MM))
    # The mullion is the same thickness as the frame, centred on xm.
    mullion_half = frame_thickness / 2

    page.draw_rect(outer, color=(0.2, 0.2, 0.2), fill=frame_color, width=1.2)
    if split:
        left_glass  = fitz.Rect(x0 + frame_thickness, y0 + frame_thickness,
                                xm - mullion_half, y1 - frame_thickness)
        right_glass = fitz.Rect(xm + mullion_half, y0 + frame_thickness,
                                x1 - frame_thickness, y1 - frame_thickness)
        page.draw_rect(left_glass, color=(0.2, 0.2, 0.2), fill=glass_color, width=1.2)
        page.draw_rect(right_glass, color=(0.2, 0.2, 0.2), fill=glass_color, width=1.2)
    else:
        inner = fitz.Rect(x0 + frame_thickness, y0 + frame_thickness,
                          x1 - frame_thickness, y1 - frame_thickness)
        page.draw_rect(inner, color=(0.2, 0.2, 0.2), fill=glass_color, width=1.2)

    # Frame construction seams: the top and bottom rails run the FULL
    # width, and the side stiles fit between them. A short line at each
    # corner, across the stile, marks where a stile meets a rail -- four
    # lines total, one per corner.
    seam_color = (0.2, 0.2, 0.2)
    top_rail_y    = y0 + frame_thickness
    bottom_rail_y = y1 - frame_thickness
    page.draw_line((x0, top_rail_y), (x0 + frame_thickness, top_rail_y), color=seam_color, width=1)
    page.draw_line((x1 - frame_thickness, top_rail_y), (x1, top_rail_y), color=seam_color, width=1)
    page.draw_line((x0, bottom_rail_y), (x0 + frame_thickness, bottom_rail_y), color=seam_color, width=1)
    page.draw_line((x1 - frame_thickness, bottom_rail_y), (x1, bottom_rail_y), color=seam_color, width=1)
    if split:
        # The mullion also fits between the rails: continue the rails'
        # inner edges across it, the same way as at the corners.
        page.draw_line((xm - mullion_half, top_rail_y), (xm + mullion_half, top_rail_y),
                       color=seam_color, width=1)
        page.draw_line((xm - mullion_half, bottom_rail_y), (xm + mullion_half, bottom_rail_y),
                       color=seam_color, width=1)

    # Sashes. A split window's panes are each half the outer frame; the
    # sash leaves only half its usual margin on the mullion side, so the
    # two sashes sit close together over the mullion.
    if split:
        pane_layout = [(fitz.Rect(x0, y0, xm, y1), 'right'),
                       (fitz.Rect(xm, y0, x1, y1), 'left')]
    else:
        pane_layout = [(outer, None)]
    for options, (pane_rect, mullion_side) in zip(panes, pane_layout):
        if options['swing']:
            _draw_sash(page, pane_rect, scale, frame_thickness, frame_color, glass_color,
                       options['handle_side'], sash_margin_mm, options['tilt'], mullion_side)

    # Width dimension line (below). Split windows get each pane's width
    # here, plus the overall width on a second line further down.
    dim_color = (0.15, 0.15, 0.15)
    dim_y = y1 + DIM_GAP
    if split:
        _draw_width_dimension(page, [x0, xm, x1], dim_y,
                              [_format_mm(width_mm / 2)] * 2, dim_color)
        dim_y += TOTAL_DIM_GAP
    _draw_width_dimension(page, [x0, x1], dim_y, [str(int(round(width_mm)))], dim_color)

    # Height dimension line (right)
    dim_x = x1 + DIM_GAP
    page.draw_line((dim_x, y0), (dim_x, y1), color=dim_color, width=1)
    page.draw_line((dim_x - DIM_TICK / 2, y0), (dim_x + DIM_TICK / 2, y0), color=dim_color, width=1)
    page.draw_line((dim_x - DIM_TICK / 2, y1), (dim_x + DIM_TICK / 2, y1), color=dim_color, width=1)
    height_label = str(int(round(height_mm)))
    page.insert_text((dim_x + 10, (y0 + y1) / 2 + 5), height_label,
                      fontsize=LABEL_FONTSIZE, color=(0.1, 0.1, 0.1))

    return doc


def _draw_width_dimension(page, xs, dim_y, labels, dim_color):
    """
    One horizontal dimension line at height dim_y, with a tick at every x
    in xs (left to right) and labels[i] centred under the span from xs[i]
    to xs[i + 1].
    """
    page.draw_line((xs[0], dim_y), (xs[-1], dim_y), color=dim_color, width=1)
    for x in xs:
        page.draw_line((x, dim_y - DIM_TICK / 2), (x, dim_y + DIM_TICK / 2), color=dim_color, width=1)
    for label, left, right in zip(labels, xs, xs[1:]):
        label_w = fitz.get_text_length(label, fontsize=LABEL_FONTSIZE)
        page.insert_text(((left + right) / 2 - label_w / 2, dim_y + 22), label,
                          fontsize=LABEL_FONTSIZE, color=(0.1, 0.1, 0.1))


def _draw_sash(page, outer, scale, frame_thickness, frame_color, glass_color, handle_side,
               sash_margin_mm, tilt, mullion_side=None):
    """
    Draw the opening sash on top of the already-drawn fixed window.

    outer: the area the sash belongs to, in points -- the window's whole
        outer frame, or one half of it for a split window.
    scale: points per mm, the same factor used for the window itself.
    frame_thickness: the fixed frame's thickness in points, as drawn.
    mullion_side: for a split window's pane, 'left' or 'right' -- the
        side facing the mullion, where the sash margin is halved. None
        for a single window.

    Parts are drawn at their real mm sizes on panes whose shorter side
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
    left_inset  = inset / 2 if mullion_side == 'left' else inset
    right_inset = inset / 2 if mullion_side == 'right' else inset
    sash = fitz.Rect(outer.x0 + left_inset, outer.y0 + inset,
                     outer.x1 - right_inset, outer.y1 - inset)

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

    _draw_opening_lines(page, glass, handle_side, tilt)

    # Handle: centred on the glass edge on the chosen side. Drawn after
    # the opening lines so it sits on top of them.
    edge_x   = glass.x1 if handle_side == 'right' else glass.x0
    handle_y = outer.y1 - outer.height * HANDLE_HEIGHT_RATIO
    half_len = max(HANDLE_LENGTH_MM * part_scale, HANDLE_MIN_LENGTH_PT) / 2
    thickness = max(HANDLE_THICKNESS_MM * part_scale, HANDLE_MIN_THICKNESS_PT)
    page.draw_line((edge_x - half_len, handle_y), (edge_x + half_len, handle_y),
                   color=HANDLE_COLOR, width=thickness, lineCap=1)


def _draw_opening_lines(page, glass, handle_side, tilt):
    """
    Draw the dashed opening lines on the sash glass.

    Turn (always): from the top and bottom corners on the HINGE side (the
    side without the handle) to the middle of the handle side, making a
    sideways "V" that points at the handle.

    Tilt (only if tilt is True): from the two bottom corners up to the
    middle of the top edge, making an upside-down "V" -- the sash tilts
    in from the top, hinged along the bottom.
    """
    style = dict(color=OPENING_LINE_COLOR, width=OPENING_LINE_WIDTH,
                 dashes=OPENING_LINE_DASHES)

    if handle_side == 'right':
        hinge_x, handle_x = glass.x0, glass.x1
    else:
        hinge_x, handle_x = glass.x1, glass.x0
    handle_mid = (handle_x, (glass.y0 + glass.y1) / 2)
    page.draw_line((hinge_x, glass.y0), handle_mid, **style)
    page.draw_line((hinge_x, glass.y1), handle_mid, **style)

    if tilt:
        top_mid = ((glass.x0 + glass.x1) / 2, glass.y0)
        page.draw_line((glass.x0, glass.y1), top_mid, **style)
        page.draw_line((glass.x1, glass.y1), top_mid, **style)
