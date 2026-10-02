"""
Page styling and header markup for the Streamlit app.
Kept separate from app.py so tweaking colors/fonts never touches logic.
"""

import streamlit as st

from .config import LOGO_PATH

# COLOURS: nothing here may assume a dark (or light) background. Text uses
# `color: inherit` (Streamlit sets the theme's text colour on the page, so it
# flips automatically between Light and Dark) and "muted" text is done with
# opacity rather than a fixed grey. Lines/borders use rgba(128,128,128,x),
# which reads on both. Only the brand red and the two icon colours are fixed.
CUSTOM_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

    /* Always reserve the vertical scrollbar's space, even on short pages.
       Without this, switching between views of very different heights
       (e.g. the tall PDF Modifier stepper vs the short Certificate
       Creator form) makes the scrollbar appear/disappear, which shifts
       centered content left/right by the scrollbar's width. */
    html {
        overflow-y: scroll;
    }

    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

    .block-container { padding-top: 2.5rem; max-width: 760px; }

    h1 { font-size: 1.5rem; font-weight: 600; letter-spacing: -0.02em; color: inherit; }
    h3 { font-size: 0.85rem; font-weight: 500; text-transform: uppercase;
         letter-spacing: 0.08em; color: inherit; opacity: 0.6; margin-bottom: 0.5rem; }

    .lh-header {
        display: flex; align-items: center; gap: 14px;
        border-bottom: 2px solid #A13336; padding-bottom: 1rem; margin-bottom: 2rem;
    }
    .lh-logo {
        background: #A13336; color: white; font-weight: 700;
        font-size: 0.75rem; padding: 6px 10px; letter-spacing: 0.05em;
    }
    .lh-title { font-size: 1.25rem; font-weight: 600; color: inherit; }
    .lh-sub   { font-size: 0.8rem; color: inherit; opacity: 0.6; margin-top: 2px; }

    .status-box {
        background: rgba(128,128,128,0.24); border-left: 3px solid #A13336;
        padding: 0.75rem 1rem; border-radius: 0 4px 4px 0;
        font-size: 0.85rem; color: inherit; margin-bottom: 1rem;
    }
    .skip-row { color: inherit; opacity: 0.5; font-style: italic; }

    div[data-testid="stDownloadButton"] button {
        background: #A13336; color: white; border: none;
        font-weight: 500; width: 100%;
    }
    div[data-testid="stDownloadButton"] button:hover { background: #6e1414; }

    /* Hide Streamlit's auto-generated header anchor links (the "#" icon
       that appears next to every st.markdown/st.header heading). */
    h1 a[href^="#"], h2 a[href^="#"], h3 a[href^="#"],
    h4 a[href^="#"], h5 a[href^="#"], h6 a[href^="#"] {
        display: none !important;
    }

    /* ══════════════════════════════════════════════════════════════════
       STEPPER - clear visual hierarchy for the processing steps flow.
       Uses !important throughout: Streamlit's own theme CSS frequently
       out-specifies plain element/class selectors (this is very likely
       why the old "### Processing steps" h3 rule wasn't visibly taking
       effect), so these rules are written to win regardless.
       ══════════════════════════════════════════════════════════════════ */

    /* Section label - sits ABOVE the step list, smallest/quietest text
       on the page so it never competes with the active step's title. */
    .lh-eyebrow {
        font-size: 0.75rem !important;
        font-weight: 500 !important;
        text-transform: uppercase !important;
        letter-spacing: 0.08em !important;
        color: inherit !important;
        opacity: 0.65;
        margin: 0 0 0.75rem 0 !important;
    }

    /* One row per already-passed or not-yet-reached step. Deliberately
       small and low-contrast - these are reference info, not decisions. */
    .lh-step-row {
        display: flex; align-items: center; gap: 10px;
        padding: 10px 2px; border-top: 1px solid rgba(128,128,128,0.28);
        font-size: 0.85rem !important; color: inherit !important;
    }
    .lh-step-icon { font-size: 0.95rem; width: 18px; text-align: center; flex-shrink: 0; }
    .lh-step-row > span:not(.lh-step-icon) { opacity: 0.75; }

    .lh-row-applied .lh-step-icon { color: #2F8F5F !important; }   /* green - readable on light AND dark */
    .lh-row-skipped .lh-step-icon { color: #B9741B !important; }   /* amber - readable on light AND dark */

    /* locked = dimmest */
    .lh-row-locked > span { opacity: 0.4 !important; }

    /* Active step header: number badge + title + "step N of M" counter,
       the single most prominent text block on the page. */
    .lh-step-header {
        display: flex; align-items: center; gap: 10px; margin-bottom: 14px;
    }
    .lh-badge {
        width: 26px; height: 26px; border-radius: 50%;
        background: #A13336; color: #fff !important;
        font-size: 0.8rem !important; font-weight: 600 !important;
        display: flex; align-items: center; justify-content: center;
        flex-shrink: 0;
    }
    .lh-step-title {
        font-size: 1.15rem !important; font-weight: 700 !important;
        color: inherit !important; letter-spacing: -0.01em;
    }
    .lh-step-counter {
        font-size: 0.7rem !important; color: inherit !important; opacity: 0.6;
        margin-left: auto; white-space: nowrap;
    }

    /* Bordered container Streamlit draws around the active step
       (st.container(border=True, key="active_step")) - recolor its
       default gray border to the brand accent so it visually reads
       as "you are here" before any text is read. */
    div[class*="st-key-active_step"] {
        border-color: #A13336 !important;
        border-width: 2px !important;
        background: rgba(139, 26, 26, 0.05) !important;
        border-radius: 8px !important;
    }

    /* Apply / Continue = primary brand action. Skip / Start Over =
       secondary, quieter, so the eye lands on the primary button first. */
    div[data-testid="stButton"] button[kind="primary"] {
        background: #A13336 !important; color: #fff !important;
        border: none !important; font-weight: 500 !important;
    }
    div[data-testid="stButton"] button[kind="primary"]:hover {
        background: #6e1414 !important;
    }
    div[data-testid="stButton"] button[kind="primary"]:disabled {
        background: rgba(161,51,54,0.35) !important; color: rgba(255,255,255,0.85) !important;
    }
    div[data-testid="stButton"] button[kind="secondary"] {
        background: transparent !important; color: inherit !important;
        border: 1px solid rgba(128,128,128,0.5) !important;
    }
    div[data-testid="stButton"] button[kind="secondary"]:hover {
        background: rgba(128,128,128,0.15) !important; color: inherit !important;
    }

    /* View switcher (PDF Editor / Certificate Creator) -- plain text
       tabs with an underline on the active one, NOT styled like the
       filled/outlined action buttons above (Apply, Skip, Continue...).
       The extra div[data-testid="stButton"] layer here isn't decorative
       -- it makes this selector MORE specific than the general
       button[kind="primary"] rule above, which is needed because equal
       specificity + both using !important resolves by source order, and
       Streamlit's own dynamically-injected styles can end up later in
       the DOM than this stylesheet regardless of where it appears in
       the code, silently winning ties. Genuinely higher specificity
       wins no matter the injection order. */
    div[class*="st-key-tab_pdf_modifier"] div[data-testid="stButton"] button,
    div[class*="st-key-tab_certificate_creator"] div[data-testid="stButton"] button,
    div[class*="st-key-tab_xero_invoice_creator"] div[data-testid="stButton"] button,
    div[class*="st-key-tab_window_diagram"] div[data-testid="stButton"] button {
        background: transparent !important;
        border: none !important;
        border-radius: 6px 6px 0 0 !important;
        border-bottom: 3px solid rgba(128,128,128,0.5) !important;
        color: inherit !important;          /* follows Light/Dark theme */
        opacity: 0.6;                       /* inactive = muted */
        font-weight: 500 !important;
        font-size: 14px !important;
        padding: 8px 4px !important;
        box-shadow: none !important;
    }
    /* label text inside the button must follow the button, not its own colour */
    div[class*="st-key-tab_pdf_modifier"] div[data-testid="stButton"] button *,
    div[class*="st-key-tab_certificate_creator"] div[data-testid="stButton"] button *,
    div[class*="st-key-tab_xero_invoice_creator"] div[data-testid="stButton"] button *,
    div[class*="st-key-tab_window_diagram"] div[data-testid="stButton"] button * {
        color: inherit !important;
    }
    /* ACTIVE tab: full-strength theme text, bold, thick brand underline and a
       light brand tint so it's obvious on a white background as well as dark */
    div[class*="st-key-tab_pdf_modifier"] div[data-testid="stButton"] button[kind="primary"],
    div[class*="st-key-tab_certificate_creator"] div[data-testid="stButton"] button[kind="primary"],
    div[class*="st-key-tab_xero_invoice_creator"] div[data-testid="stButton"] button[kind="primary"],
    div[class*="st-key-tab_window_diagram"] div[data-testid="stButton"] button[kind="primary"] {
        opacity: 1;
        font-weight: 700 !important;
        border-bottom: 3px solid #A13336 !important;
        background: rgba(161,51,54,0.10) !important;
    }
    div[class*="st-key-tab_pdf_modifier"] div[data-testid="stButton"] button:hover,
    div[class*="st-key-tab_certificate_creator"] div[data-testid="stButton"] button:hover,
    div[class*="st-key-tab_xero_invoice_creator"] div[data-testid="stButton"] button:hover,
    div[class*="st-key-tab_window_diagram"] div[data-testid="stButton"] button:hover {
        opacity: 1;
        background: rgba(128,128,128,0.12) !important;
    }
    div[class*="st-key-tab_pdf_modifier"] div[data-testid="stButton"] button[kind="primary"]:hover,
    div[class*="st-key-tab_certificate_creator"] div[data-testid="stButton"] button[kind="primary"]:hover,
    div[class*="st-key-tab_xero_invoice_creator"] div[data-testid="stButton"] button[kind="primary"]:hover,
    div[class*="st-key-tab_window_diagram"] div[data-testid="stButton"] button[kind="primary"]:hover {
        background: rgba(161,51,54,0.16) !important;
    }
</style>
"""


def inject_css():
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


def render_header():
    """Logo + title header shown at the top of the page."""
    col_logo, col_title = st.columns([1, 3])
    with col_logo:
        st.image(LOGO_PATH, use_container_width=True)
    with col_title:
        st.markdown("""
        <div style="padding-top: 1rem;">
            <div class="lh-title">Glass Weight Calculator</div>
            <div class="lh-sub">Logikhaus Pty Ltd - internal tool</div>
        </div>
        """, unsafe_allow_html=True)
    st.markdown('<hr style="border: 2px solid #A13336; margin-bottom: 2rem;">', unsafe_allow_html=True)


def render_eyebrow(text):
    """Small uppercase section label - used above the step list and file uploader."""
    st.markdown(f'<div class="lh-eyebrow">{text}</div>', unsafe_allow_html=True)


def render_step_row(step_num, label, state):
    """
    One line for an already-passed ('applied' / 'skipped') or not-yet-reached
    ('locked') step. state must be one of those three strings.
    """
    icon = {'applied': '✓', 'skipped': '⏭', 'locked': '🔒'}[state]
    text = f"Step {step_num}: {label}" + ("" if state == 'locked' else f" - {state}")
    st.markdown(
        f'<div class="lh-step-row lh-row-{state}">'
        f'<span class="lh-step-icon">{icon}</span><span>{text}</span></div>',
        unsafe_allow_html=True
    )


def render_active_step_header(step_num, total_steps, label):
    """Badge + title + counter for whichever step is currently active."""
    st.markdown(
        f'<div class="lh-step-header">'
        f'<span class="lh-badge">{step_num}</span>'
        f'<span class="lh-step-title">{label}</span>'
        f'<span class="lh-step-counter">step {step_num} of {total_steps}</span>'
        f'</div>',
        unsafe_allow_html=True
    )
