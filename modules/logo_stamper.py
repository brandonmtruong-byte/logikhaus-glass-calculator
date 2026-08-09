"""
MODULE 1 — LOGO STAMPER
Stamps the Logikhaus logo onto the first page of the PDF.
"""

import os
from .config import LOGO_PATH, LOGO_RECT


def stamp_logo(page):
    """Insert the Logikhaus logo image onto the given page, if the logo file exists."""
    if not os.path.exists(LOGO_PATH):
        return
    with open(LOGO_PATH, "rb") as f:
        logo_bytes = f.read()
    page.insert_image(LOGO_RECT, stream=logo_bytes)
