"""
Page styling and header markup for the Streamlit app.
Kept separate from app.py so tweaking colors/fonts never touches logic.
"""

import streamlit as st

CUSTOM_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&display=swap');

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
