import streamlit as st
import pandas as pd
import fitz

from modules.styles import inject_css, render_header
from modules.glass_weight import load_glass_lookup, load_glass_type_lookup
from modules.frame_code_data import load_frame_codes, load_frame_rules
from modules.steps import STEP_ORDER, STEP_LABELS, apply_logo, apply_mass, apply_frame, apply_legend

# ── Page config ────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Logikhaus Glass Calculator",
    page_icon="🪟",
    layout="centered"
)

inject_css()
render_header()

# ── Load reference data (Google Sheets — independent of any uploaded PDF) ──
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
except Exception as e:
    st.warning(f'Could not load frame code sheet — the Frame Code Matcher step will be skippable only. '
               f'({type(e).__name__}: {e})')

st.markdown("---")

# ── Preview renderers (table styling for the mass / frame steps) ───────────

def render_mass_preview(rows):
    if not rows:
        st.info("No glass lines found on this document.")
        return
    df = pd.DataFrame([{k: v for k, v in r.items() if k != '_skip'} for r in rows])

    def highlight_row(row):
        original = rows[row.name]
        if original.get('_skip'):
            return ['color: #bbb'] * len(row)
        if 'No LHG' in str(row.get('Weight', '')) or 'skipped' in str(row.get('Weight', '')):
            return ['color: #c0392b'] * len(row)
        return [''] * len(row)

    st.dataframe(df.style.apply(highlight_row, axis=1), use_container_width=True, hide_index=True)

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


def render_frame_preview(rows):
    if not rows:
        st.info("No windows found on this document.")
        return
    frame_df = pd.DataFrame(rows)

    def highlight_frame_row(row):
        if row.get('Frame Code') == 'ERROR':
            return ['color: #c0392b'] * len(row)
        return [''] * len(row)

    display_df = frame_df.drop(columns=['Block Text'], errors='ignore')
    st.dataframe(display_df.style.apply(highlight_frame_row, axis=1), use_container_width=True, hide_index=True)

    error_count = sum(1 for r in rows if r['Frame Code'] == 'ERROR')
    if error_count:
        st.warning(f'{error_count} window(s) could not be matched to a frame code — see Details below.')

    with st.expander("Debug: raw block text per window"):
        for r in rows:
            st.write(f"**{r['Window']}** ({r['Frame Code']})")
            st.code(r.get('Block Text', ''), language=None)


def render_legend_preview(status):
    if status == 'added':
        st.markdown('<div class="status-box">✓ Legend page appended to end of quote</div>', unsafe_allow_html=True)
    elif status == 'already_present':
        st.markdown('<div class="status-box">Legend page already present — not duplicated</div>',
                     unsafe_allow_html=True)
    elif status == 'missing_file':
        st.warning('LEGEND_page_for_Schedule.pdf not found in the app folder — legend page was not added.')


# ── File upload ──────────────────────────────────────────────────────────
st.markdown("### Upload schedule")
uploaded = st.file_uploader(
    "Drop a Logikhaus PDF schedule here",
    type="pdf",
    label_visibility="collapsed"
)

if uploaded is None:
    st.stop()

# New upload (or first upload) -> (re)initialize the stepper state
if st.session_state.get('uploaded_file_id') != uploaded.file_id:
    if st.session_state.get('doc') is not None:
        st.session_state.doc.close()
    st.session_state.uploaded_file_id = uploaded.file_id
    st.session_state.doc              = fitz.open(stream=uploaded.read(), filetype="pdf")
    st.session_state.file_name        = uploaded.name
    st.session_state.current_step     = 0
    st.session_state.step_status      = {k: 'pending' for k in STEP_ORDER}
    st.session_state.step_results     = {}

doc = st.session_state.doc

st.markdown("---")

col_title, col_reset = st.columns([4, 1])
with col_title:
    st.markdown("### Processing steps")
with col_reset:
    if st.button("Start Over", use_container_width=True):
        doc.close()
        for key in ['doc', 'uploaded_file_id', 'file_name', 'current_step', 'step_status', 'step_results']:
            st.session_state.pop(key, None)
        st.rerun()

# ── Stepper ──────────────────────────────────────────────────────────────
for i, step_key in enumerate(STEP_ORDER):
    label  = STEP_LABELS[step_key]
    status = st.session_state.step_status[step_key]

    # Already-passed step: collapsed one-line summary
    if i < st.session_state.current_step:
        icon = "✓" if status == 'applied' else "⏭"
        st.markdown(f"**{icon} Step {i + 1}: {label}** — {status}")
        continue

    # Not-yet-reached step: locked placeholder
    if i > st.session_state.current_step:
        st.markdown(f"<span style='color:#bbb'>Step {i + 1}: {label} — locked</span>", unsafe_allow_html=True)
        continue

    # ── The current active step ─────────────────────────────────────────
    st.markdown(f"#### Step {i + 1} of {len(STEP_ORDER)}: {label}")

    if status == 'pending':
        # Frame step needs sheet data to be available at all
        frame_data_missing = step_key == 'frame' and (frame_codes is None or frame_rules is None)
        if frame_data_missing:
            st.warning("Frame code sheet isn't available — this step can only be skipped.")

        col_apply, col_skip = st.columns([3, 1])
        with col_apply:
            apply_clicked = st.button(
                f"Apply {label}", key=f"apply_{step_key}",
                use_container_width=True, disabled=frame_data_missing,
            )
        with col_skip:
            skip_clicked = st.button("Skip", key=f"skip_{step_key}", use_container_width=True)

        if apply_clicked:
            with st.spinner(f'Applying {label}...'):
                if step_key == 'logo':
                    apply_logo(doc)
                    st.session_state.step_results[step_key] = None
                elif step_key == 'mass':
                    st.session_state.step_results[step_key] = apply_mass(doc, glass_lookup)
                elif step_key == 'frame':
                    st.session_state.step_results[step_key] = apply_frame(
                        doc, frame_codes, frame_rules, glass_type_lookup
                    )
                elif step_key == 'legend':
                    st.session_state.step_results[step_key] = apply_legend(doc)
            st.session_state.step_status[step_key] = 'applied'
            st.rerun()

        if skip_clicked:
            st.session_state.step_status[step_key] = 'skipped'
            st.session_state.current_step += 1
            st.rerun()

    elif status == 'applied':
        result = st.session_state.step_results.get(step_key)

        if step_key == 'logo':
            pix = doc[0].get_pixmap(matrix=fitz.Matrix(1.3, 1.3))
            st.image(pix.tobytes("png"), caption="Page 1 preview", use_container_width=True)
        elif step_key == 'mass':
            render_mass_preview(result)
        elif step_key == 'frame':
            render_frame_preview(result)
        elif step_key == 'legend':
            render_legend_preview(result)

        if st.button("Continue →", key=f"continue_{step_key}", use_container_width=True):
            st.session_state.current_step += 1
            st.rerun()

    st.markdown("---")

# ── All steps done: download ────────────────────────────────────────────
if st.session_state.current_step >= len(STEP_ORDER):
    st.markdown("### All steps complete")
    out_bytes = doc.tobytes()
    out_name  = st.session_state.file_name.replace('.pdf', '_processed.pdf')
    st.download_button(
        label="Download annotated PDF",
        data=out_bytes,
        file_name=out_name,
        mime="application/pdf",
        use_container_width=True,
    )
