"""
Shared constants used by more than one module.

If a value is only used inside a single module file, keep it defined in
that file instead of adding it here — this file should stay small and
only hold things that genuinely need to be shared.
"""

import os
import fitz

# Repo root = one level up from this file (modules/config.py -> repo root)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── Glass weight calculator (Module 2) ──────────────────────────────────────
SHEET_ID      = '1GLWQq3ruw1IARJ1jIQs4Be_KPNk1LXSx-1IAIZCfpY0'
GLASS_DENSITY = 2.5   # kg per m² per mm

# ── Logo stamper (Module 1) ─────────────────────────────────────────────────
LOGO_PATH = os.path.join(BASE_DIR, "Logikhaus_logo.jpg")
LOGO_RECT = fitz.Rect(20, 25, 138, 118)   # position of the stamped logo on page 1

# ── Legend page adder (Module 3) ────────────────────────────────────────────
LEGEND_PDF_PATH = os.path.join(BASE_DIR, "LEGEND page for Schedule.pdf")
LEGEND_KEYWORDS = ["LEGEND", "Codes (left column) are in alphabetical order"]

# ── Frame code data + matcher (Modules 4 & 5) ───────────────────────────────
# Separate spreadsheet holding frame code definitions (tab "CODES")
# and the matching rules used to pick a code from quote text (tab "RULESUPDATE").
FRAME_SHEET_ID  = '1Ieyvx0ZgSBToQFCDGXM8d8xK3zaxqKnXmLdK8ir79n4'
FRAME_RULES_TAB = 'RULESUPDATE'

# Google Sheets API scopes used by every module that reads a sheet.
GOOGLE_SHEETS_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]


def get_google_credentials():
    """
    Shared helper: build authorized gspread credentials from Streamlit
    secrets. Used by any module that needs to open a Google Sheet.
    """
    import streamlit as st
    from google.oauth2.service_account import Credentials

    creds_dict = dict(st.secrets["gcp_service_account"])
    return Credentials.from_service_account_info(creds_dict, scopes=GOOGLE_SHEETS_SCOPES)
