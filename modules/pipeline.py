"""
ORCHESTRATOR — runs Modules 1, 2, 3, and 5 on the uploaded PDF.

This is the one file that has to know about every pipeline-step module
by name, because process_pdf() runs them in a fixed order over the same
document. Adding a brand-new step that must run per-page (not just a new
data source or standalone helper) means importing it here and adding one
call — every module's own internals still live entirely in its own file.
"""

import fitz

from .logo_stamper import stamp_logo
from .glass_weight import process_glass_weights
from .legend_page import append_legend_page
from .frame_code_matcher import process_frame_codes, group_rules_by_category


def process_pdf(file_bytes, glass_lookup, frame_codes=None, frame_rules=None, glass_type_lookup=None):
    doc     = fitz.open(stream=file_bytes, filetype="pdf")
    results = []
    frame_results = []

    rules_by_category = group_rules_by_category(frame_rules) if frame_rules else {}

    for page_num, page in enumerate(doc):
        if page_num == 0:
            stamp_logo(page)                                        # Module 1
        results.extend(process_glass_weights(page, glass_lookup))   # Module 2
        if frame_codes is not None and frame_rules is not None:
            frame_results.extend(
                process_frame_codes(page, frame_codes, rules_by_category, glass_type_lookup)  # Module 5
            )

    legend_status = append_legend_page(doc)                         # Module 3

    out_bytes = doc.tobytes()
    doc.close()
    return out_bytes, results, legend_status, frame_results
