"""
MODULE 4 — FRAME CODE LOOKUP CONNECTION
Connects to the FRAME_SHEET_ID spreadsheet and loads:
  - the CODES tab: frame code (LHF001, ...) -> attributes
  - the RULESUPDATE tab: rules used to work out those attributes from
    raw quote text (Category / Code / Match Type / Match Value, one
    row per rule)
"""

import streamlit as st
import gspread

from .config import FRAME_SHEET_ID, FRAME_RULES_TAB, get_google_credentials


def _open_frame_sheet():
    """Authenticate and open the frame code spreadsheet (shared helper)."""
    creds = get_google_credentials()
    gc = gspread.authorize(creds)
    return gc.open_by_key(FRAME_SHEET_ID)


@st.cache_data(ttl=300)
def load_frame_codes():
    """
    Load the CODES tab: each row maps a Frame code (e.g. LHF001) to its
    attributes (System, Glass type, Opening type, Material, Threshold, ...).
    Returned as a list of dicts, keyed by the sheet's own header row.
    """
    sh = _open_frame_sheet()
    ws = sh.worksheet("CODES")
    return ws.get_all_records()


@st.cache_data(ttl=300)
def load_frame_rules():
    """
    Load the RULESUPDATE tab. This is a flat table:

        Category | Code | Match Type | Match Value | Include | Exclude
        System   | ALU75 | text      | Aluminium 75 |         |
        ...

    Match Type tells the matcher how to use each row:
      - 'text'  : literal substring search in the quote text (Match Value)
      - 'table' : same as 'text' for now (Match Value)
      - 'oType' : depends on the already-resolved Opening Type category
                  (Match Value holds the Opening Type code to compare against)
      - 'logic' : uses the Include / Exclude columns — all Include terms
                  must be present, all Exclude terms must be absent

    Returned as a list of dicts (one per rule row), keyed by the sheet's
    own header row.
    """
    sh = _open_frame_sheet()
    ws = sh.worksheet(FRAME_RULES_TAB)
    return ws.get_all_records()
