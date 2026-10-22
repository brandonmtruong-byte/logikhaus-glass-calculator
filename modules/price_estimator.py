"""
PRICE ESTIMATOR -- estimates a window's list price from the Window Diagram's
own settings (size, panels, panel types, bottom sections, glass), so there
is no separate input: whatever the diagram shows is what gets priced.

Model: fitted to the Logikhaus PRICING-GENERATOR price list (v24.1, AUD,
ex GST, per window, before add-ons like flyscreens, stay arms or locks).
A window is broken into parts and each part has a fitted price:

    one-off cost per window (+ more for door / sliding systems)
  + frame, per metre of outer perimeter
  + mullions and transoms, per metre
  + glass, per m2 (more for 6/6, 8/8 and triple glazing -- the triple
    glazing rate includes the 88 system it comes in)
  + each opening sash: a cost per sash and per metre of its perimeter,
    by type (tilt & turn, tilt only, door, French pair, slider, tilt-slide)

Fitted with non-negative least squares on the 51 price-list positions the
diagram can draw in their standard form. Tested by predicting each of
those positions with a model fitted WITHOUT it: typical error by type is
in TYPICAL_ERROR below (used as the +/- range on the estimate).

Priced as standard (the diagram can't show the difference):
  tilt & turn = concealed hinges; side-hung = inswing door; system =
  whatever the price list uses for that type and glass.
Not in the price data: lift & slide 3-panel types, round windows,
6/4/4, 6/6/6 and 8/8/8 glass, and glass types (ECL, CN, SB, ...) -- the
estimate says so where it applies.

Public API
    estimate(width_mm, height_mm, diagram_options, glass_widths, glass_cavity) -> dict
    render_price_estimate(...)  -> None (Streamlit)
"""

import streamlit as st

PRICE_LIST = "PRICING-GENERATOR v24.1"

# Fitted part prices (AUD, ex GST). "count" = per sash; "perimeter_m" = per
# metre of that sash's perimeter; glass rates are on top of area_m2.
COEFFICIENTS = {
    "window": 309.92,
    "door_or_sliding_system": 932.18,
    "frame_perimeter_m": 121.22,
    "divider_m": 295.94,
    "area_m2": 228.46,
    "glass 6/6 m2": 72.61,
    "glass 8/8 m2": 197.74,
    "glass 4/4/4 (44) m2": 74.09,
    "glass 4/4/4 (48) m2": 186.6,
    "tt count": 365.4,
    "tt perimeter_m": 0.0,
    "tilt count": 297.15,
    "tilt perimeter_m": 34.74,
    "door count": 0.0,
    "door perimeter_m": 154.38,
    "french count": 0.0,
    "french perimeter_m": 322.81,
    "slide count": 1940.27,
    "slide perimeter_m": 494.29,
    "tiltslide count": 0.0,
    "tiltslide perimeter_m": 196.8
}

# Typical error predicting a window the model hadn't seen, by type (%).
TYPICAL_ERROR = {"fixed": 14, "tt": 4, "tilt": 5, "door": 2, "french": 1.5,
                 "slide": 1, "tiltslide": 17}

# Window sizes (m2) each type appears at in the price list -- outside these
# the estimate is an extrapolation and says so.
SIZE_RANGE_M2 = {"fixed": (0.25, 7.2), "tt": (0.36, 8.64), "tilt": (0.3, 5.76),
                 "door": (1.89, 9.1), "french": (3.78, 12.48), "slide": (3.78, 14.56),
                 "tiltslide": (1.28, 6.8)}

# The least +/- to show when the glass is rough (6/6, 8/8) or not in the
# price data at all (6/4/4, 6/6/6, 8/8/8).
GLASS_GUESS_ERROR = 10

TYPE_NAMES = {"fixed": "fixed", "tt": "tilt & turn", "tilt": "tilt only", "door": "door",
              "french": "French doors", "slide": "sliding", "tiltslide": "tilt & slide"}
_SASH_TYPES = ["tt", "tilt", "door", "french", "slide", "tiltslide"]


def _panels_from_diagram(width_mm, diagram_options):
    """
    The diagram's options as [(width_mm, type, top_height_mm or None)], with
    types fixed / tt / tilt / door / french / slide / double_slide /
    tiltslide, plus notes about anything priced as an assumption.
    """
    notes = []
    o = diagram_options
    if o.get("slide"):
        left = o.get("split_left_mm") or width_mm / 2
        tilting = o.get("tilt") or o.get("tilt_only")
        if o.get("tilt") and not o.get("tilt_only"):
            notes.append("Tilt & turn on a sliding panel is priced as tilt & slide.")
        slider = ("tiltslide" if tilting else "slide", None)
        fixed = ("fixed", None)
        widths = [left, width_mm - left]
        kinds = [slider, fixed] if o.get("slide_side", "left") == "left" else [fixed, slider]
        return [(w, k, top) for w, (k, top) in zip(widths, kinds)], notes

    panels = o.get("panels") or [dict(swing=o.get("swing"), tilt=o.get("tilt"),
                                      tilt_only=o.get("tilt_only"))]
    widths = o.get("panel_widths_mm") or [width_mm / len(panels)] * len(panels)
    out = []
    for p, w in zip(panels, widths):
        if p.get("double_slide"):
            kind = "double_slide"
        elif p.get("french"):
            kind = "french"
        elif not p.get("swing"):
            kind = "fixed"
        elif p.get("tilt_only"):
            kind = "tilt"
        elif p.get("tilt"):
            kind = "tt"
        else:
            kind = "door"
            if "Side-hung panels are priced as inswing doors." not in notes:
                notes.append("Side-hung panels are priced as inswing doors.")
        out.append((w, kind, p.get("top_height_mm")))
    if any(k == "tt" for _, k, _ in out):
        notes.append("Tilt & turn is priced with concealed hinges (the price list's standard).")
    return out, notes


def _glass_group(glass_widths, glass_cavity):
    """The glass rate to use, and a note if the glass isn't in the price data."""
    if glass_widths == "4/4":
        return None, None
    if glass_widths in ("6/6", "8/8"):
        return glass_widths, f"{glass_widths} glass is priced from a single fixed window in the price list, so it's rough."
    if glass_widths == "4/4/4":
        return ("4/4/4 (44)" if str(glass_cavity) == "44" else "4/4/4 (48)"), None
    return "4/4/4 (48)", (f"There's no price data for {glass_widths} glass, so it's priced "
                         f"as 4/4/4 (48) triple glazing.")


def estimate(width_mm, height_mm, diagram_options, glass_widths="4/4", glass_cavity=None):
    """
    Estimated list price for the window the diagram shows. Returns a dict:
        price      -- the estimate (AUD, ex GST)
        error_pct  -- typical +/- for this kind of window
        parts      -- [(description, amount)] adding up to the price
        notes      -- assumptions and warnings to show with it
    """
    W, H = float(width_mm), float(height_mm)
    panels, notes = _panels_from_diagram(W, diagram_options)
    glass, glass_note = _glass_group(glass_widths, glass_cavity)
    if glass_note:
        notes.append(glass_note)
    c = COEFFICIENTS
    area = W * H / 1e6
    kinds = {k for _, k, _ in panels}
    heavy = bool(kinds & {"door", "french", "slide", "double_slide", "tiltslide"})

    parts = [("Window (one-off)", c["window"])]
    if heavy:
        parts.append(("Door / sliding system", c["door_or_sliding_system"]))
    parts.append((f"Frame ({2 * (W + H) / 1000:.1f} m)", c["frame_perimeter_m"] * 2 * (W + H) / 1000))
    divider_m = (len(panels) - 1) * H / 1000 + sum(w for w, _, top in panels if top) / 1000
    if divider_m:
        parts.append((f"Mullions / transoms ({divider_m:.1f} m)", c["divider_m"] * divider_m))
    parts.append((f"Glass ({area:.2f} m2)", c["area_m2"] * area
                   + (c[f"glass {glass} m2"] * area if glass else 0)))

    sash_totals = {}
    for w, kind, top in panels:
        h = top or H
        sashes = [(w / 2, h), (w / 2, h)] if kind == "double_slide" else [(w, h)]
        kind = "slide" if kind == "double_slide" else kind
        if kind == "fixed":
            continue
        for sw, sh in sashes:
            amount = c[f"{kind} count"] + c[f"{kind} perimeter_m"] * 2 * (sw + sh) / 1000
            n, total = sash_totals.get(kind, (0, 0.0))
            sash_totals[kind] = (n + 1, total + amount)
    for kind, (n, total) in sash_totals.items():
        parts.append((f"{TYPE_NAMES[kind].capitalize()} sash{'es' if n > 1 else ''} ({n})", total))

    price = sum(a for _, a in parts)

    # The +/- range: the least accurate type in this window (fixed if no sashes).
    main_types = set(sash_totals) or {"fixed"}
    error_pct = max(TYPICAL_ERROR[k] for k in main_types)
    if glass_note:
        # The glass itself is rough or guessed, so don't claim the type's
        # usual accuracy.
        error_pct = max(error_pct, GLASS_GUESS_ERROR)
    for k in main_types:
        lo, hi = SIZE_RANGE_M2[k]
        if not lo <= area <= hi:
            notes.append(f"At {area:.1f} m2 this is outside the {TYPE_NAMES[k]} sizes in the price "
                         f"list ({lo:g}-{hi:g} m2), so the estimate is less reliable.")
    return dict(price=price, error_pct=error_pct, parts=parts, notes=notes)


def render_price_estimate(width_mm, height_mm, diagram_options, glass_widths, glass_cavity,
                          glass_type=None, eyebrow=None):
    """Streamlit: the estimate for the diagram's current window."""
    if eyebrow:
        eyebrow("Price estimate")
    result = estimate(width_mm, height_mm, diagram_options, glass_widths, glass_cavity)
    price, err = result["price"], result["error_pct"]
    st.markdown(f"### ${price:,.0f}")
    st.caption(f"Estimated list price, AUD ex GST, before add-ons (flyscreens, stay arms, locks...). "
               f"Typically within about ±{err:g}% for this kind of window "
               f"(${price * (1 - err / 100):,.0f}-${price * (1 + err / 100):,.0f}). "
               f"Based on {PRICE_LIST}.")
    notes = list(result["notes"])
    if glass_type:
        notes.append(f"Glass type {glass_type} isn't priced separately.")
    for note in notes:
        st.caption(f"ⓘ {note}")
    with st.expander("How it's worked out"):
        st.dataframe([{"Part": p, "Amount": f"${a:,.0f}"} for p, a in result["parts"]],
                     hide_index=True)
