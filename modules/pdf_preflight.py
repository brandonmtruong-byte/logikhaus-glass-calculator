"""
PDF PREFLIGHT (CLEAN-UP) -- step 1 of the stepper
Finds and neutralises "0 0 TD" / "0 0 Td" text moves before the PDF is
edited, either by the later steps here or in Acrobat (or similar).

Why: some PDF converters write "0 0 TD" to snap the text cursor back to the
start of the line (e.g. after drawing a leading space). PDF editors that
rewrite the page often treat it as a no-op and delete it, which shifts the
rest of the line right and makes letters overlap.

Each one is replaced with an explicit, absolute "Tm" (same position, same
result on screen), which editors keep intact.

Used two ways:
  - In the app: preflight_pdf_bytes() -- see steps.apply_preflight().
  - From the command line, as before:
        python -m modules.pdf_preflight input.pdf          -> report + writes input_preflight.pdf
        python -m modules.pdf_preflight input.pdf --check  -> report only

Needs the pikepdf package (add "pikepdf" to requirements.txt).
"""
import io
import sys

import pikepdf
from pikepdf import Operator


def mul(a, b):
    # 2D affine matrices as [a b c d e f]; returns a x b
    return [
        a[0] * b[0] + a[1] * b[2],
        a[0] * b[1] + a[1] * b[3],
        a[2] * b[0] + a[3] * b[2],
        a[2] * b[1] + a[3] * b[3],
        a[4] * b[0] + a[5] * b[2] + b[4],
        a[4] * b[1] + a[5] * b[3] + b[5],
    ]


def process_stream(instructions):
    """
    Rewrite one page's content-stream instructions, replacing every
    "0 0 Td" / "0 0 TD" with an absolute "Tm" at the same position.
    Returns (new_instructions, number_replaced).

    Inline images and anything else that isn't a plain operator are
    passed through untouched.
    """
    out, hits = [], 0
    tlm = [1, 0, 0, 1, 0, 0]
    leading = 0.0

    def move(tx, ty):
        nonlocal tlm
        tlm = mul([1, 0, 0, 1, tx, ty], tlm)

    for instruction in instructions:
        operands, op = instruction.operands, instruction.operator
        name = str(op)
        if name == "BT":
            tlm = [1, 0, 0, 1, 0, 0]
        elif name == "Tm":
            tlm = [float(x) for x in operands]
        elif name == "TL":
            leading = float(operands[0])
        elif name in ("Td", "TD"):
            tx, ty = float(operands[0]), float(operands[1])
            if tx == 0 and ty == 0:
                hits += 1
                out.append((list(tlm), Operator("Tm")))  # same effect, absolute
                if name == "TD":
                    out.append(([0], Operator("TL")))  # TD also sets leading = -ty
                    leading = 0.0
                continue
            if name == "TD":
                leading = -ty
            move(tx, ty)
        elif name in ("T*", "'", '"'):
            move(0, -leading)
        out.append(instruction)
    return out, hits


def _fix_pages(pdf):
    """
    Fix every page of an open pikepdf.Pdf in place.
    Returns {page_number (1-based): number_replaced} for pages that had any.
    """
    fixed = {}
    for i, page in enumerate(pdf.pages, 1):
        new, hits = process_stream(pikepdf.parse_content_stream(page))
        if hits:
            fixed[i] = hits
            page.Contents = pdf.make_stream(pikepdf.unparse_content_stream(new))
    return fixed


def preflight_pdf_bytes(pdf_bytes):
    """
    Clean a whole PDF given as bytes.
    Returns (cleaned_bytes, {page_number: number_replaced}). If nothing
    needed fixing, the ORIGINAL bytes come back unchanged, so a clean file
    is never re-saved for no reason.
    """
    with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
        fixed = _fix_pages(pdf)
        if not fixed:
            return pdf_bytes, {}
        out = io.BytesIO()
        pdf.save(out)
        return out.getvalue(), fixed


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    src = sys.argv[1]
    check_only = "--check" in sys.argv
    pdf = pikepdf.open(src)
    if check_only:
        total = 0
        for i, page in enumerate(pdf.pages, 1):
            _, hits = process_stream(pikepdf.parse_content_stream(page))
            if hits:
                total += hits
                print(f"Page {i}: {hits} risky line reset(s)")
        print(f"{total} found. Run without --check to fix." if total
              else "No risky line resets found - safe to edit.")
        return
    fixed = _fix_pages(pdf)
    for page_no, hits in fixed.items():
        print(f"Page {page_no}: {hits} risky line reset(s)")
    if not fixed:
        print("No risky line resets found - safe to edit.")
        return
    dst = src.rsplit(".", 1)[0] + "_preflight.pdf"
    pdf.save(dst)
    print(f"Fixed {sum(fixed.values())}. Edit this file instead: {dst}")


if __name__ == "__main__":
    main()
