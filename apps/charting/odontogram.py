"""Draws the dental chart as SVG (FDI, patient's right on the viewer's left).

Each tooth has a 5-surface crown box (M, O, D, B, L) and a root area, so caries,
fillings, crowns, root canals, implants (with their stage), missing teeth and
planned work are visible at a glance. Pure server-side SVG: prints and works offline.
"""

from django.utils.html import escape
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _

from .models import ToothState
from .rules import DEFAULT, state_label
from .teeth import LOWER, UPPER

S = ToothState.Status
W, GAP, PAD, BOX = 46, 16, 8, 30
UPPER_NUM_Y, UPPER_ROOT = 14, (20, 60)
UPPER_BOX_Y = 62
MID_Y = 104
LOWER_BOX_Y = 114
LOWER_ROOT = (146, 186)
LOWER_NUM_Y = 202
HEIGHT = 210
WIDTH = PAD * 2 + 16 * W + GAP

COLORS = {
    "caries": "#E35D6A",
    "filling": "#3D7FE0",
    "crown": "#B8860B",
    "crown_fill": "#FFF4CC",
    "rct": "#D62839",
    "implant": "#8A8D91",
    "implant_dark": "#5B5E62",
    "loaded": "#D6EAB3",
    "loaded_stroke": "#5C8020",
    "outline": "#6C757D",
    "faint": "#CED4DA",
    "plan": "#0D6EFD",
    "hopeless": "#D62839",
}


def _x(index):
    return PAD + index * W + (GAP if index >= 8 else 0)


def _poly(points, fill, stroke=COLORS["outline"], width=1, extra=""):
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    return f'<polygon points="{pts}" fill="{fill}" stroke="{stroke}" stroke-width="{width}" {extra}/>'


def _surfaces_for(tooth, upper):
    """Which polygon (top/bottom/left/right/center) shows which surface letter."""
    quadrant = tooth // 10
    left_is_mesial = quadrant in (2, 3)  # teeth drawn on the right half have mesial on their left
    return {
        "top": "B" if upper else "L",
        "bottom": "L" if upper else "B",
        "left": "M" if left_is_mesial else "D",
        "right": "D" if left_is_mesial else "M",
        "center": "O",
    }


def _crown_box(x, y, tooth, upper, snap, dashed=False, fill_all=None, stroke=None, stroke_width=1):
    s, inset = BOX, 10
    x0 = x + (W - s) / 2
    x1, y1 = x0 + s, y + s
    ix0, iy0, ix1, iy1 = x0 + inset, y + inset, x1 - inset, y1 - inset
    shapes = {
        "top": [(x0, y), (x1, y), (ix1, iy0), (ix0, iy0)],
        "bottom": [(x0, y1), (x1, y1), (ix1, iy1), (ix0, iy1)],
        "left": [(x0, y), (ix0, iy0), (ix0, iy1), (x0, y1)],
        "right": [(x1, y), (ix1, iy0), (ix1, iy1), (x1, y1)],
        "center": [(ix0, iy0), (ix1, iy0), (ix1, iy1), (ix0, iy1)],
    }
    mapping = _surfaces_for(tooth, upper)
    caries = set(snap.get("caries_surfaces") or "")
    filled = set(snap.get("filling_surfaces") or "")
    base = fill_all or (COLORS["crown_fill"] if snap.get("crown") else "#FFFFFF")
    dash = 'stroke-dasharray="3,2"' if dashed else ""
    out = []
    for part, points in shapes.items():
        letter = mapping[part]
        fill = base
        if letter in filled:
            fill = COLORS["filling"]
        if letter in caries:
            fill = COLORS["caries"]
        out.append(_poly(points, fill, stroke or (COLORS["faint"] if dashed else COLORS["outline"]), 1, dash))
    if snap.get("crown") and not dashed:
        out.append(f'<rect x="{x0 - 1.5}" y="{y - 1.5}" width="{s + 3}" height="{s + 3}" fill="none" '
                   f'stroke="{COLORS["crown"]}" stroke-width="3" rx="3"/>')
    if stroke_width > 1:
        out.append(f'<rect x="{x0}" y="{y}" width="{s}" height="{s}" fill="none" stroke="{stroke}" '
                   f'stroke-width="{stroke_width}" rx="2"/>')
    return "".join(out)


def _roots(x, tooth, upper, rct=False, faint=False):
    top, bottom = UPPER_ROOT if upper else LOWER_ROOT
    tip, base = (top + 2, bottom) if upper else (bottom - 2, top)
    cx = x + W / 2
    molar = tooth % 10 >= 6
    centers = [cx - 6, cx + 6] if molar else [cx]
    half_base, half_tip = (5.5, 2) if molar else (8, 2.5)
    stroke = COLORS["faint"] if faint else COLORS["outline"]
    out = []
    for c in centers:
        out.append(_poly([(c - half_base, base), (c + half_base, base), (c + half_tip, tip), (c - half_tip, tip)],
                         "#F4F1EA" if not faint else "#FFFFFF", stroke))
        if rct:
            out.append(f'<line x1="{c}" y1="{base}" x2="{c}" y2="{tip + (3 if upper else -3)}" '
                       f'stroke="{COLORS["rct"]}" stroke-width="3" stroke-linecap="round"/>')
    return "".join(out)


def _implant(x, upper, stage):
    top, bottom = UPPER_ROOT if upper else LOWER_ROOT
    cx = x + W / 2
    body_top, body_bottom = (top + 6, bottom) if upper else (top, bottom - 6)
    out = [f'<rect x="{cx - 6}" y="{body_top}" width="12" height="{body_bottom - body_top}" rx="3" '
           f'fill="{COLORS["implant"]}" stroke="{COLORS["implant_dark"]}"/>']
    y = body_top + 5
    while y < body_bottom - 3:
        out.append(f'<line x1="{cx - 8}" y1="{y}" x2="{cx + 8}" y2="{y + 2}" stroke="{COLORS["implant_dark"]}" '
                   f'stroke-width="1.4"/>')
        y += 6
    if stage in ("uncovered", "impression", "loaded"):
        # healing abutment / abutment between the implant and the crown
        ay = body_bottom - 1 if upper else body_top - 7
        out.append(f'<rect x="{cx - 4}" y="{ay}" width="8" height="8" fill="{COLORS["implant_dark"]}"/>')
    return "".join(out)


def _badge(cx, cy, text, color):
    return (f'<circle cx="{cx}" cy="{cy}" r="7" fill="#fff" stroke="{color}" stroke-width="1.5"/>'
            f'<text x="{cx}" y="{cy + 3.5}" text-anchor="middle" font-size="9" font-weight="700" fill="{color}">'
            f"{escape(text)}</text>")


def _tooth(tooth, index, upper, snap, site, planned, link):
    x = _x(index)
    status = snap.get("status", S.PRESENT)
    box_y = UPPER_BOX_Y if upper else LOWER_BOX_Y
    parts = []
    stage = site.implant_status if site is not None else ("loaded" if status == S.IMPLANT else "")

    if status == S.MISSING:
        parts.append(_crown_box(x, box_y, tooth, upper, DEFAULT, dashed=True))
        top, bottom = UPPER_ROOT if upper else LOWER_ROOT
        y0, y1 = (top + 4, box_y + BOX) if upper else (box_y, bottom - 4)
        parts.append(f'<line x1="{x + 8}" y1="{y0}" x2="{x + W - 8}" y2="{y1}" stroke="#9AA0A6" stroke-width="2"/>'
                     f'<line x1="{x + W - 8}" y1="{y0}" x2="{x + 8}" y2="{y1}" stroke="#9AA0A6" stroke-width="2"/>')
    elif status == S.IMPLANT:
        parts.append(_implant(x, upper, stage))
        if stage == "loaded":
            parts.append(_crown_box(x, box_y, tooth, upper, DEFAULT, fill_all=COLORS["loaded"],
                                    stroke=COLORS["loaded_stroke"], stroke_width=2))
        else:
            parts.append(_crown_box(x, box_y, tooth, upper, DEFAULT, dashed=True))
            if stage == "impression":
                parts.append(f'<circle cx="{x + W / 2}" cy="{box_y + BOX / 2}" r="4" fill="{COLORS["plan"]}"/>')
    elif status == S.PONTIC:
        parts.append(_crown_box(x, box_y, tooth, upper, DEFAULT, fill_all="#DEE2E6"))
        mid = box_y + BOX / 2
        parts.append(f'<line x1="{x}" y1="{mid}" x2="{x + W}" y2="{mid}" stroke="{COLORS["outline"]}" stroke-width="3"/>')
    else:
        faint = status == S.IMPACTED
        parts.append(_roots(x, tooth, upper, rct=snap.get("rct"), faint=faint))
        if status == S.ROOT_REMNANT:
            parts.append(_crown_box(x, box_y, tooth, upper, DEFAULT, dashed=True))
            parts.append(f'<text x="{x + W / 2}" y="{box_y + BOX / 2 + 4}" text-anchor="middle" font-size="10" '
                         f'font-weight="700" fill="{COLORS["hopeless"]}">RR</text>')
        else:
            parts.append(_crown_box(x, box_y, tooth, upper, snap))
        if faint:
            cy = (UPPER_ROOT[0] + box_y + BOX) / 2 if upper else (box_y + LOWER_ROOT[1]) / 2
            parts.append(f'<ellipse cx="{x + W / 2}" cy="{cy}" rx="{W / 2 - 2}" ry="44" fill="none" '
                         f'stroke="#FD7E14" stroke-dasharray="4,3" stroke-width="1.5"/>')
        if snap.get("hopeless"):
            top, bottom = UPPER_ROOT if upper else LOWER_ROOT
            parts.append(f'<line x1="{x + 10}" y1="{bottom if upper else top}" x2="{x + W - 10}" '
                         f'y2="{top if upper else bottom}" stroke="{COLORS["hopeless"]}" stroke-width="2.5"/>')

    # small markers at the root tips
    badges = []
    if snap.get("caries") and not snap.get("caries_surfaces"):
        badges.append(("C", COLORS["caries"]))
    if snap.get("filled") and not snap.get("filling_surfaces"):
        badges.append(("F", COLORS["filling"]))
    if snap.get("hopeless"):
        badges.append(("H", COLORS["hopeless"]))
    if snap.get("fractured"):
        badges.append(("Fx", "#FD7E14"))
    if snap.get("not_sure"):
        badges.append(("?", "#6C757D"))
    if snap.get("mobility"):
        badges.append((f"M{snap['mobility']}", "#6F42C1"))
    if planned:
        badges.append(("P", COLORS["plan"]))
    for i, (text, color) in enumerate(badges[:3]):
        cy = (UPPER_ROOT[0] + 6 + i * 15) if upper else (LOWER_ROOT[1] - 6 - i * 15)
        parts.append(_badge(x + W - 8, cy, text, color))

    num_y = UPPER_NUM_Y if upper else LOWER_NUM_Y
    num_style = f'fill="{COLORS["plan"]}" font-weight="800" text-decoration="underline"' if planned else 'fill="#495057" font-weight="700"'
    parts.append(f'<text x="{x + W / 2}" y="{num_y}" text-anchor="middle" font-size="12" {num_style}>{tooth}</text>')

    title = f"{tooth}: {state_label(snap, site)}"
    if site is not None:
        title += f" — {site.implant_label}"
    if planned:
        title += " | " + _("Planned") + ": " + "; ".join(planned)
    body = f"<title>{escape(title)}</title>" + "".join(parts)
    hit = f'<rect x="{x}" y="0" width="{W}" height="{HEIGHT / 2 if upper else HEIGHT}" fill="transparent"/>'
    if not upper:
        hit = f'<rect x="{x}" y="{MID_Y}" width="{W}" height="{HEIGHT - MID_Y}" fill="transparent"/>'
    group = f'<g class="tooth" data-tooth="{tooth}">{hit}{body}</g>'
    if link:
        group = f'<a href="{escape(link.replace("__tooth__", str(tooth)))}">{group}</a>'
    return group


def render(states, planned=None, link=None, title=""):
    """``states``: tooth -> ToothState; ``planned``: tooth -> [descriptions];
    ``link``: URL with "__tooth__" placeholder to make teeth clickable."""
    planned = planned or {}
    out = [
        f'<svg class="odontogram" viewBox="0 0 {WIDTH} {HEIGHT}" xmlns="http://www.w3.org/2000/svg" '
        f'role="img" aria-label="{escape(title or _("Dental chart"))}" font-family="Cairo, Segoe UI, sans-serif">',
        f'<line x1="{PAD}" y1="{MID_Y}" x2="{WIDTH - PAD}" y2="{MID_Y}" stroke="#DEE2E6" stroke-dasharray="4,4"/>',
        f'<line x1="{WIDTH / 2}" y1="4" x2="{WIDTH / 2}" y2="{HEIGHT - 4}" stroke="#DEE2E6" stroke-dasharray="4,4"/>',
    ]
    for arch, upper in ((UPPER, True), (LOWER, False)):
        for index, tooth in enumerate(arch):
            state = states.get(tooth)
            snap = state.snapshot() if state is not None else DEFAULT
            site = state.implant_site if state is not None and state.implant_site_id else None
            out.append(_tooth(tooth, index, upper, snap, site, planned.get(tooth), link))
    out.append("</svg>")
    return mark_safe("".join(out))
