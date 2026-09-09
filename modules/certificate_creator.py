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

# ═════════════════════════════════════════════════════════════════════════
# CERTIFICATE 2 -- AGWA Window Compliance Certificate (Housing)
# Same "one quote, generate this too" idea as CERT_FIELD_MAP above, but
# this template also needs two one-hot checkbox groups filled in (Site
# Wind rating N1-N6, Bushfire rating BAL LOW/12.5/19/29/40/FZ) instead of
# just text fields. Field names confirmed by rendering the template with
# every widget's name/rect drawn on top of it and reading them off
# directly -- see fill_window_certificate()'s docstring for specifics.
#
# Two template files exist (DG = double glazing, TG = triple glazing),
# identical in every field except the pre-filled U-Value/SHGC numbers --
# WINDOW_CERT_TEMPLATE_PATHS below picks between them based on which
# glazing type extract_quote_data() finds in the quote.
# ═════════════════════════════════════════════════════════════════════════

WINDOW_CERT_FIELD_MAP = {
    'client':       'Text Field 3.Page 1',
    'site':         'Text Field 4.Page 1',
    'delivered_on': 'Text Field 5.Page 1',
    'date':         'Text Field 17.Page 1',
}

# Wind Loads N Ratings table, N1 (top row) through N6 (bottom row).
# Deliberately excludes the Wind Loads C Ratings checkboxes (a separate
# table entirely, Check Box 68-71) -- fill_window_certificate() never
# touches those, per instruction.
WIND_RATING_CHECKBOX_MAP = {
    'N1': 'Check Box 56.Page 1',
    'N2': 'Check Box 57.Page 1',
    'N3': 'Check Box 58.Page 1',
    'N4': 'Check Box 59.Page 1',
    'N5': 'Check Box 60.Page 1',
    'N6': 'Check Box 61.Page 1',
}

# Bushfire table, top to bottom.
BUSHFIRE_CHECKBOX_MAP = {
    'BAL LOW': 'Check Box 91.Page 1',
    'BAL 12.5': 'Check Box 92.Page 1',
    'BAL 19': 'Check Box 93.Page 1',
    'BAL 29': 'Check Box 94.Page 1',
    'BAL 40': 'Check Box 95.Page 1',
    'BAL FZ': 'Check Box 96.Page 1',
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

    # The rest is used for the Window Compliance certificate (see
    # fill_window_certificate() below), scanned across every page since
    # the Project Summary / product description can land on any page.
    full_text = '\n'.join(page.get_text() for page in doc)

    bushfire_match = re.search(r'Bushfire rating:\s*\n\s*(.+?)\s*\n', full_text)
    if bushfire_match:
        data['bushfire_rating'] = bushfire_match.group(1).strip().upper()

    wind_match = re.search(r'Site Wind rating:\s*\n\s*(N\d+)', full_text)
    if wind_match:
        data['site_wind_rating'] = wind_match.group(1).strip().upper()

    # Glazing type: scoped to just the itemized Options section (between
    # "Options" and the pricing "Sub Total:" line) rather than the whole
    # quote -- keeps this from misfiring on an unrelated mention of
    # "double glazing" elsewhere in the document (e.g. a comparison
    # aside), since only the actual selected product line should decide
    # which certificate template gets used.
    options_match = re.search(r'Options\s*\n(.*?)Sub Total:', full_text, re.DOTALL)
    options_text = options_match.group(1) if options_match else ''

    if re.search(r'triple\s+glazing', options_text, re.IGNORECASE):
        data['glazing_type'] = 'TG'
    elif re.search(r'double\s+glazing', options_text, re.IGNORECASE):
        data['glazing_type'] = 'DG'

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


def pick_window_cert_template_path(dg_path, tg_path, glazing_type):
    """
    Choose which of the two Window Compliance templates to use.
    glazing_type is whatever extract_quote_data() found ('DG' or 'TG'),
    or None if it couldn't tell -- defaults to the DG (double glazing)
    template in that case, since that's the more common/base product.
    """
    return tg_path if glazing_type == 'TG' else dg_path


def fill_window_certificate(template_bytes, data):
    """
    Fill the AGWA Window Compliance Certificate (Housing) template.

    `data` uses WINDOW_CERT_FIELD_MAP's keys for the text fields --
    'client', 'site', 'delivered_on', 'date' -- plus two extra keys for
    the checkbox groups:

        'site_wind_rating' : one of 'N1'..'N6', or None/omitted to leave
                              the whole Wind Loads N group untouched
        'bushfire_rating'   : one of the BUSHFIRE_CHECKBOX_MAP keys
                              ('BAL LOW', 'BAL 12.5', 'BAL 19', 'BAL 29',
                              'BAL 40', 'BAL FZ'), or None/omitted to
                              leave the whole Bushfire group untouched

    When a rating IS given, every OTHER checkbox in that same group is
    explicitly set to 'Off' -- not just left alone -- so the result is
    always a clean one-hot selection regardless of whatever sample data
    the template happened to ship with. Everything else on the
    template (Wind Loads C Ratings/C1-C4, the Non-Exposed/Exposed
    header selectors, glass-standard-year, fall prevention, tested/
    prescriptive) is never included in the write, so it's always left
    exactly as the template already has it.

    Checkbox values use a leading slash ('/Yes', '/Off') -- unlike text
    fields, pypdf's update_page_form_field_values() silently no-ops on
    checkboxes given the plain string form even though that's what
    fitz's own field_value reports back for an already-set checkbox.
    """
    import io

    reader = PdfReader(io.BytesIO(template_bytes))
    writer = PdfWriter()
    writer.append(reader)

    field_values = {
        WINDOW_CERT_FIELD_MAP[key]: value
        for key, value in data.items()
        if key in WINDOW_CERT_FIELD_MAP and value is not None
    }

    wind_choice = data.get('site_wind_rating')
    if wind_choice:
        for rating, field_name in WIND_RATING_CHECKBOX_MAP.items():
            field_values[field_name] = '/Yes' if rating == wind_choice else '/Off'

    bushfire_choice = data.get('bushfire_rating')
    if bushfire_choice:
        for rating, field_name in BUSHFIRE_CHECKBOX_MAP.items():
            field_values[field_name] = '/Yes' if rating == bushfire_choice else '/Off'

    if field_values:
        writer.update_page_form_field_values(writer.pages[0], field_values)

    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()
