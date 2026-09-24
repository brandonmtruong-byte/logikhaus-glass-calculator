"""
XERO INVOICE CREATOR
Fully independent of both the PDF Modifier stepper AND the Certificate
Creator -- takes two quote PDFs (a windows/doors quote and a separate
blinds/services quote for the same job) and builds the plain-text
60%-deposit invoice paragraph described below, ready to paste into Xero.

Two DIFFERENT quote formats are involved, so two separate extraction
functions:

  Windows quote (the multi-page "Dear <names>," letter format, e.g.
  QUOTE_W-*.pdf): pulls client name + site address (same regex approach
  as the Certificate Creator's 'client'/'site' fields) plus the
  Quotation page's "Sub Total:" figure (the EX-GST price -- not "Total
  Price", which includes GST).

  Blinds/services quote (the single-page "Quote" table format, e.g.
  QUOTE_S-*.pdf): pulls just the line item's "Amount" column figure
  (also ex-GST). Nothing else is needed from this one -- the blinds
  line's description text is fixed, not built from extracted data (see
  build_xero_invoice_text() below).

Output format is fixed/hardcoded except for the four bracketed pieces
in the original spec (client name, site address, windows price, blinds
price) -- Account, Tax rate, Qty, and the "Mr Blank" contact line are
always the same literal text regardless of what's in the quotes.
"""

import re

WINDOWS_ACCOUNT  = '202001 Sales - windows'
BLINDS_ACCOUNT   = '203001 Sales - blinds'
TAX_RATE         = 'GST on Income'
DEPOSIT_QTY      = '0.6'


# ── Client name combining ───────────────────────────────────────────────
# Combines the first name(s) from the quote's "Dear <names>," line with
# the surname(s) from its "Client:" field. The same code also lives in
# certificate_creator.py; the two copies are deliberately separate so
# each creator stays fully independent. Change both if you change one.
#
#   Single surname            "Morey"
#       "Caitlin & Chris" + "Morey"         -> "Caitlin & Chris Morey"
#   Double-barrelled surname  "Smith - Jones" (spaces optional)
#       "Caitlin & Chris" + "Smith - Jones" -> "Caitlin & Chris Smith-Jones"
#   Two spouses' surnames     "Smith & Jones" / "Smith and Jones"
#       "Caitlin & Chris" + "Smith & Jones" -> "Caitlin Smith & Chris Jones"
#
# If the number of first names doesn't match the number of surnames, the
# names can't be paired reliably, so the first names are kept as written
# and all the surnames are appended joined by " & " instead.

# "&" or the whole word "and" (case-insensitive). The \b word boundaries
# stop this splitting surnames that merely contain "and" ("Anderson").
_SPOUSE_SEPARATOR = re.compile(r'\s*(?:&|\band\b)\s*', re.IGNORECASE)

# A hyphen (or an en/em dash, in case the quote's font substitutes one)
# with any amount of surrounding whitespace, including none.
_HYPHEN = re.compile(r'\s*[-\u2013\u2014]\s*')


def _split_names(text):
    """Split on "&" / "and" and drop any empty pieces."""
    return [part.strip() for part in _SPOUSE_SEPARATOR.split(text) if part.strip()]


def combine_client_name(first_names, surname_field):
    """
    Combine the "Dear ..." first names with the "Client:" surname field
    using the rules above. Both arguments are the raw regex captures.
    """
    first_names = first_names.strip()
    surnames = [_HYPHEN.sub('-', s) for s in _split_names(surname_field)]

    if not surnames:
        return first_names

    # One surname (plain or double-barrelled): the original behaviour.
    if len(surnames) == 1:
        return f'{first_names} {surnames[0]}'

    # Two or more surnames: pair them with the first names in order.
    firsts = _split_names(first_names)
    if len(firsts) == len(surnames):
        return ' & '.join(f'{first} {last}' for first, last in zip(firsts, surnames))

    # The counts don't match, so don't guess a pairing.
    return f"{first_names} {' & '.join(surnames)}"

def extract_windows_quote_info(doc):
    """
    Returns {'client': ..., 'site': ..., 'price': ...} from a windows/
    doors quote (a fitz.Document). Any piece that can't be found is
    simply omitted, same "don't guess" principle as the Certificate
    Creator's extract_quote_data().
    """
    text = doc[0].get_text()
    data = {}

    surname_match = re.search(r'Client:\s*(.+?)\s*\n', text)
    dear_match     = re.search(r'Dear\s+([^,]+),', text)
    if surname_match and dear_match:
        data['client'] = combine_client_name(dear_match.group(1), surname_match.group(1))

    # Try the footer-anchored boundary first (works when the page footer
    # "W www.logikhaus..." happens to land AFTER Project: in the PDF's
    # text-extraction order). If that finds nothing, fall back to the
    # blank-line boundary instead -- PDF extraction order varies between
    # quotes (sometimes the footer lands BEFORE Project: instead), but
    # the address itself is always written as contiguous lines with no
    # blank line in between, regardless of what surrounds it or in what
    # order, so that's a reliable stopping point either way.
    project_match = re.search(r'Project:\s*(.*?)\nW\s+www\.logikhaus', text, re.DOTALL)
    if not project_match:
        project_match = re.search(r'Project:\s*(.*?)\n\s*\n', text, re.DOTALL)
    if project_match:
        lines = [ln.strip() for ln in project_match.group(1).splitlines()]
        lines = [ln for ln in lines if ln and not ln.isdigit()]
        if lines:
            data['site'] = ' '.join(lines)

    full_text = '\n'.join(page.get_text() for page in doc)
    price_match = re.search(r'Sub Total:\s*\n\$?([\d,]+\.\d{2})', full_text)
    if price_match:
        data['price'] = price_match.group(1).replace(',', '')

    return data


def extract_blinds_quote_info(doc):
    """
    Returns {'price': ...} from a blinds/services quote (a fitz.Document).

    Reads the "Total inc GST" summary figure (always exactly one, right
    before the Acceptance section, regardless of how many line items the
    table has) and divides by 1.1 to back out the ex-GST price, rounded
    to 2dp. Deliberately NOT reading the table's own "Amount" column --
    that approach broke on quotes with more than one row (the regex
    only ever captured the first row), where reading the single final
    total instead always works regardless of row count.
    """
    text = doc[0].get_text()
    data = {}
    total_match = re.search(r'Total inc GST\s*\n\$?([\d,]+\.\d{2})', text)
    if total_match:
        total_inc_gst = float(total_match.group(1).replace(',', ''))
        data['price'] = f'{round(total_inc_gst / 1.1, 2):.2f}'
    return data


def build_xero_invoice_text(windows_info=None, blinds_info=None):
    """
    Build the final paragraph from whichever quote(s) were actually
    provided.

    Pass None for a quote that simply wasn't uploaded at all -- that
    item's whole section is OMITTED from the output, since "this job
    has no blinds" (or no windows) isn't a data-extraction problem, it's
    just not applicable.

    Pass a dict (even an empty/partial one) for a quote that WAS
    uploaded -- any field that couldn't be extracted from it renders as
    a [MISSING: ...] placeholder instead, since that IS a genuine gap on
    a document that does exist, worth flagging rather than silently
    guessing or dropping.

    If only the blinds quote is provided, its section is labelled "With
    first item:" instead of "2nd item:", since it genuinely is the only
    (and therefore first) item in that case.
    """
    lines = ['*' * 21, 'Contact:', 'Mr Blank']

    if windows_info is not None:
        client        = windows_info.get('client') or '[MISSING: client name]'
        site          = windows_info.get('site') or '[MISSING: site address]'
        windows_price = windows_info.get('price') or '[MISSING: windows sub total]'
        lines += [
            '',
            'With first item:',
            f'60% deposit for windows and doors for {client} - {site}',
            '',
            f'Qty {DEPOSIT_QTY}',
            f'Price ${windows_price}',
            f'Account {WINDOWS_ACCOUNT}',
            f'Tax rate {TAX_RATE}',
        ]

    if blinds_info is not None:
        blinds_price = blinds_info.get('price') or '[MISSING: blinds amount]'
        lines += [
            '',
            '2nd item:' if windows_info is not None else 'With first item:',
            '60% deposit for motorised external blinds',
            f'Qty {DEPOSIT_QTY}',
            f'Price ${blinds_price}',
            f'Account {BLINDS_ACCOUNT}',
            f'Tax rate {TAX_RATE}',
        ]

    lines += ['', '*' * 21]
    return '\n'.join(lines)
