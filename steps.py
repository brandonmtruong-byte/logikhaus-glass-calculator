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

STEP_ORDER = ['logo', 'mass', 'frame', 'legend']

STEP_LABELS = {
    'logo':   'Logo Stamp',
    'mass':   'Glass Weight Calculator',
    'frame':  'Frame Code Matcher',
    'legend': 'Legend Page',
}


def apply_logo(doc):
    """Stamp the logo onto page 1. No table result — app.py shows a page-1 image preview instead."""
    if len(doc) > 0:
        stamp_logo(doc[0])


def apply_mass(doc, glass_lookup):
    """Run the glass weight calculator over every page. Returns the combined result rows."""
    rows = []
    for page in doc:
        rows.extend(process_glass_weights(page, glass_lookup))
    return rows


def apply_frame(doc, frame_codes, frame_rules, glass_type_lookup):
    """Run the frame code matcher over every page. Returns the combined result rows."""
    rules_by_category = group_rules_by_category(frame_rules)
    rows = []
    for page in doc:
        rows.extend(process_frame_codes(page, frame_codes, rules_by_category, glass_type_lookup))
    return rows


def apply_legend(doc):
    """Append the legend page if it's missing. Returns the status string ('added' / 'already_present' / 'missing_file')."""
    return append_legend_page(doc)
