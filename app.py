import streamlit as st
import pandas as pd

from modules.styles import inject_css, render_header
from modules.glass_weight import load_glass_lookup, load_glass_type_lookup
from modules.frame_code_data import load_frame_codes, load_frame_rules
from modules.pipeline import process_pdf

# ── Page config ────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Logikhaus Glass Calculator",
    page_icon="🪟",
    layout="centered"
)

inject_css()
render_header()

# ── Load glass lookup ──────────────────────────────────────────────────────
try:
    with st.spinner('Loading glass data from sheet...'):
        glass_lookup      = load_glass_lookup()
        glass_type_lookup = load_glass_type_lookup()
    st.markdown(f'<div class="status-box">✓ Glass database loaded — {len(glass_lookup)} codes</div>',
                unsafe_allow_html=True)
except Exception as e:
    st.error(f'Could not connect to Google Sheets: {type(e).__name__}: {e}')
    import traceback
    st.code(traceback.format_exc())
    st.stop()

# ── Load frame code data (Module 4 connection) ──────────────────────────────
frame_codes, frame_rules = None, None
try:
    with st.spinner('Loading frame code data...'):
        frame_codes = load_frame_codes()
        frame_rules = load_frame_rules()
    st.markdown(
        f'<div class="status-box">✓ Frame code data loaded — '
        f'{len(frame_codes)} codes, {len(frame_rules)} rules</div>',
        unsafe_allow_html=True
    )
    with st.expander("Debug: preview CODES / RULESUPDATE tabs"):
        st.write("CODES tab — first 3 rows:")
        st.write(frame_codes[:3])
        st.write("RULESUPDATE tab — first 5 rows:")
        st.write(frame_rules[:5])
except Exception as e:
    st.warning(f'Could not load frame code sheet — frame code matching will be skipped. '
               f'({type(e).__name__}: {e})')

# ── File upload ────────────────────────────────────────────────────────────
st.markdown("### Upload schedule")
uploaded = st.file_uploader(
    "Drop a Logikhaus PDF schedule here",
    type="pdf",
    label_visibility="collapsed"
)

if uploaded:
    st.markdown("---")
    with st.spinner('Processing PDF...'):
        file_bytes = uploaded.read()
        annotated_bytes, rows, legend_status, frame_results = process_pdf(
            file_bytes, glass_lookup, frame_codes, frame_rules, glass_type_lookup
        )

    # ── Legend status feedback ──────────────────────────────────────────────
    if legend_status == 'added':
        st.markdown('<div class="status-box">✓ Legend page appended to end of quote</div>',
                     unsafe_allow_html=True)
    elif legend_status == 'already_present':
        st.markdown('<div class="status-box">Legend page already present — not duplicated</div>',
                     unsafe_allow_html=True)
    elif legend_status == 'missing_file':
        st.warning('LEGEND_page_for_Schedule.pdf not found in the app folder — legend page was not added.')

    # ── Summary table ──────────────────────────────────────────────────────
    st.markdown("### Results")
    df = pd.DataFrame([{k: v for k, v in r.items() if k != '_skip'} for r in rows])

    def highlight_row(row):
        original = rows[row.name]
        if original.get('_skip'):
            return ['color: #bbb'] * len(row)
        if 'No LHG' in str(row.get('Weight', '')) or 'skipped' in str(row.get('Weight', '')):
            return ['color: #c0392b'] * len(row)
        return [''] * len(row)

    st.dataframe(
        df.style.apply(highlight_row, axis=1),
        use_container_width=True,
        hide_index=True,
    )

    # Totals
    weights = []
    for r in rows:
        if not r['_skip'] and 'kg' in str(r['Weight']):
            try:
                weights.append(float(r['Weight'].replace(' kg', '')))
            except ValueError:
                pass

    if weights:
        col1, col2 = st.columns(2)
        col1.metric("Total glass items", len(rows))
        col2.metric("Total estimated weight", f"{sum(weights):.1f} kg")

    st.markdown("---")

    # ── Frame code results ───────────────────────────────────────────────────
    if frame_results:
        st.markdown("### Frame codes")
        frame_df = pd.DataFrame(frame_results)

        def highlight_frame_row(row):
            if row.get('Frame Code') == 'ERROR':
                return ['color: #c0392b'] * len(row)
            return [''] * len(row)

        display_df = frame_df.drop(columns=['Block Text'], errors='ignore')
        st.dataframe(
            display_df.style.apply(highlight_frame_row, axis=1),
            use_container_width=True,
            hide_index=True,
        )
        error_count = sum(1 for r in frame_results if r['Frame Code'] == 'ERROR')
        if error_count:
            st.warning(f'{error_count} window(s) could not be matched to a frame code — see Details above.')

        with st.expander("Debug: raw block text per window (what the matcher actually saw)"):
            for r in frame_results:
                st.write(f"**{r['Window']}** ({r['Frame Code']})")
                st.code(r.get('Block Text', ''), language=None)

        st.markdown("---")

    # ── Download ───────────────────────────────────────────────────────────
    st.markdown("### Download annotated PDF")
    out_name = uploaded.name.replace('.pdf', '_with_weights.pdf')
    st.download_button(
        label="Download annotated PDF",
        data=annotated_bytes,
        file_name=out_name,
        mime="application/pdf",
    )
