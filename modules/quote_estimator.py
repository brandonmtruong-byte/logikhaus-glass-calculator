"""
quote_estimator.py -- type/paste the key lines of a Logikhaus position, get a price estimate.

Model reverse-engineered from four Logikhaus quotes (Alphington, Wickins,
Duggan, Ayling). Coefficients are on the v22 price list basis (AUD, ex GST)
and are scaled by a price-list index that is auto-detected from the priced
option lines in the pasted text (e.g. EMERGENCY LOCK 11.67 -> 1.00,
11.51 -> 0.986, 10.50 -> 0.90).

What it prices
    * Rectangular aluclad windows (fixed, tilt & turn, concealed hinges)
    * Hinged doors (inswing, outswing DX, French pairs)
What it does NOT price (it says so rather than guessing)
    * Lift & slide, solid IV68/IV92 doors, LUMIS, ALU STAR
    * Arch / angled / curved shapes (the listed ANGLE/ARCH EXTRA lines are
      added as quoted, but the base is only a bounding-rectangle estimate)

Public API
    parse_position(text)                  -> dict   (pure)
    estimate_position(parsed, ...)        -> dict   (pure)
    render_quote_estimator(w, h, eyebrow) -> None   (Streamlit UI)
"""

import re
import statistics

import streamlit as st

# ---------------------------------------------------------------------------
# Fitted coefficients (v22 basis):  price = c + a * area_m2 + p * perimeter_m
# ---------------------------------------------------------------------------
WINDOW_FIXED = {"c": 343.5, "a": 232.3, "p": 147.9}    # mean err 2.7%, max 6%
WINDOW_OPENER = {"c": 131.1, "a": 626.7, "p": 164.5}   # mean err 5.4%, max 19%
CONCEALED_PREMIUM = 185.2
GLASS_6_6_PER_M2 = 90.0           # rough
SYSTEM_88_MULT = 1.20             # rough (very few points)

DOOR_HINGED = {"c": 83.9, "a": 1761.3}                 # 7 points, within ~7%
DOOR_OUTWARD_MULT = 1.25                               # 2 single doors, 1.29-1.34
DOOR_FRENCH_MULT = 1.15                                # ONE French pair (outward) at 1.14

BAND = {"win_fixed": 0.06, "win_opener": 0.10, "door_in": 0.08, "door_out": 0.12}
FIT_AREA = {"window": (0.6, 7.0), "door": (1.9, 4.3)}

# Observed lift & slide prices, v22 basis (not modelled)
LS_NOTE = ("Lift & slide isn't modelled. In your quotes, 3.0-3.5 m wide LS units "
           "came to roughly $13,000-$14,200 each (list, before options).")

# v22 reference rates for auto-detecting the price list index.
# Longest keys are matched first so "STEEL HINGES 4TH" beats "STEEL HINGES".
REF_RATES = {
    "EMERGENCY LOCK": 11.67, "KEYED ALIKE": 43.75, "WINKHAUS AV4D": 189.58,
    "STEEL HINGES 4TH": 116.67, "STEEL HINGES": 350.00, "AUSTIN WINDOW F9": 29.17,
    "FLYSCREEN ALU": 131.94, "ADJUSTABLE WHEELS": 72.92, "KIT FORM": 729.17,
    "TOULON KEY F9": 131.25, "STAY ARM": 33.68, "TURN BLOCKED": 23.33,
    "TF POWERHINGE": 94.79, "HANDLE BRAKE PH": 77.29, "WELDED": 24.31,
    "TALL DOORS": 416.67, "AMSTERDAM": 67.08,
}
_REF_KEYS = sorted(REF_RATES, key=len, reverse=True)

_NUM = r"\d[\d,]*(?:\.\d+)?"


def _f(s):
    return float(s.replace(",", ""))


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------
def _parse_options(text):
    """Priced option lines like '3. WINKHAUS AV4D: - auto espag  1 x 170.63 = 170.63'."""
    head = re.search(r"quantity\s+price\s+value", text, re.I)
    start = head.end() if head else 0
    m_sys = re.search(r"\bSystem\s*:", text[start:], re.I)
    end = start + m_sys.start() if m_sys else len(text)
    region = text[start:end]

    heads = list(re.finditer(r"(?:(?<=\s)|^)(\d{1,2})\.\s+([A-Z/\-][^:\n]{1,60}?):", region))
    options = []
    for i, h in enumerate(heads):
        chunk = region[h.end(): heads[i + 1].start() if i + 1 < len(heads) else len(region)]
        name = h.group(2).strip().lstrip("/-").strip()
        eq = list(re.finditer(rf"({_NUM})\s*=\s*({_NUM})", chunk))
        if eq:
            rate, value = _f(eq[-1].group(1)), _f(eq[-1].group(2))
        else:
            nums = re.findall(r"\d[\d,]*\.\d{2}\b", chunk)
            if not nums:
                continue
            rate, value = None, _f(nums[-1])
        options.append({"name": name, "rate": rate, "value": value})
    return options


def _detect_index(options):
    ratios = []
    for o in options:
        if o["rate"] is None:
            continue
        up = o["name"].upper()
        for k in _REF_KEYS:
            if up.startswith(k):
                ratios.append(o["rate"] / REF_RATES[k])
                break
    ratios = [r for r in ratios if 0.7 < r < 1.3]
    if not ratios:
        return None
    return round(statistics.median(ratios), 4)


def parse_position(text):
    """Pull the fields that matter out of one pasted position block."""
    t = text.replace("\u00d7", "x")
    out = {"ok": False, "warnings": []}

    m = re.search(r"Pos\.?\s*no\.?\s*\d+\s*:\s*([^\n]+)", t, re.I)
    out["name"] = m.group(1).strip() if m else "?"

    m = re.search(r"size\s*\(\s*W\s*x\s*H\s*\)\s*:\s*(\d+)\s*x\s*(\d+)", t, re.I)
    if not m:
        m = re.search(r"\b(\d{3,4})\s*x\s*(\d{3,4})\b", t)
    if not m:
        out["error"] = "Couldn't find the size - include the 'size (W x H): ...' line."
        return out
    out["w"], out["h"] = int(m.group(1)), int(m.group(2))

    # Quoted base price line (first 'qty x price = value' after the header)
    hdr = re.search(r"quantity\s+price\s+value", t, re.I)
    seg = t[hdr.end():] if hdr else t
    m = re.search(rf"(\d+)\s*x\s*({_NUM})\s*=\s*({_NUM})", seg)
    out["qty"], out["quoted_unit"] = 1, None
    if m and hdr:
        out["qty"] = int(m.group(1))
        out["quoted_unit"] = _f(m.group(2))

    out["options"] = _parse_options(t)
    out["index"] = _detect_index(out["options"])

    sysm = re.search(r"System\s*:\s*([^\n]+)", t, re.I)
    out["system"] = sysm.group(1).strip() if sysm else ""
    glm = re.search(r"Glass\s*:\s*([^\n]+)", t, re.I)
    out["glass"] = glm.group(1).strip() if glm else ""

    up = t.upper()
    name_up = out["name"].upper()
    is_door = bool(re.match(r"\s*D", name_up)) or "ENTRANCE DOOR" in up
    out["is_door"] = is_door

    out["is_ls"] = bool(re.search(r"\bLS\b|LIFT\s*(AND|&)?\s*SLIDE|WHEELS\s*:|LOCKBOLTS", up))
    out["unsupported"] = None
    if re.search(r"\bIV\s?\d{2}\b", out["system"].upper()):
        out["unsupported"] = "Solid IV68/IV92 doors aren't modelled (one data point each)."
    elif "LUMIS" in out["system"].upper() or "ALU STAR" in out["system"].upper():
        out["unsupported"] = "LUMIS / ALU STAR systems aren't modelled."
    elif out["is_ls"] and is_door:
        out["unsupported"] = LS_NOTE

    out["triple"] = bool(re.search(r"\d/\d/\d", out["glass"])) or bool(re.search(r"\b88\b", out["system"]))
    out["glass_6"] = bool(re.search(r"\b6/6\b|\b8/8\b", out["glass"])) and not out["triple"]
    out["outward"] = bool(re.search(r"R\s*DX|OUTWARD|OUTSWING", up))
    out["french"] = bool(re.search(r"FRENCH|\bR2\b", up)) and is_door

    tilt_turn = bool(re.search(r"\bUR[12]|AX_RU|T&T|MIK\+", up))
    tilt_only = bool(re.search(r"AX_U\b|TILTCONC|TILT-ONLY", up))
    out["tilt_turn"], out["tilt_only"] = tilt_turn, tilt_only
    out["opener"] = (not is_door) and (tilt_turn or tilt_only or bool(re.search(r"\bSash\s*:", t)))
    out["concealed"] = bool(re.search(r"AX_|CONC", up))

    if re.search(r"ANGLE EXTRA|ARCH EXTRA|CURVE", up):
        out["warnings"].append(
            "Angled / arched / curved: the base is only a bounding-rectangle estimate. "
            "The ANGLE/ARCH EXTRA line from the paste is added as quoted.")
    if out["triple"] and not is_door:
        out["warnings"].append("88 / triple glazing uplift rests on 3 data points - treat as +/-20%.")
    if out["french"]:
        out["warnings"].append("French pair uplift is based on a single quote - low confidence.")
    if re.search(r"JOINED ONSITE", up):
        out["warnings"].append("Multi-unit assembly - the model treats it as one window, so expect more error.")
    if re.search(r"\+\s*\d+\s*%", out["glass"]):
        out["warnings"].append("Glass surcharge (e.g. +30%) isn't modelled.")
    if re.search(r"\bORN\b|ORNAMENTAL|FLUTED", up):
        out["warnings"].append("Ornamental glass on small windows ran well above the model - treat as low.")
    out["ok"] = True
    return out


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------
def estimate_position(p, index=None, discount_pct=None):
    """Return an estimate dict for a parsed position (see parse_position)."""
    w, h = p["w"], p["h"]
    area = w * h / 1e6
    perim = 2 * (w + h) / 1000
    idx = index if index else (p["index"] or 1.0)
    if discount_pct is None:
        discount_pct = 10.0 if idx > 0.95 else 0.0

    opt_total = sum(o["value"] for o in p["options"])
    r = {"area": area, "index": idx, "discount_pct": discount_pct,
         "options_total": opt_total, "base_unit": None, "lines": []}
    if p["unsupported"]:
        r["note"] = p["unsupported"]
        return r

    kind = "door" if p["is_door"] else "window"
    lo, hi = FIT_AREA[kind]
    r["in_range"] = lo <= area <= hi
    r["fit_range"] = (lo, hi)

    if p["is_door"]:
        base = DOOR_HINGED["c"] + DOOR_HINGED["a"] * area
        r["lines"].append(("Hinged door base (size)", base))
        if p["outward"]:
            m = DOOR_FRENCH_MULT if p["french"] else DOOR_OUTWARD_MULT
            lbl = "Outward French pair" if p["french"] else "Outward / DX"
            r["lines"].append((f"{lbl} uplift x{m}", base * (m - 1)))
        band = BAND["door_out"] if p["outward"] else BAND["door_in"]
    else:
        coef = WINDOW_OPENER if p["opener"] else WINDOW_FIXED
        base = coef["c"] + coef["a"] * area + coef["p"] * perim
        r["lines"].append(("Window base (size" + (", opening sash)" if p["opener"] else ", fixed)"), base))
        if p["opener"] and p["concealed"]:
            r["lines"].append(("Concealed hinges", CONCEALED_PREMIUM))
        if p["glass_6"]:
            r["lines"].append(("6/6 glass upgrade", GLASS_6_6_PER_M2 * area))
        if p["triple"]:
            sub = sum(a for _, a in r["lines"])
            r["lines"].append((f"88 / triple uplift x{SYSTEM_88_MULT}", sub * (SYSTEM_88_MULT - 1)))
        band = BAND["win_opener"] if p["opener"] else BAND["win_fixed"]

    if p["triple"] and not p["is_door"]:
        band = max(band, 0.20)
    unit = sum(a for _, a in r["lines"]) * idx
    r["lines"] = [(l, a * idx) for l, a in r["lines"]]
    r["base_unit"] = unit
    r["base_total"] = unit * p["qty"]
    r["low"] = r["base_total"] * (1 - band)
    r["high"] = r["base_total"] * (1 + band)
    # Options / extras are NOT discounted on these quotes; the base is.
    d = 1 - discount_pct / 100
    r["net_base"] = r["base_total"] * d
    r["net_low"], r["net_high"] = r["low"] * d, r["high"] * d
    r["line_total"] = r["net_base"] + opt_total
    r["line_low"], r["line_high"] = r["net_low"] + opt_total, r["net_high"] + opt_total
    if p["quoted_unit"]:
        q = p["quoted_unit"] * p["qty"]
        r["quoted_base"] = q
        r["vs_quoted_pct"] = (r["base_total"] - q) / q * 100
    return r


# ---------------------------------------------------------------------------
# Streamlit UI
# ---------------------------------------------------------------------------
def _money(x):
    return f"${x:,.0f}"


def _apply_to_diagram(w, h, swing, tilt):
    """Button callback: push the pasted size/opening into the diagram widgets."""
    st.session_state["window_diagram_width"] = int(w)
    st.session_state["window_diagram_height"] = int(h)
    st.session_state["window_diagram_swing"] = bool(swing)
    st.session_state["window_diagram_tilt"] = bool(swing and tilt)


def _strip_label(txt, *labels):
    """Allow people to paste 'System: Aluclad ...' as well as just the value."""
    txt = (txt or "").strip()
    return re.sub(rf"^\s*(?:{'|'.join(labels)})\s*[:=]\s*", "", txt, flags=re.I)


def _compose_block(name, size, qty, system, glass, fitting, notes, options, quoted):
    """Rebuild a quote-style block from the separate boxes so one parser serves all."""
    m = re.search(r"(\d{3,5})\D+?(\d{3,5})", size or "")
    if not m:
        return None
    w, h = m.group(1), m.group(2)
    try:
        q = float((quoted or "").replace("$", "").replace(",", "").strip() or 0)
    except ValueError:
        q = 0.0
    lines = [
        f"Pos.no 1: {name.strip() or 'W'}",
        f"size (W x H): {w} x {h}",
        "quantity price value",
        f"{int(qty)} x {q:.2f} = {q * int(qty):.2f}",
        (options or "").strip(),
        f"System: {_strip_label(system, 'System')}",
        f"Glass: {_strip_label(glass, 'Glass')}",
    ]
    fit = _strip_label(fitting, "Fitting")
    if fit and not re.search(r"\bfixed\b", fit, re.I):
        lines += ["Sash: 68x80mm", f"Fitting: {fit}"]   # a fitting means it opens
    lines.append(notes or "")
    return "\n".join(lines)


def render_quote_estimator(width_mm=None, height_mm=None, eyebrow=None):
    """Estimator driven by a few separate text boxes. width/height args are
    unused (kept so the app.py call doesn't change)."""
    (eyebrow or st.subheader)("Price estimate")
    st.caption("Fill in the lines from the quote. Only size is required; the more you "
               "give it, the better the estimate. Pasting 'System: ...' with its label is fine.")

    c1, c2, c3 = st.columns([1, 1.2, 0.6])
    name = c1.text_input("Position name", key="qe_name", placeholder="W01 or D02",
                         help="Starts with D = door, otherwise window. Leave blank for a window.")
    size = c2.text_input("Size (W x H, mm)", key="qe_size", placeholder="1100 x 2048")
    qty = c3.number_input("Qty", min_value=1, value=1, step=1, key="qe_qty")

    c4, c5 = st.columns(2)
    system = c4.text_input("System", key="qe_system",
                           placeholder="Aluclad Timber 68 PEFC Select Pine")
    glass = c5.text_input("Glass", key="qe_glass", placeholder="LHG001_4/4 (26)")

    c6, c7 = st.columns(2)
    fitting = c6.text_input("Fitting / drawing code", key="qe_fitting",
                            placeholder="blank = fixed. e.g. UR1STD, AX_RU1, TILTconc, R DX",
                            help="Any fitting means the window opens. AX_ / conc = concealed hinges.")
    notes = c7.text_input("Notes", key="qe_notes",
                          placeholder="e.g. Outward opening entrance door; 3 units joined onsite")

    c8, c9 = st.columns([2.2, 1])
    options = c8.text_area("Priced options (optional)", key="qe_options", height=110,
                           placeholder="1. WINKHAUS AV4D: - auto espag\n1 x 189.58 = 189.58\n"
                                       "2. KEYED ALIKE: ...\n1 x 43.75 = 43.75",
                           help="Paste the numbered option lines as they appear on the quote. "
                                "They're added as quoted and also reveal the price list.")
    quoted = c9.text_input("Quoted base price (optional)", key="qe_quoted", placeholder="7728.31",
                           help="Only used to show how close the estimate is.")

    block = _compose_block(name, size, qty, system, glass, fitting, notes, options, quoted)
    if block is None:
        st.info("Enter a size such as 1100 x 2048 to get an estimate.")
        return
    p = parse_position(block)
    if not p["ok"]:
        st.error(p["error"])
        return

    with st.expander("Advanced: price list index / discount"):
        detected = p["index"]
        st.caption(
            f"Detected price list index: {detected if detected else 'none (add priced options to detect it)'}. "
            "1.00 = v22, 0.986 = v23.1 (Duggan), 0.90 = Ayling-style.")
        idx = st.number_input("Price list index", min_value=0.5, max_value=1.5,
                              value=float(detected or 1.0), step=0.001, format="%.4f")
        disc = st.number_input("Discount on base (%) - options aren't discounted",
                               min_value=0.0, max_value=50.0,
                               value=10.0 if idx > 0.95 else 0.0, step=1.0)

    r = estimate_position(p, index=idx, discount_pct=disc)

    kind = "Door" if p["is_door"] else ("Window - opening" if p["opener"] else "Window - fixed")
    st.markdown(
        f"**Reading this as:** {p['w']} x {p['h']} mm ({r['area']:.2f} m2) "
        f"&nbsp;|&nbsp; {kind}" + (f" &nbsp;|&nbsp; x{p['qty']}" if p["qty"] > 1 else ""),
        unsafe_allow_html=True)

    if "note" in r:
        st.warning(r["note"])
        if r["options_total"]:
            st.caption(f"Priced options/extras entered total {_money(r['options_total'])}.")
        return

    m1, m2, m3 = st.columns(3)
    m1.metric("Base estimate (list)", _money(r["base_total"]),
              help=f"Likely range {_money(r['low'])} - {_money(r['high'])}")
    m2.metric("Options & extras (as quoted)", _money(r["options_total"]))
    m3.metric("Estimated line total", _money(r["line_total"]),
              help=(f"Likely range {_money(r['line_low'])} - {_money(r['line_high'])}. "
                    f"Includes {disc:.0f}% discount on the base only.") if disc else
                   f"Likely range {_money(r['line_low'])} - {_money(r['line_high'])}.")
    st.caption(f"Base likely range {_money(r['low'])} - {_money(r['high'])} (list, before discount). Ex GST.")
    if "quoted_base" in r:
        st.info(f"The quote lists the base at {_money(r['quoted_base'])}; "
                f"this model gives {_money(r['base_total'])} ({r['vs_quoted_pct']:+.1f}%).")
    if not r["in_range"]:
        lo, hi = r["fit_range"]
        st.warning(f"{r['area']:.2f} m2 is outside the {lo}-{hi} m2 range this model was fitted on.")
    for w_ in p["warnings"]:
        st.warning(w_)

    st.button("Show this size in the diagram", key="qe_apply",
              on_click=_apply_to_diagram,
              args=(p["w"], p["h"], p["opener"] or p["is_door"], p["tilt_turn"]))

    with st.expander("What was detected / breakdown"):
        st.write({
            "system": p["system"], "glass": p["glass"],
            "type": kind, "tilt & turn": p["tilt_turn"], "concealed hinges": p["concealed"],
            "outward (DX)": p["outward"], "triple / 88": p["triple"], "6/6 glass": p["glass_6"],
            "price index": r["index"],
        })
        st.table({"Base component": [l for l, _ in r["lines"]],
                  "Each ($, list)": [f"{a:,.2f}" for _, a in r["lines"]]})
        if p["options"]:
            st.table({"Option (as entered)": [o["name"] for o in p["options"]],
                      "Value ($)": [f"{o['value']:,.2f}" for o in p["options"]]})
        st.caption("Estimate only - not a Logikhaus quote. Rectangular windows and hinged doors only.")
