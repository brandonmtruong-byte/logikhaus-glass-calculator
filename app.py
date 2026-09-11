import os
import re
import streamlit as st
import pandas as pd
import fitz

from modules.styles import inject_css, render_header, render_eyebrow, render_step_row, render_active_step_header
from modules.glass_weight import load_glass_lookup, load_glass_type_lookup
from modules.frame_code_data import load_frame_codes, load_frame_rules
from modules.config import TEMPLATE_XLSX_PATH, CERTIFICATE_TEMPLATE_PATH, WINDOW_CERT_TEMPLATE_DG_PATH, WINDOW_CERT_TEMPLATE_TG_PATH
from modules.test_files import list_test_files, load_test_file
from modules.certificate_creator import (
    extract_quote_data, fill_certificate, fill_window_certificate, pick_window_cert_template_path,
    WIND_RATING_CHECKBOX_MAP, BUSHFIRE_CHECKBOX_MAP,
)
from modules.steps import (
    STEP_ORDER, STEP_LABELS,
    apply_logo, apply_mass, apply_frame, apply_legend, apply_text_replace,
)

# ── Page config ────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Logikhaus Glass Calculator",
    page_icon="🪟",
    layout="centered"
)

inject_css()
render_header()

# ── View switcher ────────────────────────────────────────────────────────
# Deliberately NOT st.tabs(): Streamlit executes every tab's body on every
# rerun regardless of which one is visually shown, so st.tabs() alone
# wouldn't stop switching to Certificate Creator from still hitting
# Google Sheets for glass/frame data. This uses real if/elif branching on
# session_state instead, so only the active view's code ever runs.
if 'active_view' not in st.session_state:
    st.session_state.active_view = 'PDF Modifier'

col_view1, col_view2 = st.columns(2)
with col_view1:
    with st.container(key="tab_pdf_modifier"):
        if st.button(
            "PDF Editor", use_container_width=True,
            type="primary" if st.session_state.active_view == 'PDF Modifier' else "secondary",
        ):
            st.session_state.active_view = 'PDF Modifier'
            st.rerun()
with col_view2:
    with st.container(key="tab_certificate_creator"):
        if st.button(
            "Certificate Creator", use_container_width=True,
            type="primary" if st.session_state.active_view == 'Certificate Creator' else "secondary",
        ):
            st.session_state.active_view = 'Certificate Creator'
            st.rerun()

st.markdown("---")

# ── Preview renderers (table styling for the mass / frame steps) ───────────
# Function definitions only -- harmless to leave outside the view branches
# below, since defining a function has no side effects until it's called.

def render_mass_preview(result, doc):
    rows  = result['rows']
    pages = result['pages']
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

    if pages:
        show_images = st.toggle(
            f"Show preview of {len(pages)} page(s)", value=False, key="mass_show_images"
        )
        if show_images:
            # Draw highlights on a throwaway copy, never the real working
            # doc -- doc.tobytes() + reopen keeps this purely visual with
            # zero risk of touching what actually gets downloaded.
            preview_doc = fitz.open(stream=doc.tobytes(), filetype="pdf")
            highlight_rects = result.get('highlight_rects', {})
            for pno in pages:
                preview_page = preview_doc[pno - 1]
                for rect in highlight_rects.get(pno, []):
                    preview_page.draw_rect(
                        rect, color=(0.85, 0.55, 0), width=1.2,
                        fill=(1, 0.92, 0.55), fill_opacity=0.45, overlay=True
                    )
                pix = preview_page.get_pixmap(dpi=150)
                st.image(pix.tobytes("png"), caption=f"Page {pno}", use_container_width=True)
            preview_doc.close()


def render_frame_preview(result, doc):
    rows  = result['rows']
    pages = result['pages']
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
        st.warning(f'{error_count} window(s) could not be matched to a frame code- see Details below.')

    if pages:
        show_images = st.toggle(
            f"Show preview of {len(pages)} page(s)", value=False, key="frame_show_images"
        )
        if show_images:
            # Same throwaway-copy pattern as the mass preview above.
            preview_doc = fitz.open(stream=doc.tobytes(), filetype="pdf")
            highlight_rects = result.get('highlight_rects', {})
            for pno in pages:
                preview_page = preview_doc[pno - 1]
                for rect in highlight_rects.get(pno, []):
                    preview_page.draw_rect(
                        rect, color=(0.85, 0.55, 0), width=1.2,
                        fill=(1, 0.92, 0.55), fill_opacity=0.45, overlay=True
                    )
                pix = preview_page.get_pixmap(dpi=150)
                st.image(pix.tobytes("png"), caption=f"Page {pno}", use_container_width=True)
            preview_doc.close()

    if st.toggle("Show raw block text per window", value=False, key="frame_show_debug"):
        for r in rows:
            st.write(f"**{r['Window']}** ({r['Frame Code']})")
            st.code(r.get('Block Text', ''), language=None)


def render_text_replace_preview(result):
    st.markdown(
        f'<div class="status-box">✓ {result["replaced"]} replacement(s), '
        f'{result["deleted"]} deletion(s), across page(s) '
        f'{result["pages"] if result["pages"] else "none"}</div>',
        unsafe_allow_html=True
    )

    if result["not_found_warnings"]:
        st.warning("Some instructions may need a closer look- either they "
                   "didn't match anything, or they matched some but missed a similar variant:")
        for w in result["not_found_warnings"]:
            st.write(f"- {w}")

    if result["overlap_warnings"]:
        st.warning("Possible text overlap detected- review these pages before continuing:")
        for pno, page_warnings in result["overlap_warnings"].items():
            for w in page_warnings:
                st.write(f"- Page {pno}: {w}")

    if result["preview_images"]:
        show_images = st.toggle(
            f"Show preview of {len(result['preview_images'])} changed page(s)",
            value=False, key="text_replace_show_images"
        )
        if show_images:
            for pno in sorted(result["preview_images"]):
                st.image(result["preview_images"][pno], caption=f"Page {pno}", use_container_width=True)


def render_legend_preview(status):
    if status == 'added':
        st.markdown('<div class="status-box">✓ Legend page appended to end of quote</div>', unsafe_allow_html=True)
    elif status == 'already_present':
        st.markdown('<div class="status-box">Legend page already present- not duplicated</div>',
                     unsafe_allow_html=True)
    elif status == 'missing_file':
        st.warning('LEGEND_page_for_Schedule.pdf not found in the app folder- legend page was not added.')


def start_new_document(file_bytes, file_name, unique_id):
    """
    (Re)initialize the stepper session state for a new document -- shared
    by both a real upload and the dev-only test file picker below, so the
    two paths can never drift apart or process a file differently.
    """
    if st.session_state.get('doc') is not None:
        st.session_state.doc.close()
    st.session_state.uploaded_file_id = unique_id
    st.session_state.doc              = fitz.open(stream=file_bytes, filetype="pdf")
    st.session_state.file_name        = file_name
    st.session_state.current_step     = 0
    st.session_state.step_status      = {k: 'pending' for k in STEP_ORDER}
    st.session_state.step_results     = {}


def sanitize_filename_part(text):
    """
    Strip characters that are invalid (or awkward) in a filename, for
    building download filenames out of free text like a client name.
    Collapses whitespace and trims, so "Caitlin & Chris  Morey" becomes
    "Caitlin & Chris Morey" rather than leaving double spaces.
    """
    cleaned = re.sub(r'[<>:"/\\|?*]', '', text)
    return re.sub(r'\s+', ' ', cleaned).strip()


# ═════════════════════════════════════════════════════════════════════════
#  VIEW: PDF MODIFIER — the existing stepper flow, entirely unchanged
# ═════════════════════════════════════════════════════════════════════════
if st.session_state.active_view == 'PDF Modifier':

    # ── Load reference data (Google Sheets - independent of any uploaded PDF)
    try:
        with st.spinner('Loading glass data from sheet...'):
            glass_lookup      = load_glass_lookup()
            glass_type_lookup = load_glass_type_lookup()
        st.markdown(f'<div class="status-box">✓ Glass database loaded - {len(glass_lookup)} codes</div>',
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
            f'<div class="status-box">✓ Frame code data loaded - '
            f'{len(frame_codes)} codes, {len(frame_rules)} rules</div>',
            unsafe_allow_html=True
        )
    except Exception as e:
        st.warning(f'Could not load frame code sheet- the Frame Code Matcher step will be skippable only. '
                   f'({type(e).__name__}: {e})')

    st.markdown("---")

    # ── Dev-only: load a test file already committed to the repo ───────────
    # Not part of the stepper flow in modules/steps.py -- this is purely a
    # shortcut for getting bytes onto the screen, feeding into the exact
    # same start_new_document() path a real upload uses below.
    test_files = list_test_files()
    if test_files:
        with st.expander("Load a test file (dev only)", expanded=False):
            selected_test_file = st.selectbox(
                "Choose a file from the Test Files folder", test_files, key="test_file_select"
            )
            if st.button("Load test file", key="load_test_file_btn", type="secondary"):
                start_new_document(
                    load_test_file(selected_test_file),
                    selected_test_file,
                    f"testfile:{selected_test_file}",
                )
                st.session_state.test_file_loaded_message = selected_test_file
                st.rerun()

    if st.session_state.get('test_file_loaded_message'):
        st.success(f"✓ Loaded test file: {st.session_state.test_file_loaded_message}")
        del st.session_state['test_file_loaded_message']

    # ── File upload ─────────────────────────────────────────────────────
    render_eyebrow("Upload schedule")
    uploaded = st.file_uploader(
        "Drop a Logikhaus PDF schedule here",
        type="pdf",
        label_visibility="collapsed"
    )

    # New upload -> (re)initialize the stepper state. A test file may
    # already have set st.session_state.doc above -- either way this only
    # fires when uploaded is a genuinely new file, so it can't clobber a
    # loaded test file.
    if uploaded is not None and st.session_state.get('uploaded_file_id') != uploaded.file_id:
        start_new_document(uploaded.read(), uploaded.name, uploaded.file_id)

    if st.session_state.get('doc') is None:
        st.stop()

    doc = st.session_state.doc

    st.markdown("---")

    col_title, col_reset = st.columns([4, 1])
    with col_title:
        render_eyebrow("Processing steps")
    with col_reset:
        if st.button("Start Over", use_container_width=True, type="secondary"):
            doc.close()
            for key in ['doc', 'uploaded_file_id', 'file_name', 'current_step', 'step_status', 'step_results']:
                st.session_state.pop(key, None)
            st.rerun()

    # ── Stepper ──────────────────────────────────────────────────────────
    for i, step_key in enumerate(STEP_ORDER):
        label  = STEP_LABELS[step_key]
        status = st.session_state.step_status[step_key]

        # Already-passed step: collapsed one-line summary (✓ applied / ⏭ skipped)
        if i < st.session_state.current_step:
            render_step_row(i + 1, label, status)
            continue

        # Not-yet-reached step: locked placeholder
        if i > st.session_state.current_step:
            render_step_row(i + 1, label, 'locked')
            continue

        # ── The current active step- highlighted bordered container ─────
        with st.container(border=True, key="active_step"):
            render_active_step_header(i + 1, len(STEP_ORDER), label)

            if status == 'pending':
                # Frame step needs sheet data to be available at all
                frame_data_missing = step_key == 'frame' and (frame_codes is None or frame_rules is None)
                if frame_data_missing:
                    st.warning("Frame code sheet isn't available- this step can only be skipped.")

                # Text replace step needs its own instructions .xlsx uploaded first
                text_replace_xlsx = None
                if step_key == 'text_replace':
                    if os.path.exists(TEMPLATE_XLSX_PATH):
                        with open(TEMPLATE_XLSX_PATH, "rb") as f:
                            st.download_button(
                                "Download blank instructions template (.xlsx)",
                                data=f.read(),
                                file_name="template_instructions.xlsx",
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                key=f"template_download_{step_key}",
                            )
                    text_replace_xlsx = st.file_uploader(
                        "Instructions spreadsheet (.xlsx)", type="xlsx", key=f"xlsx_upload_{step_key}"
                    )

                text_replace_missing = step_key == 'text_replace' and text_replace_xlsx is None
                apply_disabled = frame_data_missing or text_replace_missing

                col_apply, col_skip = st.columns([3, 1])
                with col_apply:
                    apply_clicked = st.button(
                        f"Apply {label}", key=f"apply_{step_key}",
                        use_container_width=True, disabled=apply_disabled, type="primary",
                    )
                with col_skip:
                    skip_clicked = st.button(
                        "Skip", key=f"skip_{step_key}", use_container_width=True, type="secondary",
                    )

                if apply_clicked:
                    with st.spinner(f'Applying {label}...'):
                        if step_key == 'logo':
                            apply_logo(doc)
                            st.session_state.step_results[step_key] = None
                        elif step_key == 'text_replace':
                            result = apply_text_replace(doc, text_replace_xlsx.getvalue())
                            st.session_state.doc = result.pop('doc')
                            st.session_state.step_results[step_key] = result
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

                st.markdown(f'<div class="status-box">✓ {label} applied</div>', unsafe_allow_html=True)

                with st.expander("View details", expanded=False):
                    if step_key == 'logo':
                        pix = doc[0].get_pixmap(matrix=fitz.Matrix(1.3, 1.3))
                        st.image(pix.tobytes("png"), caption="Page 1 preview", use_container_width=True)
                    elif step_key == 'text_replace':
                        render_text_replace_preview(result)
                    elif step_key == 'mass':
                        render_mass_preview(result, doc)
                    elif step_key == 'frame':
                        render_frame_preview(result, doc)
                    elif step_key == 'legend':
                        render_legend_preview(result)

                if st.button("Continue →", key=f"continue_{step_key}", use_container_width=True, type="primary"):
                    st.session_state.current_step += 1
                    st.rerun()

    # ── All steps done: download ────────────────────────────────────────
    if st.session_state.current_step >= len(STEP_ORDER):
        render_eyebrow("All steps complete")
        out_bytes = doc.tobytes()
        out_name  = st.session_state.file_name.replace('.pdf', '_processed.pdf')
        st.download_button(
            label="Download annotated PDF",
            data=out_bytes,
            file_name=out_name,
            mime="application/pdf",
            use_container_width=True,
        )


# ═════════════════════════════════════════════════════════════════════════
#  VIEW: CERTIFICATE CREATOR — fully independent, no editor state touched
# ═════════════════════════════════════════════════════════════════════════
elif st.session_state.active_view == 'Certificate Creator':

    render_eyebrow("Upload quote")
    cert_uploaded = st.file_uploader(
        "Drop a quote PDF here", type="pdf", label_visibility="collapsed", key="cert_uploader"
    )

    # Auto-scan the moment a new quote is uploaded -- no button needed.
    if cert_uploaded is not None and st.session_state.get('cert_uploaded_file_id') != cert_uploaded.file_id:
        st.session_state.cert_uploaded_file_id = cert_uploaded.file_id
        st.session_state.cert_quote_bytes      = cert_uploaded.read()

        quote_doc = fitz.open(stream=st.session_state.cert_quote_bytes, filetype="pdf")
        try:
            detected = extract_quote_data(quote_doc)
        except NotImplementedError:
            detected = {}
            st.info("Quote scanning isn't built yet- fill in the fields below by hand.")
        quote_doc.close()

        st.session_state.cert_client       = detected.get('client', '') or ''
        # Kept separate from cert_client: this is the raw value straight
        # off the quote's own "Client:" line, used for filenames so it
        # stays correct even if the Client field above gets hand-edited.
        st.session_state.cert_client_quote_field = detected.get('client_quote_field', '') or ''
        st.session_state.cert_site         = detected.get('site', '') or ''
        st.session_state.cert_date         = detected.get('date', '') or ''
        st.session_state.cert_completed_on = ''  # never auto-detected -- always left for manual entry
        st.session_state.cert_delivered_on = ''  # same -- always left for manual entry

        # Detected but not user-editable -- these drive the Window
        # Compliance certificate's checkboxes and template choice
        # directly, there's no free-text field for them in the UI.
        st.session_state.cert_site_wind_rating = detected.get('site_wind_rating')
        st.session_state.cert_bushfire_rating  = detected.get('bushfire_rating')
        st.session_state.cert_glazing_type     = detected.get('glazing_type')

    if st.session_state.get('cert_quote_bytes') is None:
        st.stop()

    render_eyebrow("Detected fields - edit if needed")
    
    st.session_state.cert_client       = st.text_input("Client", value=st.session_state.get('cert_client', ''))
    st.session_state.cert_site         = st.text_input("Site", value=st.session_state.get('cert_site', ''))

    wind_options = list(WIND_RATING_CHECKBOX_MAP.keys())
    detected_wind = st.session_state.get('cert_site_wind_rating')
    wind_index = wind_options.index(detected_wind) if detected_wind in wind_options else 0
    st.session_state.cert_site_wind_rating = st.selectbox(
        "Site Wind Rating", wind_options, index=wind_index
    )

    bushfire_options = list(BUSHFIRE_CHECKBOX_MAP.keys())
    detected_bushfire = st.session_state.get('cert_bushfire_rating')
    bushfire_index = bushfire_options.index(detected_bushfire) if detected_bushfire in bushfire_options else 0
    st.session_state.cert_bushfire_rating = st.selectbox(
        "Bushfire Rating", bushfire_options, index=bushfire_index
    )

    st.session_state.cert_completed_on = st.text_input(
        "Completed on", value=st.session_state.get('cert_completed_on', '')
    )
    st.session_state.cert_delivered_on = st.text_input(
        "Delivered on", value=st.session_state.get('cert_delivered_on', '')
    )
    st.session_state.cert_date         = st.text_input("Date", value=st.session_state.get('cert_date', ''))

    st.markdown("---")

    # Generate + download in one click: the filled PDF is (cheaply)
    # rebuilt from whatever's currently in the fields on every rerun, so
    # it's always ready the instant this button renders -- no separate
    # "Generate" step before the download becomes available.
    if os.path.exists(CERTIFICATE_TEMPLATE_PATH):
        with open(CERTIFICATE_TEMPLATE_PATH, "rb") as f:
            template_bytes = f.read()
        filled_bytes = fill_certificate(template_bytes, {
            'client':       st.session_state.cert_client,
            'site':         st.session_state.cert_site,
            'completed_on': st.session_state.cert_completed_on,
            'date':         st.session_state.cert_date,
        })
        st.download_button(
            "Generate and download Glass Compliance Certificate",
            data=filled_bytes,
            file_name=f"Glass_Compliance_Certificate_{sanitize_filename_part(st.session_state.cert_client_quote_field)}.pdf",
            mime="application/pdf",
            type="primary",
            use_container_width=True,
        )
    else:
        st.error("Certificate template not found in the app folder.")

    window_cert_path = pick_window_cert_template_path(
        WINDOW_CERT_TEMPLATE_DG_PATH, WINDOW_CERT_TEMPLATE_TG_PATH,
        st.session_state.get('cert_glazing_type'),
    )
    if os.path.exists(window_cert_path):
        with open(window_cert_path, "rb") as f:
            window_template_bytes = f.read()
        window_filled_bytes = fill_window_certificate(window_template_bytes, {
            'client':            st.session_state.cert_client,
            'site':              st.session_state.cert_site,
            'delivered_on':      st.session_state.cert_delivered_on,
            'date':              st.session_state.cert_date,
            'site_wind_rating':  st.session_state.get('cert_site_wind_rating'),
            'bushfire_rating':   st.session_state.get('cert_bushfire_rating'),
        })
        st.download_button(
            "Generate and download Window Compliance Certificate",
            data=window_filled_bytes,
            file_name=f"Window_Compliance_Certificate_{sanitize_filename_part(st.session_state.cert_client_quote_field)}.pdf",
            mime="application/pdf",
            type="primary",
            use_container_width=True,
        )
    else:
        st.error("Window Compliance Certificate template not found in the app folder.")
