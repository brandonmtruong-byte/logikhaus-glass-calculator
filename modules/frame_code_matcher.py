"""
MODULE 5 — FRAME CODE MATCHER
For each window (Pos.no block) on a page: resolve System / Glass Type /
Opening Type / Material / Threshold from the quote text using the
RULESUPDATE rules, look the 5-tuple up in CODES to get a Frame code,
and stamp it above that window's "System:" line. If any of the 5
categories can't be pinned down to exactly one code, the window is
flagged as an error and nothing is stamped.
"""

import re

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
    results        = []

    for block in window_blocks:
        block_text  = ' | '.join(l['text'] for l in block['lines'])
        system_line = find_system_line(block['lines'])

        resolved, errors = resolve_categories(block_text, rules_by_category, glass_type_lookup)

        # Base row always shows what was (or wasn't) resolved per category
        row = {
            'Window':     block['pos_label'],
            'Frame Code': 'ERROR',
            **{cat: resolved.get(cat, '') for cat in CATEGORY_ORDER},
            'Details':    '',
            'Block Text': block_text,
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
            page.insert_text(
                (system_line['bbox'][0], system_line['bbox'][1] - 2),
                f'[{frame_code}]',
                fontsize=system_line['font_size'],
                fontname='helv',
                color=(0.0, 0.0, 0.0),
            )

        row['Frame Code'] = frame_code
        row['Details']    = 'OK'
        results.append(row)

    return results
