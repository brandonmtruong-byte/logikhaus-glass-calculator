"""
Page styling and header markup for the Streamlit app.
Kept separate from app.py so tweaking colors/fonts never touches logic.
"""

import streamlit as st

CUSTOM_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

    .block-container { padding-top: 2.5rem; max-width: 760px; }

    h1 { font-size: 1.5rem; font-weight: 600; letter-spacing: -0.02em; color: #111; }
    h3 { font-size: 0.85rem; font-weight: 500; text-transform: uppercase;
         letter-spacing: 0.08em; color: #888; margin-bottom: 0.5rem; }

    .lh-header {
        display: flex; align-items: center; gap: 14px;
        border-bottom: 2px solid #8B1A1A; padding-bottom: 1rem; margin-bottom: 2rem;
    }
    .lh-logo {
        background: #8B1A1A; color: white; font-weight: 700;
        font-size: 0.75rem; padding: 6px 10px; letter-spacing: 0.05em;
    }
    .lh-title { font-size: 1.25rem; font-weight: 600; color: #111; }
    .lh-sub   { font-size: 0.8rem; color: #888; margin-top: 2px; }

    .status-box {
        background: #f7f7f5; border-left: 3px solid #8B1A1A;
        padding: 0.75rem 1rem; border-radius: 0 4px 4px 0;
        font-size: 0.85rem; color: #333; margin-bottom: 1rem;
    }
    .skip-row { color: #aaa; font-style: italic; }

    div[data-testid="stDownloadButton"] button {
        background: #8B1A1A; color: white; border: none;
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
       STEPPER — clear visual hierarchy for the processing steps flow.
       Uses !important throughout: Streamlit's own theme CSS frequently
       out-specifies plain element/class selectors (this is very likely
       why the old "### Processing steps" h3 rule wasn't visibly taking
       effect), so these rules are written to win regardless.
       ══════════════════════════════════════════════════════════════════ */

    /* Section label — sits ABOVE the step list, smallest/quietest text
       on the page so it never competes with the active step's title. */
    .lh-eyebrow {
        font-size: 0.75rem !important;
        font-weight: 500 !important;
        text-transform: uppercase !important;
        letter-spacing: 0.08em !important;
        color: #7a7d85 !important;
        margin: 0 0 0.75rem 0 !important;
    }

    /* One row per already-passed or not-yet-reached step. Deliberately
       small and low-contrast — these are reference info, not decisions. */
    .lh-step-row {
        display: flex; align-items: center; gap: 10px;
        padding: 10px 2px; border-top: 1px solid rgba(255,255,255,0.08);
        font-size: 0.85rem !important;
    }
    .lh-step-icon { font-size: 0.95rem; width: 18px; text-align: center; flex-shrink: 0; }

    .lh-row-applied { color: #9a9da5 !important; }
    .lh-row-applied .lh-step-icon { color: #4caf82 !important; }   /* done = green */

    .lh-row-skipped { color: #9a9da5 !important; }
    .lh-row-skipped .lh-step-icon { color: #e0a030 !important; }   /* skipped = amber, distinct from done */

    .lh-row-locked { color: #5a5d65 !important; }
    .lh-row-locked .lh-step-icon { color: #454850 !important; }    /* locked = dimmest */

    /* Active step header: number badge + title + "step N of M" counter,
       the single most prominent text block on the page. */
    .lh-step-header {
        display: flex; align-items: center; gap: 10px; margin-bottom: 14px;
    }
    .lh-badge {
        width: 26px; height: 26px; border-radius: 50%;
        background: #8B1A1A; color: #fff !important;
        font-size: 0.8rem !important; font-weight: 600 !important;
        display: flex; align-items: center; justify-content: center;
        flex-shrink: 0;
    }
    .lh-step-title {
        font-size: 1.15rem !important; font-weight: 700 !important;
        color: #f0f0f2 !important; letter-spacing: -0.01em;
    }
    .lh-step-counter {
        font-size: 0.7rem !important; color: #7a7d85 !important;
        margin-left: auto; white-space: nowrap;
    }

    /* Bordered container Streamlit draws around the active step
       (st.container(border=True, key="active_step")) — recolor its
       default gray border to the brand accent so it visually reads
       as "you are here" before any text is read. */
    div[class*="st-key-active_step"] {
        border-color: #8B1A1A !important;
        background: rgba(139, 26, 26, 0.05) !important;
        border-radius: 8px !important;
    }

    /* Apply / Continue = primary brand action. Skip / Start Over =
       secondary, quieter, so the eye lands on the primary button first. */
    div[data-testid="stButton"] button[kind="primary"] {
        background: #8B1A1A !important; color: #fff !important;
        border: none !important; font-weight: 500 !important;
    }
    div[data-testid="stButton"] button[kind="primary"]:hover {
        background: #6e1414 !important;
    }
    div[data-testid="stButton"] button[kind="primary"]:disabled {
        background: #4a3030 !important; color: #9a9da5 !important;
    }
    div[data-testid="stButton"] button[kind="secondary"] {
        background: transparent !important; color: #9a9da5 !important;
        border: 1px solid #3a3d45 !important;
    }
    div[data-testid="stButton"] button[kind="secondary"]:hover {
        background: rgba(255,255,255,0.05) !important; color: #d0d2d8 !important;
    }
</style>
"""


def inject_css():
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


def render_header():
    """Logo + title header shown at the top of the page."""
    col_logo, col_title = st.columns([1, 3])
    with col_logo:
        st.image("Logikhaus_logo.jpg", use_container_width=True)
    with col_title:
        st.markdown("""
        <div style="padding-top: 1rem;">
            <div class="lh-title">Glass Weight Calculator</div>
            <div class="lh-sub">Logikhaus Pty Ltd — internal tool</div>
        </div>
        """, unsafe_allow_html=True)
    st.markdown('<hr style="border: 2px solid #8B1A1A; margin-bottom: 2rem;">', unsafe_allow_html=True)


def render_eyebrow(text):
    """Small uppercase section label — used above the step list and file uploader."""
    st.markdown(f'<div class="lh-eyebrow">{text}</div>', unsafe_allow_html=True)


def render_step_row(step_num, label, state):
    """
    One line for an already-passed ('applied' / 'skipped') or not-yet-reached
    ('locked') step. state must be one of those three strings.
    """
    icon = {'applied': '✓', 'skipped': '⏭', 'locked': '🔒'}[state]
    text = f"Step {step_num}: {label}" + ("" if state == 'locked' else f" — {state}")
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
