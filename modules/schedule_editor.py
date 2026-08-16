"""
SCHEDULE TEXT EDITOR — bridge to the vendored pdf_text_editor.py
Wraps process() from modules/schedule_text_editor.py (a vendored, unmodified
copy of jennynt-LGH/Schedule-Editor's engine — see that file's own
docstring for the full instructions-spreadsheet format) so it can slot
into the stepper flow.

process() works on file PATHS, not an in-memory document, so this writes
the current working doc out to a temp file, runs process() on it, then
reloads the result and hands back a fresh fitz.Document for app.py to
swap into st.session_state.doc. The old doc is closed here; the caller
should not keep using it after this returns.
"""

import os
import tempfile

import fitz

from .schedule_text_editor import process as run_text_editor


def apply_text_replace(doc, xlsx_bytes):
    """
    Run the Schedule Text Editor against the working document.

    Returns a dict:
        {
            'doc':               new fitz.Document (already reopened —
                                  swap this into st.session_state.doc)
            'replaced':          int
            'deleted':           int
            'pages':             sorted list of modified page numbers
            'overlap_warnings':  {page_num: [warning str, ...]}
            'not_found_warnings': [warning str, ...]
            'preview_images':    {page_num: png bytes}
        }
    """
    with tempfile.TemporaryDirectory() as workdir:
        pdf_path      = os.path.join(workdir, "input.pdf")
        xlsx_path     = os.path.join(workdir, "instructions.xlsx")
        output_path   = os.path.join(workdir, "output.pdf")
        preview_dir   = os.path.join(workdir, "previews")

        doc.save(pdf_path)
        with open(xlsx_path, "wb") as f:
            f.write(xlsx_bytes)

        replaced, deleted, pages, overlap_warnings, not_found_warnings = run_text_editor(
            pdf_path, xlsx_path, output_path, preview_dir
        )

        with open(output_path, "rb") as f:
            output_bytes = f.read()

        preview_images = {}
        for pno in pages:
            preview_path = os.path.join(preview_dir, f"page{pno}_preview.png")
            if os.path.exists(preview_path):
                with open(preview_path, "rb") as f:
                    preview_images[pno] = f.read()

    doc.close()
    new_doc = fitz.open(stream=output_bytes, filetype="pdf")

    return {
        'doc':                new_doc,
        'replaced':           replaced,
        'deleted':             deleted,
        'pages':              pages,
        'overlap_warnings':    overlap_warnings,
        'not_found_warnings':  not_found_warnings,
        'preview_images':     preview_images,
    }
