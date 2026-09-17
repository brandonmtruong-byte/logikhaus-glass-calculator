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
        data['client'] = f"{dear_match.group(1).strip()} {surname_match.group(1).strip()}"

    project_match = re.search(r'Project:\s*(.*?)\nW\s+www\.logikhaus', text, re.DOTALL)
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
    Returns {'price': ...} from a blinds/services quote (a fitz.Document)
    -- the "Amount" column of its (single) line item, ex-GST. That's the
    only piece actually used, since the blinds line's description is a
    fixed string, not built from the quote's content.

    Assumes exactly one line item, matching every sample seen so far --
    if a quote ever has more than one row, only the first is captured.
    """
    text = doc[0].get_text()
    data = {}
    amount_match = re.search(r'\d+\n[^\n$]+\n\$([\d,]+\.\d{2})', text)
    if amount_match:
        data['price'] = amount_match.group(1).replace(',', '')
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
