"""
CERTIFICATE CREATOR
Completely independent of the PDF Modifier stepper (modules/steps.py) --
this reads a quote PDF, pulls out a handful of fields, and fills them
into the AGWA Glass Compliance Certificate template's actual PDF form
fields. No redaction, no cover boxes, no page-content editing at all:
a fillable PDF template has real named form fields (an "AcroForm"), so
writing a value into one is just setting a property, not surgically
editing drawn text like the Schedule Text Editor has to.

FIELD MAP (confirmed by inspecting the real template's widgets directly
-- see CERT_FIELD_MAP below for the actual PDF field names, which are
generic/auto-generated and don't match their on-page labels):

    Certificate field (visible label)   PDF field name
    ----------------------------------  --------------
    Client:                             Text Field 1
    Site:                                Text Field 2
    Date: (bottom signature date)        Text Field 6

Everything else on the template (company/AGWA number, description of
work, signature, work-type checkboxes) is already filled in on the
template itself and is left untouched -- fill_certificate() only ever
writes to the three fields above.

STATUS: the form-filling mechanism (fill_certificate) is built and
tested against the real template. extract_quote_data() is a stub --
the actual logic for pulling client/site/date out of a quote PDF is
TODO, to be filled in once that's worked out.
"""

from pypdf import PdfReader, PdfWriter

# Maps our own logical names to the template's actual (generic) field
# names, so the rest of the code can talk about "client"/"site"/"date"
# instead of remembering "Text Field 1" vs "Text Field 2" by heart.
CERT_FIELD_MAP = {
    'client': 'Text Field 1',
    'site':   'Text Field 2',
    'date':   'Text Field 6',
}


def extract_quote_data(doc):
    """
    TODO: not implemented yet -- logic for this to be provided separately.

    Should scan the quote PDF (a fitz.Document, same as what the PDF
    Modifier stepper works with) and return a dict with whatever subset
    of these keys it can determine:

        {'client': ..., 'site': ..., 'date': ...}

    Any key it can't confidently determine should simply be omitted (or
    set to None) rather than guessed -- fill_certificate() only writes
    the keys actually present in the dict it's given, so a partial
    result is fine and expected; the person using the tool can fill in
    whatever wasn't auto-detected by hand before generating the
    certificate.
    """
    raise NotImplementedError("extract_quote_data() logic not written yet")


def fill_certificate(template_bytes, data):
    """
    Fill the certificate template's form fields from `data` (a dict
    using the CERT_FIELD_MAP keys above -- 'client', 'site', 'date').
    Missing keys are simply left as whatever the template already has.

    Returns the filled PDF as bytes. Does not touch any field outside
    CERT_FIELD_MAP, so the template's pre-filled company/description/
    signature/checkboxes are always preserved exactly as they are.
    """
    import io

    reader = PdfReader(io.BytesIO(template_bytes))
    writer = PdfWriter()
    writer.append(reader)

    field_values = {
        CERT_FIELD_MAP[key]: value
        for key, value in data.items()
        if key in CERT_FIELD_MAP and value is not None
    }
    if field_values:
        writer.update_page_form_field_values(writer.pages[0], field_values)

    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()
