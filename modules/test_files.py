"""
TEST FILES — dev-only shortcut for picking a PDF already committed to the
repo (in the "Test Files" folder) instead of uploading one by hand.

Intentionally NOT part of the stepper flow in modules/steps.py — this
just gets bytes onto the screen for app.py to feed into the exact same
document-initialization path a real upload uses. Nothing here touches
logo_stamper, glass_weight, schedule_editor, etc.
"""

import os

from .config import TEST_FILES_DIR


def list_test_files():
    """
    Return a sorted list of .pdf filenames in the Test Files folder.
    Empty list if the folder doesn't exist (e.g. locally before it's
    been added) rather than raising, so app.py can just hide the picker.
    """
    if not os.path.isdir(TEST_FILES_DIR):
        return []
    return sorted(f for f in os.listdir(TEST_FILES_DIR) if f.lower().endswith(".pdf"))


def load_test_file(filename):
    """Return the raw bytes of a test file, by name (as returned by list_test_files())."""
    path = os.path.join(TEST_FILES_DIR, filename)
    with open(path, "rb") as f:
        return f.read()
