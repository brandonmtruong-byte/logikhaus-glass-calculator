"""
MODULE 3 — LEGEND PAGE ADDER
Checks whether the legend page is already in the quote, and appends the
standard legend PDF to the end if it's missing.
"""

import os
import fitz

from .config import LEGEND_PDF_PATH, LEGEND_KEYWORDS


def has_legend_page(doc):
    """Return True if any page in doc already contains the legend text."""
    for page in doc:
        text = page.get_text()
        if all(kw in text for kw in LEGEND_KEYWORDS):
            return True
    return False


def append_legend_page(doc):
    """
    Append the legend PDF to the end of doc, unless a legend page is
    already present. Returns a status string for UI feedback:
    'added', 'already_present', or 'missing_file'.
    """
    if has_legend_page(doc):
        return 'already_present'
    if not os.path.exists(LEGEND_PDF_PATH):
        return 'missing_file'
    legend_doc = fitz.open(LEGEND_PDF_PATH)
    doc.insert_pdf(legend_doc)
    legend_doc.close()
    return 'added'
