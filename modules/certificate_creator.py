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
    Completed on:                        Text Field 3  (always left blank -- not auto-detected)
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

import re
from datetime import datetime

from pypdf import PdfReader, PdfWriter

# Maps our own logical names to the template's actual (generic) field
# names, so the rest of the code can talk about "client"/"site"/"date"
# instead of remembering "Text Field 1" vs "Text Field 2" by heart.
CERT_FIELD_MAP = {
    'client':       'Text Field 1',
    'site':         'Text Field 2',
    'completed_on': 'Text Field 3',
    'date':         'Text Field 6',
}


def extract_quote_data(doc):
    """
    Scan a quote PDF (a fitz.Document) and return {'client', 'site', 'date'}.

    Only page 1 is scanned -- the client greeting, "Client:" surname, and
    "Project:" address all live in the letterhead/opening of the quote's
    first page in every sample seen so far.

      client -> the first name(s) from "Dear <names>," combined with the
                surname from the "Client:" field, e.g. "Dear Caitlin &
                Chris," + "Client: Morey" -> "Caitlin & Chris Morey".
      site   -> the address in the "Project:" field. That field commonly
                wraps across two lines (e.g. "Lot 4, Buninyong-Mt Mercer
                Road," / "Durham Lead VIC 3352") with a page number and
                blank lines after it before the page footer -- captured
                up to the footer's "W www.logikhaus..." line (present on
                every page), then blank/page-number lines are dropped and
                the remaining lines joined into one string.
      date   -> always today's date (not read from the quote at all),
                formatted to match the certificate's existing date style,
                e.g. "08 Sep 2026".

    Any piece that can't be found is simply omitted from the returned
    dict rather than guessed, consistent with fill_certificate() only
    writing whatever keys it's actually given.
    """
    text = doc[0].get_text()
    data = {}

    surname_match = re.search(r'Client:\s*(.+?)\s*\n', text)
    dear_match     = re.search(r'Dear\s+([^,]+),', text)
    if surname_match and dear_match:
        data['client'] = f"{dear_match.group(1).strip()} {surname_match.group(1).strip()}"

    project_match = re.search(r'Project:\s*(.*?)\nW\s+www\.logikhaus', text, re.DOTALL)
    if project_match:
        lines = [ln.strip() for ln in project_match.group(1).splitlines()]
        lines = [ln for ln in lines if ln and not ln.isdigit()]
        if lines:
            data['site'] = ' '.join(lines)

    data['date'] = datetime.now().strftime('%d %b %Y')

    return data


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
