"""
quote_estimator.py -- rough window price estimator for the Quote Estimator tab.

Model reverse-engineered from four Logikhaus quotes (Alphington, Wickins,
Duggan, Ayling). All coefficients are on the v22 price list basis (AUD, ex GST)
and are scaled by the price-list index chosen in the UI.

Fitted on rectangular aluclad 68 windows only. The 88 / triple glazing and
6/6 glass adjustments are rougher (very few data points) -- see CAUTION flags.
Doors, lift & slide, arches, angled/curved units are NOT modelled.

Public API:
    estimate_window(...)        -> dict   (pure function, no Streamlit)
    render_quote_estimator(w,h) -> None   (draws the estimator UI)
"""

import streamlit as st

# ---------------------------------------------------------------------------
# Fitted coefficients  (v22 basis)
# price = c + a * area_m2 + p * perimeter_m
# ---------------------------------------------------------------------------
BASE_FIXED = {"c": 343.5, "a": 232.3, "p": 147.9}      # mean err 2.7%, max 6%
BASE_OPENER = {"c": 131.1, "a": 626.7, "p": 164.5}     # mean err 5.4%, max 19%
CONCEALED_HINGE_PREMIUM = 185.2

# Uncertainty band shown around the estimate
BAND_FIXED = 0.06
BAND_OPENER = 0.10

# Area range the model was fitted on (m2) -- warn outside it
FIT_AREA_MIN, FIT_AREA_MAX = 0.6, 7.0

# ---------------------------------------------------------------------------
# Curated dropdown options
# ---------------------------------------------------------------------------
# label -> (multiplier, forces triple glass?)
SYSTEMS = {
    "Aluclad Timber 68 - Select": (1.00, False),
    "Aluclad Timber 68 - Jointed": (1.00, False),
    "Aluclad Timber 68 SLIM - Jointed": (1.00, False),
    "Aluclad Timber 88 - triple glazed (rough)": (1.20, True),
}

# label -> extra $ per m2 of window area (v22 basis)
GLASS = {
    "Double 4/4 (26)": 0.0,
    "Double 4/4 combi-neutral CN61/32": 0.0,
    "Double 6/6 (32)": 90.0,
}

# label -> (price-list index, discount already applied?, default discount %)
PRICE_LISTS = {
    "v22 list (Alphington / Wickins) - 10% discount": (1.0000, 10.0),
    "v23.1 list (Duggan) - 10% discount": (0.9863, 10.0),
    "v23.1 list (Ayling) - discount already included": (0.9000, 0.0),
}

TYPES = {
    "Fixed (no opening sash)": ("fixed", False),
    "Tilt & turn - standard hinges": ("opener", False),
    "Tilt & turn - concealed hinges (Siegenia)": ("opener", True),
}

# label -> price each (v22 basis)
HANDLES = {
    "No handle": 0.0,
    "Hoppe Austin F9": 29.17,
    "Hoppe Amsterdam matt black": 67.08,
    "Hoppe Toulon keyed F9 (child safe)": 131.25,
}

OPENER_EXTRAS = {
    "Handle brake (Powerhinge)": 77.29,
    "Friction brake (concealed)": 87.50,
    "Stay arm / turn limiter": 33.68,
    "Tilt-first Powerhinge": 94.79,
    "Tilt first, turn blocked": 23.33,
}

FLYSCREEN_PER_M2 = 131.94
HST_PER_M2 = 35.00
ALU_SILL_PER_M = 41.04   # Duggan's $40.48 on v22 basis


# ---------------------------------------------------------------------------
# Pure pricing function
# ---------------------------------------------------------------------------
def estimate_window(
    width_mm, height_mm, *, qty=1,
    system, glass, win_type, price_list,
    handle="No handle", extras=(), flyscreen=False, sash_width_mm=None,
    hst_glass=False, alu_sill=False,
):
    """Return {'lines': [(label, amount)], 'unit', 'total', 'low', 'high', ...}.

    All amounts are AFTER applying the price-list index but BEFORE discount,
    except 'net_total' which is after the price list's discount.
    """
    index, discount_pct = PRICE_LISTS[price_list]
    kind, concealed = TYPES[win_type]
    sys_mult, triple = SYSTEMS[system]

    area = width_mm * height_mm / 1e6
    perim = 2 * (width_mm + height_mm) / 1000

    coef = BASE_FIXED if kind == "fixed" else BASE_OPENER
    base = coef["c"] + coef["a"] * area + coef["p"] * perim

    lines = [("Frame, sash & glass (base)", base)]

    if concealed:
        lines.append(("Concealed hinges", CONCEALED_HINGE_PREMIUM))
    if not triple and GLASS[glass]:
        lines.append((f"Glass upgrade: {glass}", GLASS[glass] * area))
    if sys_mult != 1.0:
        sub = sum(a for _, a in lines)
        lines.append((f"System uplift x{sys_mult:.2f}", sub * (sys_mult - 1)))

    # ---- add-ons: fixed price-list items --------------------------------
    if kind == "opener":
        if HANDLES[handle]:
            lines.append((handle, HANDLES[handle]))
        for e in extras:
            lines.append((e, OPENER_EXTRAS[e]))
        if flyscreen:
            sw = sash_width_mm or width_mm
            fa = sw * height_mm / 1e6
            lines.append((f"Flyscreen ({fa:.2f} m2)", fa * FLYSCREEN_PER_M2))
    if hst_glass:
        ga = max(width_mm - 218, 0) * max(height_mm - 218, 0) / 1e6
        lines.append((f"HST glass ({ga:.2f} m2)", ga * HST_PER_M2))
    if alu_sill:
        lines.append((f"Alu sill 90 ({width_mm/1000:.2f} m)", width_mm / 1000 * ALU_SILL_PER_M))

    # ---- scale to chosen price list; add-ons are already v22 so scale all
    lines = [(lbl, amt * index) for lbl, amt in lines]
    unit = sum(a for _, a in lines)
    total = unit * qty

    # Uncertainty applies to the fitted base only, not fixed-price add-ons
    band = BAND_FIXED if kind == "fixed" else BAND_OPENER
    base_scaled = lines[0][1] * qty
    low = total - base_scaled * band
    high = total + base_scaled * band

    net_total = total * (1 - discount_pct / 100)
    return {
        "lines": lines, "unit": unit, "total": total,
        "low": low, "high": high,
        "discount_pct": discount_pct, "net_total": net_total,
        "net_low": low * (1 - discount_pct / 100),
        "net_high": high * (1 - discount_pct / 100),
        "area": area, "perimeter": perim, "kind": kind,
        "in_fit_range": FIT_AREA_MIN <= area <= FIT_AREA_MAX,
        "triple": triple,
    }


# ---------------------------------------------------------------------------
# Streamlit UI
# ---------------------------------------------------------------------------
def _money(x):
    return f"${x:,.0f}"


def render_quote_estimator(width_mm, height_mm, eyebrow=None):
    """Draw the estimator. Width/height come from the dimension inputs above
    it, so the diagram and the estimate always describe the same window."""
    def head(text):
        if eyebrow:
            eyebrow(text)
        else:
            st.subheader(text)

    head("Price estimate")

    c1, c2 = st.columns(2)
    with c1:
        system = st.selectbox("System", list(SYSTEMS), key="qe_system")
        win_type = st.selectbox("Window type", list(TYPES), key="qe_type")
    with c2:
        _, triple = SYSTEMS[system]
        glass = st.selectbox(
            "Glass", list(GLASS), key="qe_glass", disabled=triple,
            help="88 system is priced as triple glazed." if triple else None,
        )
        price_list = st.selectbox("Price list", list(PRICE_LISTS), key="qe_pricelist")

    kind, _ = TYPES[win_type]

    handle, extras, flyscreen, sash_w = "No handle", [], False, None
    if kind == "opener":
        o1, o2 = st.columns(2)
        with o1:
            handle = st.selectbox("Handle", list(HANDLES), index=1, key="qe_handle")
            flyscreen = st.checkbox("Aluminium flyscreen", key="qe_fly")
        with o2:
            extras = st.multiselect("Opener extras", list(OPENER_EXTRAS), key="qe_extras")
            if flyscreen:
                sash_w = st.number_input(
                    "Opening sash width (mm) - for flyscreen size",
                    min_value=100, max_value=int(max(width_mm, 100)),
                    value=int(width_mm), step=10, key="qe_sash_w",
                )

    a1, a2, a3 = st.columns(3)
    with a1:
        hst = st.checkbox("HST glass", key="qe_hst")
    with a2:
        sill = st.checkbox("Aluminium sill 90", key="qe_sill")
    with a3:
        qty = st.number_input("Quantity", min_value=1, value=1, step=1, key="qe_qty")

    r = estimate_window(
        width_mm, height_mm, qty=qty, system=system, glass=glass,
        win_type=win_type, price_list=price_list, handle=handle,
        extras=extras, flyscreen=flyscreen, sash_width_mm=sash_w,
        hst_glass=hst, alu_sill=sill,
    )

    st.markdown("---")
    m1, m2 = st.columns(2)
    m1.metric("Estimate (before discount)", _money(r["total"]),
              help=f"Range {_money(r['low'])} - {_money(r['high'])}")
    if r["discount_pct"]:
        m2.metric(f"After {r['discount_pct']:.0f}% discount", _money(r["net_total"]),
                  help=f"Range {_money(r['net_low'])} - {_money(r['net_high'])}")
    else:
        m2.metric("Net (discount included)", _money(r["net_total"]))
    st.caption(
        f"Likely range {_money(r['low'])} - {_money(r['high'])} before discount "
        f"({width_mm} x {height_mm} mm = {r['area']:.2f} m2). ex GST."
    )

    if not r["in_fit_range"]:
        st.warning(
            f"{r['area']:.2f} m2 is outside the {FIT_AREA_MIN}-{FIT_AREA_MAX} m2 range "
            "this model was fitted on, so treat it as a guess."
        )
    if r["triple"]:
        st.warning("88 / triple glazing uplift is based on very few data points (+/- 15% or more).")

    with st.expander("Breakdown"):
        st.table({
            "Item": [l for l, _ in r["lines"]],
            "Each ($)": [f"{a:,.2f}" for _, a in r["lines"]],
        })
        st.caption(
            "Estimate only - not a Logikhaus quote. Rectangular windows only; "
            "doors, lift & slide, arches and angled/curved units are not modelled."
        )
