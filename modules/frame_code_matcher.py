"""
MODULE 5 — FRAME CODE MATCHER
For each window (Pos.no block) on a page: resolve System / Glass Type /
Opening Type / Material / Threshold from the quote text using the
RULESUPDATE rules, look the 5-tuple up in CODES to get a Frame code,
and stamp it above that window's "System:" line. If any of the 5
categories can't be pinned down to exactly one code, the window is
flagged as an error and nothing is stamped.

Opening Type is also read from each window's DRAWING (the vector picture
to the left of its text) -- see opening_type_from_drawing(). The text
rules and the drawing must agree; if they don't, the window is flagged
and nothing is stamped. Heritage inswing / outswing windows (no drawing
examples yet) and curved or angled windows are checked by text alone.
"""

import math
import re
import fitz

# Order matters: Threshold's 'oType' rules depend on Opening Type already
# being resolved, so Threshold must be resolved last.
CATEGORY_ORDER = ['System', 'Glass Type', 'Opening Type', 'Material', 'Threshold']

# Maps a resolved category name to its column name in the CODES tab.
CODES_COLUMN_MAP = {
    'System':       'System',
    'Glass Type':   'Glass type',
    'Opening Type': 'Opening type',
    'Material':     'MATERIAL',
    'Threshold':    'THRESHOLD',
}


def extract_page_lines(page):
    """Return every text line on the page, top-to-bottom, with position info."""
    blocks = page.get_text('dict')['blocks']
    lines = []
    for b in blocks:
        if 'lines' not in b:
            continue
        for line in b['lines']:
            spans = line['spans']
            if not spans:
                continue
            full_text = ''.join(s['text'] for s in spans).strip()
            if not full_text:
                continue
            bbox = spans[0]['bbox']
            lines.append({
                'y_mid':     (bbox[1] + bbox[3]) / 2,
                'text':      full_text,
                'bbox':      bbox,
                'font_size': spans[0]['size'],
            })
    lines.sort(key=lambda l: l['y_mid'])
    return lines


def split_into_window_blocks(lines):
    """
    Split a page's lines into one block per window, each starting at its
    'Pos.no N: ...' line and running up to (not including) the next one.
    """
    blocks  = []
    current = None
    for line in lines:
        if re.match(r'Pos\.?no\s*\d+', line['text'], re.IGNORECASE):
            if current:
                blocks.append(current)
            current = {'pos_label': line['text'], 'lines': [line]}
        elif current:
            current['lines'].append(line)
    if current:
        blocks.append(current)
    return blocks


def find_system_line(block_lines):
    """Find the line starting with 'System:' within a window block, if any."""
    for line in block_lines:
        if line['text'].lower().startswith('system:'):
            return line
    return None


def group_rules_by_category(frame_rules):
    """Turn the flat RULESUPDATE rows into {category: {code: [rule_rows]}}."""
    grouped = {}
    for row in frame_rules:
        grouped.setdefault(row['Category'], {}).setdefault(row['Code'], []).append(row)
    return grouped


def _get_field_ci(rule_row, field_name):
    """
    Fetch a field from a rule row, tolerant of header mismatches
    (case, leading/trailing whitespace) that would otherwise silently
    return '' via a plain dict lookup on the wrong key.
    """
    target = field_name.strip().lower()
    for key, value in rule_row.items():
        if key.strip().lower() == target:
            return value
    return ''


def contains_normalized(haystack_lower, needle):
    """
    Whitespace- and line-break-insensitive substring check. Handles two
    quirks: (1) stray spaces mid-word from PDF text extraction (e.g.
    'I nward opening'), and (2) phrases that get word-wrapped across two
    separate PDF text lines, which our own block-text joining then
    separates with ' | ' (e.g. '1- | seal threshold'). Stripping both
    whitespace and '|' before comparing makes matching tolerant of both.
    """
    compact_haystack = re.sub(r'[\s|]+', '', haystack_lower)
    compact_needle    = re.sub(r'[\s|]+', '', needle.lower())
    return compact_needle in compact_haystack


def evaluate_logic_rule(rule_row, text_lower):
    """
    Evaluate a 'logic' rule using its Include/Exclude columns, e.g.:
      Include: fitting          Exclude: Wheels          -> present AND absent
      Include: (blank)          Exclude: HS:- ZERO, ECO PASS  -> both absent
    All Include terms must be present; all Exclude terms must be absent.
    """
    includes = [t.strip() for t in str(_get_field_ci(rule_row, 'Include')).split(',') if t.strip()]
    excludes = [t.strip() for t in str(_get_field_ci(rule_row, 'Exclude')).split(',') if t.strip()]
    return (all(contains_normalized(text_lower, t) for t in includes)
            and all(not contains_normalized(text_lower, t) for t in excludes))


def extract_lhg_code(block_text):
    """
    Find the LHG code within a window's raw (non-lowercased) block text,
    e.g. from its 'Glass: ... LHG012 ...' line. If multiple codes are
    found on the line, just use the first one — good enough for looking
    up Glass Type (DG/TG/VT/VP), even though it's ambiguous for the mass
    calculator's own weight lookup (handled separately in Module 2).
    Returns None only if zero codes are found at all.
    """
    matches = re.findall(r'LHG\d+', block_text)
    return matches[0] if matches else None


def evaluate_rule(rule_row, block_text_lower, resolved_so_far, glass_type_lookup=None, lhg_code=None):
    """Evaluate a single RULESUPDATE row against a window's block text."""
    match_type  = rule_row['Match Type'].strip().lower()
    match_value = str(rule_row['Match Value']).strip()

    if match_type == 'text':
        return contains_normalized(block_text_lower, match_value)
    if match_type == 'table':
        # Glass Type: look up the window's LHG code in the glass sheet's
        # column G (DG/TG/VT/VP) rather than searching quote text directly.
        if not lhg_code or not glass_type_lookup:
            return False
        looked_up = glass_type_lookup.get(lhg_code)
        if not looked_up:
            return False
        return looked_up.strip().lower() == match_value.lower()
    if match_type == 'otype':
        return resolved_so_far.get('Opening Type') == match_value
    if match_type == 'logic':
        return evaluate_logic_rule(rule_row, block_text_lower)
    return False   # unknown match type — never matches


def resolve_categories(block_text, rules_by_category, glass_type_lookup=None):
    """
    Resolve all 5 categories for one window's block text.
    Returns (resolved_dict, error_list). error_list is empty only when all
    5 categories resolved to exactly one code each.
    """
    block_text_lower = block_text.lower()
    lhg_code          = extract_lhg_code(block_text)
    resolved = {}
    errors   = []

    for category in CATEGORY_ORDER:
        rules_for_category = rules_by_category.get(category, {})
        matched_codes = [
            code for code, rule_rows in rules_for_category.items()
            if any(evaluate_rule(r, block_text_lower, resolved, glass_type_lookup, lhg_code)
                   for r in rule_rows)
        ]
        if len(matched_codes) == 1:
            resolved[category] = matched_codes[0]
        elif len(matched_codes) == 0:
            errors.append(f'{category}: no match found')
        else:
            errors.append(f'{category}: ambiguous ({", ".join(matched_codes)})')

    return resolved, errors


def match_frame_code(resolved, frame_codes):
    """Look up the resolved 5-tuple in the CODES tab. Returns (frame_code, error)."""
    matches = [
        row for row in frame_codes
        if all(str(row.get(CODES_COLUMN_MAP[cat], '')).strip() == resolved[cat]
               for cat in CATEGORY_ORDER)
    ]
    if len(matches) == 1:
        return matches[0].get('Frame code'), None
    if len(matches) == 0:
        return None, 'No matching row in CODES tab'
    return None, f'Multiple CODES rows match ({len(matches)})'


# ═════════════════════════════════════════════════════════════════════════
# OPENING TYPE FROM THE DRAWING
# Each window's picture is real vector shapes, so its opening symbols can
# be read exactly. Worked out (and tested on 120 windows across the
# PRICING-GENERATOR price list, a customer schedule and the DG template):
#
#   no opening symbols                          -> FIXED WINDOW
#   dashed diagonals (tilt & turn, tilt only)   -> INSWING WINDOW
#     ...with a door threshold (balcony door)   -> INSWING DOOR
#   thin solid diagonals (door swing lines)     -> INSWING DOOR
#     ...with "DX" in the drawn code ("R DX")   -> OUTSWING DOOR
#   arrows, no dashed diagonals                 -> LIFT AND SLIDE DOOR
#   arrows + dashed diagonals (tilt & slide)    -> SLIDING WINDOW
#
# Outswing doors are drawn from OUTSIDE, so their swing lines look like an
# inswing door of the opposite hand -- the drawn "DX" code is what tells
# them apart. Windows have a filled frame rail across the full width at
# the bottom; doors have a threshold instead (no full-width bottom strip).
# ═════════════════════════════════════════════════════════════════════════

# Opening types the drawing can't check yet (no drawing examples): use the
# text rules alone for these.
OPENING_TYPES_TEXT_ONLY = {'HERITAGE INSWING WINDOW', 'OUTSWING WINDOW'}

# Text markers for shaped windows, which are also checked by text alone.
SHAPED_WINDOW_MARKERS = ('ANGLE EXTRA', 'ARCH EXTRA')

# The drawing sits in the left part of the page; text starts to its right.
DRAWING_COLUMN_RATIO = 0.5
# A window's drawing starts a little above its "Pos.no" line.
DRAWING_TOP_MARGIN = 40


def _drawing_for_block(page_drawings, page_lines, page, block_top, next_block_top):
    """
    The shapes and drawn codes (e.g. 'AX_RU1', 'R DX', 'HS') of the window
    whose 'Pos.no' line is at block_top: everything in the drawing column
    from just above that line to just above the next window's.
    """
    x_limit = page.rect.width * DRAWING_COLUMN_RATIO
    y0 = block_top - DRAWING_TOP_MARGIN
    y1 = (next_block_top - DRAWING_TOP_MARGIN) if next_block_top is not None else page.rect.height
    shapes = [d for d in page_drawings if d['rect'].x1 < x_limit and y0 <= d['rect'].y0 < y1]
    codes = [l['text'] for l in page_lines
             if l['bbox'][2] < x_limit and y0 <= l['bbox'][1] < y1
             and not re.fullmatch(r'[\d\s.,]+', l['text'])]
    return shapes, codes


def _is_dashed(shape):
    return shape.get('dashes') not in (None, '[] 0', '[] 0.0', '[] 0.00')


def _drawing_symbols(shapes):
    """Count the opening symbols in one window's drawing."""
    dashed = thin = 0
    thin_segments = []
    for s in shapes:
        width = s.get('width') or 0
        dash = _is_dashed(s)
        for it in s['items']:
            if it[0] != 'l':
                continue
            a, b = it[1], it[2]
            dx, dy = abs(b.x - a.x), abs(b.y - a.y)
            if dash and dx > 1 and dy > 1:
                dashed += 1                                   # tilt / turn lines
            elif not dash and width < 0.2 and dx > 2 and dy > 2 and math.hypot(dx, dy) > 8:
                thin += 1                                     # door swing lines
            if not dash and width < 0.3:
                thin_segments.append((a, b))

    # Arrows: a thin horizontal shaft with two short slanted strokes meeting
    # at one end, one going up and one going down.
    arrows = 0
    shafts = [(a, b) for a, b in thin_segments if abs(a.y - b.y) < 0.3 and abs(a.x - b.x) > 4]
    strokes = [(a, b) for a, b in thin_segments
               if 0.8 < math.hypot(b.x - a.x, b.y - a.y) < 14
               and abs(b.x - a.x) > 0.2 and abs(b.y - a.y) > 0.2]
    for a, b in shafts:
        for end in (a, b):
            touching = [(p, q) for p, q in strokes
                        if min(math.hypot(p.x - end.x, p.y - end.y),
                               math.hypot(q.x - end.x, q.y - end.y)) < 0.5]
            up = any(max(p.y, q.y) > end.y + 0.2 for p, q in touching)
            down = any(min(p.y, q.y) < end.y - 0.2 for p, q in touching)
            if up and down:
                arrows += 1
    return {'dashed': dashed, 'thin': thin, 'arrows': arrows}


def _is_shaped_window(shapes):
    """True for curved (round / arched) or angled windows."""
    for s in shapes:
        for it in s['items']:
            if it[0] == 'c':
                return True                                   # a curved outline
            if it[0] == 'l' and (s.get('width') or 0) >= 0.5:
                a, b = it[1], it[2]
                if abs(a.x - b.x) > 2 and abs(a.y - b.y) > 2:
                    return True                               # a sloped frame edge
    return False


def _has_door_threshold(shapes):
    """
    True if the frame has a door threshold instead of a bottom rail.
    Windows: a filled strip across (nearly) the full frame width at the
    very bottom. Doors: no such strip.
    """
    frame = fitz.Rect()
    for s in shapes:
        if (s.get('width') or 0) >= 0.5:
            frame |= s['rect']
    if frame.is_empty:
        return False
    for s in shapes:
        r = s['rect']
        if (s.get('fill') and any(it[0] == 're' for it in s['items']) and r.height < 6
                and frame.y1 - r.y1 < 1.6 and r.width >= 0.9 * frame.width):
            return False
    return True


def opening_type_from_drawing(shapes, codes):
    """
    The opening type a window's drawing shows (one of the codes in the
    table above), or None if there's no drawing to read.
    """
    if not any((s.get('width') or 0) >= 0.5 for s in shapes):
        return None                                           # no frame drawn
    sym = _drawing_symbols(shapes)
    drawn = ' '.join(codes)
    if sym['arrows']:
        return 'SLIDING WINDOW' if sym['dashed'] else 'LIFT AND SLIDE DOOR'
    if sym['dashed']:
        return 'INSWING DOOR' if _has_door_threshold(shapes) else 'INSWING WINDOW'
    if sym['thin'] >= 2:
        return 'OUTSWING DOOR' if re.search(r'\bDX\b', drawn) else 'INSWING DOOR'
    return 'FIXED WINDOW'


def check_opening_type(text_type, block_text, shapes, codes):
    """
    Compare the text rules' Opening Type with the drawing's.
    Returns (drawing_result_for_display, error or None).
    """
    upper = block_text.upper()
    if text_type and text_type.strip().upper() in OPENING_TYPES_TEXT_ONLY:
        return 'not checked (type checked by text only)', None
    if any(m in upper for m in SHAPED_WINDOW_MARKERS) or _is_shaped_window(shapes):
        return 'not checked (curved / angled window)', None
    drawn_type = opening_type_from_drawing(shapes, codes)
    if drawn_type is None:
        return 'no drawing found', 'Opening Type: no drawing found to check it against'
    if text_type is None:
        return drawn_type, None        # the text rules' own error already covers this
    if text_type.strip().upper() != drawn_type:
        return drawn_type, f'Opening Type: text says {text_type}, drawing says {drawn_type}'
    return drawn_type, None


def _stamp_highlight_rect(x, y_base, text, fontsize, fontname='helv'):
    """
    Bounding rect around a stamped frame code label, for preview
    highlighting only -- purely visual, never used for any redaction or
    deletion, so it doesn't need to stay tight.
    """
    font_obj = fitz.Font(fontname)
    width = font_obj.text_length(text, fontsize=fontsize)
    pad = 2.0
    return fitz.Rect(
        x - pad, y_base - fontsize * 0.85 - pad,
        x + width + pad, y_base + fontsize * 0.25 + pad,
    )


def process_frame_codes(page, frame_codes, rules_by_category, glass_type_lookup=None):
    """
    Full frame-code pass for a single page: split into window blocks,
    resolve + look up a frame code for each, stamp it above 'System:',
    and return a result row per window for the on-screen debug table.

    Every result row always has one column per category (System, Glass
    Type, Opening Type, Material, Threshold) — filled in with whatever was
    resolved, blank if that category failed — plus Frame Code and Details,
    so partial progress is visible even on an ERROR row.
    """
    lines          = extract_page_lines(page)
    window_blocks  = split_into_window_blocks(lines)
    page_drawings  = page.get_drawings()
    results        = []

    for i, block in enumerate(window_blocks):
        block_text  = ' | '.join(l['text'] for l in block['lines'])
        system_line = find_system_line(block['lines'])

        resolved, errors = resolve_categories(block_text, rules_by_category, glass_type_lookup)

        # Opening Type must also match the window's drawing.
        block_top = block['lines'][0]['bbox'][1]
        next_top = (window_blocks[i + 1]['lines'][0]['bbox'][1]
                    if i + 1 < len(window_blocks) else None)
        shapes, codes = _drawing_for_block(page_drawings, lines, page, block_top, next_top)
        drawing_result, drawing_error = check_opening_type(
            resolved.get('Opening Type'), block_text, shapes, codes)
        if drawing_error:
            errors.append(drawing_error)

        # Base row always shows what was (or wasn't) resolved per category
        row = {
            'Window':     block['pos_label'],
            'Frame Code': 'ERROR',
            **{cat: resolved.get(cat, '') for cat in CATEGORY_ORDER},
            'Drawing':    drawing_result,
            'Details':    '',
            'Block Text': block_text,
            '_highlight_rect': None,
        }

        if errors:
            row['Details'] = '; '.join(errors)
            results.append(row)
            continue

        frame_code, lookup_error = match_frame_code(resolved, frame_codes)
        if lookup_error:
            row['Details'] = lookup_error
            results.append(row)
            continue

        if system_line:
            stamp_text = f'[{frame_code}]'
            page.insert_text(
                (system_line['bbox'][0], system_line['bbox'][1] - 2),
                stamp_text,
                fontsize=system_line['font_size'],
                fontname='helv',
                color=(0.0, 0.0, 0.0),
            )
            row['_highlight_rect'] = _stamp_highlight_rect(
                system_line['bbox'][0], system_line['bbox'][1] - 2,
                stamp_text, system_line['font_size']
            )

        row['Frame Code'] = frame_code
        row['Details']    = 'OK'
        results.append(row)

    return results
