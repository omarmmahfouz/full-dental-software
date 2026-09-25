"""Draws the dental chart as SVG (FDI, patient's right on the viewer's left).

Each tooth is drawn as it looks from the cheek side: its own crown shape (incisor, canine,
premolar, molar) and its roots (one, two or three), upper roots pointing up and lower roots
down. Under each crown a round diagram shows the five surfaces (M, O, D, B, L) for caries
and fillings. Crowns, root canals, implants (with their stage), missing teeth, bridge pontics,
root remnants, impacted teeth and planned work are all shown. Pure server-side SVG: prints
and works offline.
"""

import math

from django.utils.html import escape
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _

from .models import ToothState
from .rules import DEFAULT, state_label
from .teeth import LOWER, UPPER

S = ToothState.Status
W, GAP, PAD = 46, 16, 8
WIDTH = PAD * 2 + 16 * W + GAP
UPPER_NUM_Y = 14
UPPER_CEJ = 72          # upper teeth: crown below this line, roots above
UPPER_SURF_Y = 118      # centre of the round surface diagram
MID_Y = 136
LOWER_SURF_Y = 154
LOWER_CEJ = 200         # lower teeth: crown above this line, roots below
LOWER_NUM_Y = 262
HEIGHT = 270
SURF_R, SURF_CORE = 11, 4.6

COLORS = {
    "caries": "#E35D6A",
    "filling": "#3D7FE0",
    "crown": "#B8860B",
    "crown_fill": "#FFF4CC",
    "rct": "#D62839",
    "implant": "#9A9EA3",
    "implant_dark": "#5B5E62",
    "loaded": "#D6EAB3",
    "loaded_stroke": "#5C8020",
    "outline": "#8C8577",
    "root_outline": "#A89A7C",
    "ghost": "#C5C9CE",
    "plan": "#0D6EFD",
    "hopeless": "#D62839",
    "pontic": "#DEE2E6",
}

# Tooth shapes by position in the quadrant (1 = central incisor … 8 = wisdom tooth):
# crown width, width at the neck, crown height, root length, roots seen from the cheek, crown style,
# where the roots split (fraction of the root length from the neck; molars split high).
UPPER_SHAPES = {
    1: (34, 24, 30, 40, 1, "incisor", 0), 2: (28, 19, 26, 36, 1, "incisor", 0), 3: (30, 21, 30, 48, 1, "canine", 0),
    4: (28, 20, 26, 38, 2, "premolar", 0.6), 5: (28, 20, 25, 38, 1, "premolar", 0),
    6: (38, 30, 25, 36, 3, "molar", 0.3), 7: (36, 28, 24, 34, 3, "molar", 0.35), 8: (32, 26, 22, 28, 3, "molar", 0.5),
}
LOWER_SHAPES = {
    1: (22, 15, 26, 36, 1, "incisor", 0), 2: (24, 16, 27, 38, 1, "incisor", 0), 3: (28, 20, 30, 46, 1, "canine", 0),
    4: (28, 19, 26, 40, 1, "premolar", 0), 5: (29, 20, 25, 40, 1, "premolar", 0),
    6: (40, 32, 25, 38, 2, "molar", 0.3), 7: (38, 30, 24, 36, 2, "molar", 0.35), 8: (34, 28, 22, 30, 2, "molar", 0.45),
}

DEFS = (
    '<defs>'
    '<linearGradient id="odg-enamel" x1="0" x2="1"><stop offset="0" stop-color="#EFE9DC"/>'
    '<stop offset=".45" stop-color="#FFFFFF"/><stop offset="1" stop-color="#E8E0CE"/></linearGradient>'
    '<linearGradient id="odg-root" x1="0" x2="1"><stop offset="0" stop-color="#E9DBBB"/>'
    '<stop offset=".5" stop-color="#F7EFDD"/><stop offset="1" stop-color="#E2D1AC"/></linearGradient>'
    '<linearGradient id="odg-metal" x1="0" x2="1"><stop offset="0" stop-color="#7D8185"/>'
    '<stop offset=".5" stop-color="#C9CDD1"/><stop offset="1" stop-color="#6F7377"/></linearGradient>'
    '</defs>'
)


def _x(index):
    return PAD + index * W + (GAP if index >= 8 else 0)


def _n(value):
    return f"{value:.1f}".rstrip("0").rstrip(".")


# ------------------------------------------------------------ tooth outlines (local coordinates)
# The neck (cemento-enamel junction) is at y = 0, the crown goes to +y and the roots to -y;
# the mesial side (towards the midline) is +x. The drawing is then placed and mirrored.
def _crown_path(shape):
    cw, cerv, h, _rl, _roots, style, _split = shape
    a, b = cw / 2, cerv / 2
    p = [f"M{_n(-b)},0", f"C{_n(-a)},{_n(h * .15)} {_n(-a)},{_n(h * .45)} {_n(-a + 1)},{_n(h * .62)}"]
    if style == "incisor":
        p += [f"C{_n(-a + 1)},{_n(h * .9)} {_n(-a + 3)},{_n(h)} {_n(-a + 5)},{_n(h)}", f"L{_n(a - 5)},{_n(h)}",
              f"C{_n(a - 3)},{_n(h)} {_n(a - 1)},{_n(h * .9)} {_n(a - 1)},{_n(h * .62)}"]
    elif style == "canine":
        p += [f"C{_n(-a + 1)},{_n(h * .78)} {_n(-a * .45)},{_n(h * .86)} -1.5,{_n(h * .99)}",
              f"Q0,{_n(h * 1.02)} 1.5,{_n(h * .99)}",
              f"C{_n(a * .45)},{_n(h * .86)} {_n(a - 1)},{_n(h * .78)} {_n(a - 1)},{_n(h * .62)}"]
    elif style == "premolar":
        p += [f"C{_n(-a + 1)},{_n(h * .85)} {_n(-a * .5)},{_n(h * .9)} -2,{_n(h * .98)}",
              f"Q0,{_n(h)} 2,{_n(h * .98)}",
              f"C{_n(a * .5)},{_n(h * .9)} {_n(a - 1)},{_n(h * .85)} {_n(a - 1)},{_n(h * .62)}"]
    else:  # molar: two cusps seen from the cheek
        p += [f"C{_n(-a + 1)},{_n(h * .85)} {_n(-a * .8)},{_n(h)} {_n(-a * .5)},{_n(h)}",
              f"C{_n(-a * .25)},{_n(h)} {_n(-a * .12)},{_n(h * .9)} 0,{_n(h * .9)}",
              f"C{_n(a * .12)},{_n(h * .9)} {_n(a * .25)},{_n(h)} {_n(a * .5)},{_n(h)}",
              f"C{_n(a * .8)},{_n(h)} {_n(a - 1)},{_n(h * .85)} {_n(a - 1)},{_n(h * .62)}"]
    p += [f"C{_n(a)},{_n(h * .45)} {_n(a)},{_n(h * .15)} {_n(b)},0", f"Q0,-3 {_n(-b)},0Z"]
    return " ".join(p)


def _single_root(half, length):
    return (f"M{_n(-half)},0 C{_n(-half)},{_n(-length * .45)} {_n(-half * .55)},{_n(-length * .9)} "
            f"-1.2,{_n(-length)} Q0,{_n(-length - 1.5)} 1.2,{_n(-length)} "
            f"C{_n(half * .55)},{_n(-length * .9)} {_n(half)},{_n(-length * .45)} {_n(half)},0Z")


def _split_root(half, length, split):
    """Two roots (mesial and distal) joined up to ``split`` of their length."""
    f = -length * split
    return (f"M{_n(-half)},0 C{_n(-half)},{_n(-length * .5)} {_n(-half * .8)},{_n(-length * .9)} "
            f"{_n(-half * .6)},{_n(-length)} Q{_n(-half * .45)},{_n(-length - 1.5)} {_n(-half * .3)},{_n(-length * .97)} "
            f"C{_n(-half * .2)},{_n(-length * .7)} {_n(-half * .12)},{_n(f - 4)} 0,{_n(f)} "
            f"C{_n(half * .12)},{_n(f - 4)} {_n(half * .2)},{_n(-length * .7)} {_n(half * .3)},{_n(-length * .97)} "
            f"Q{_n(half * .45)},{_n(-length - 1.5)} {_n(half * .6)},{_n(-length)} "
            f"C{_n(half * .8)},{_n(-length * .9)} {_n(half)},{_n(-length * .5)} {_n(half)},0Z")


def _root_paths(shape):
    """[(path, is_behind)] — upper molars show their palatal root behind the two cheek-side roots."""
    _cw, cerv, _h, rl, roots, _style, split = shape
    b = cerv / 2
    if roots == 1:
        return [(_single_root(b, rl), False)]
    paths = [(_split_root(b, rl, split), False)]
    if roots == 3:
        paths.insert(0, (_single_root(b * .55, rl * 1.06), True))
    return paths


def _canals(shape):
    """Root canal lines (for root canal treatment)."""
    _cw, cerv, _h, rl, roots, _style, _split = shape
    b = cerv / 2
    if roots == 1:
        return [(0, -2, 0, -rl + 3)]
    return [(-b * .3, -2, -b * .45, -rl + 3), (b * .3, -2, b * .45, -rl + 3)]


def _implant(shape, stage):
    _cw, _cerv, _h, rl, _roots, _style, _split = shape
    length = min(rl * .85, 34)
    out = [f'<path d="M-6,-1 L6,-1 L5,{_n(-length + 4)} Q0,{_n(-length - 2)} -5,{_n(-length + 4)} Z" '
           f'fill="url(#odg-metal)" stroke="{COLORS["implant_dark"]}" stroke-width="1"/>']
    y = -5
    while y > -length + 5:
        half = 6 - (abs(y) / length) * 1.5
        out.append(f'<line x1="{_n(-half - 1.5)}" y1="{_n(y)}" x2="{_n(half + 1.5)}" y2="{_n(y - 1.5)}" '
                   f'stroke="{COLORS["implant_dark"]}" stroke-width="1.2"/>')
        y -= 4.5
    if stage in ("uncovered", "impression", "loaded"):
        out.append(f'<rect x="-3.5" y="-1" width="7" height="8" rx="1" fill="{COLORS["implant_dark"]}"/>')
    else:  # cover screw, under the gum
        out.append(f'<rect x="-6" y="-2.5" width="12" height="2.5" rx="1" fill="{COLORS["implant_dark"]}"/>')
    return "".join(out)


# ------------------------------------------------------------ surfaces (round diagram)
def _surfaces_for(tooth, upper):
    """Which part of the round diagram (top/bottom/left/right/center) shows which surface letter."""
    quadrant = tooth // 10
    left_is_mesial = quadrant in (2, 3)  # teeth drawn on the right half have mesial on their left
    return {
        "top": "B" if upper else "L",
        "bottom": "L" if upper else "B",
        "left": "M" if left_is_mesial else "D",
        "right": "D" if left_is_mesial else "M",
        "center": "O",
    }


def _sector(cx, cy, start, end):
    def point(radius, angle):
        rad = math.radians(angle)
        return f"{_n(cx + radius * math.cos(rad))},{_n(cy + radius * math.sin(rad))}"

    return (f"M{point(SURF_R, start)} A{SURF_R},{SURF_R} 0 0 1 {point(SURF_R, end)} "
            f"L{point(SURF_CORE, end)} A{SURF_CORE},{SURF_CORE} 0 0 0 {point(SURF_CORE, start)}Z")


def _surface_diagram(cx, cy, tooth, upper, snap, ghost=False):
    mapping = _surfaces_for(tooth, upper)
    caries = set(snap.get("caries_surfaces") or "")
    filled = set(snap.get("filling_surfaces") or "")
    base = COLORS["crown_fill"] if snap.get("crown") else "#FFFFFF"
    stroke = COLORS["ghost"] if ghost else "#8F959B"
    dash = ' stroke-dasharray="2,2"' if ghost else ""
    out = []
    parts = {"top": (225, 315), "right": (315, 405), "bottom": (45, 135), "left": (135, 225)}
    for part, (start, end) in parts.items():
        letter = mapping[part]
        fill = COLORS["caries"] if letter in caries else COLORS["filling"] if letter in filled else base
        out.append(f'<path d="{_sector(cx, cy, start, end)}" fill="{"#FFFFFF" if ghost else fill}" '
                   f'stroke="{stroke}" stroke-width="1"{dash}/>')
    center = COLORS["caries"] if "O" in caries else COLORS["filling"] if "O" in filled else base
    out.append(f'<circle cx="{_n(cx)}" cy="{_n(cy)}" r="{SURF_CORE}" fill="{"#FFFFFF" if ghost else center}" '
               f'stroke="{stroke}" stroke-width="1"{dash}/>')
    if snap.get("crown") and not ghost:
        out.append(f'<circle cx="{_n(cx)}" cy="{_n(cy)}" r="{SURF_R + 1.5}" fill="none" stroke="{COLORS["crown"]}" '
                   f'stroke-width="2.5"/>')
    return "".join(out)


# ------------------------------------------------------------ one tooth
def _badge(cx, cy, text, color):
    return (f'<circle cx="{_n(cx)}" cy="{_n(cy)}" r="7" fill="#fff" stroke="{color}" stroke-width="1.5"/>'
            f'<text x="{_n(cx)}" y="{_n(cy + 3.5)}" text-anchor="middle" font-size="9" font-weight="700" '
            f'fill="{color}">{escape(text)}</text>')


def _tooth(tooth, index, upper, snap, site, planned, link):
    x = _x(index)
    cx = x + W / 2
    shape = (UPPER_SHAPES if upper else LOWER_SHAPES)[tooth % 10]
    cej = UPPER_CEJ if upper else LOWER_CEJ
    mirror = -1 if tooth // 10 in (2, 3) else 1
    place = f'translate({_n(cx)},{cej}) scale({mirror},{1 if upper else -1})'
    status = snap.get("status", S.PRESENT)
    stage = site.implant_status if site is not None else ("loaded" if status == S.IMPLANT else "")
    crown = _crown_path(shape)
    ghost = f'fill="none" stroke="{COLORS["ghost"]}" stroke-width="1" stroke-dasharray="3,2"'

    drawing = []  # in the tooth's own (mirrored) coordinates
    over = []     # in page coordinates: text, badges, crossing lines
    ghost_surfaces = False
    if status == S.MISSING:
        drawing += [f'<path d="{path}" {ghost}/>' for path, _behind in _root_paths(shape)]
        drawing.append(f'<path d="{crown}" {ghost}/>')
        y0, y1 = (cej - shape[3], cej + shape[2]) if upper else (cej - shape[2], cej + shape[3])
        over.append(f'<line x1="{_n(x + 9)}" y1="{y0}" x2="{_n(x + W - 9)}" y2="{y1}" stroke="#9AA0A6" stroke-width="2"/>'
                    f'<line x1="{_n(x + W - 9)}" y1="{y0}" x2="{_n(x + 9)}" y2="{y1}" stroke="#9AA0A6" stroke-width="2"/>')
        ghost_surfaces = True
    elif status == S.IMPLANT:
        drawing.append(_implant(shape, stage))
        if stage == "loaded":
            drawing.append(f'<path d="{crown}" fill="{COLORS["loaded"]}" stroke="{COLORS["loaded_stroke"]}" '
                           f'stroke-width="2"/>')
        else:
            drawing.append(f'<path d="{crown}" {ghost}/>')
            ghost_surfaces = True
            if stage == "impression":
                over.append(f'<circle cx="{_n(cx)}" cy="{_n(cej + (14 if upper else -14))}" r="4" '
                            f'fill="{COLORS["plan"]}"/>')
    elif status == S.PONTIC:
        drawing.append(f'<path d="{crown}" fill="{COLORS["pontic"]}" stroke="{COLORS["outline"]}" stroke-width="1.2"/>')
        mid = cej + (shape[2] / 2 if upper else -shape[2] / 2)
        over.append(f'<line x1="{x}" y1="{_n(mid)}" x2="{x + W}" y2="{_n(mid)}" stroke="{COLORS["outline"]}" '
                    f'stroke-width="3"/>')
    else:
        faint = status == S.IMPACTED
        for path, behind in _root_paths(shape):
            fill = "#F4ECDA" if behind else "url(#odg-root)"
            drawing.append(f'<path d="{path}" fill="{fill}" stroke="{COLORS["root_outline"]}" stroke-width="1"/>')
        if snap.get("rct"):
            for x1, y1, x2, y2 in _canals(shape):
                drawing.append(f'<line x1="{_n(x1)}" y1="{y1}" x2="{_n(x2)}" y2="{_n(y2)}" stroke="{COLORS["rct"]}" '
                               f'stroke-width="2.6" stroke-linecap="round"/>')
        if status == S.ROOT_REMNANT:
            drawing.append(f'<path d="{crown}" {ghost}/>')
            over.append(f'<text x="{_n(cx)}" y="{_n(cej + (18 if upper else -10))}" text-anchor="middle" '
                        f'font-size="10" font-weight="700" fill="{COLORS["hopeless"]}">RR</text>')
            ghost_surfaces = True
        elif snap.get("crown"):
            drawing.append(f'<path d="{crown}" fill="{COLORS["crown_fill"]}" stroke="{COLORS["crown"]}" '
                           f'stroke-width="2.2"/>')
        else:
            drawing.append(f'<path d="{crown}" fill="url(#odg-enamel)" stroke="{COLORS["outline"]}" stroke-width="1.1"/>')
            filled, caries = set(snap.get("filling_surfaces") or ""), set(snap.get("caries_surfaces") or "")
            if filled or caries:  # a visible spot on the crown too
                color = COLORS["caries"] if caries else COLORS["filling"]
                drawing.append(f'<ellipse cx="0" cy="{_n(shape[2] * .55)}" rx="{_n(shape[0] * .18)}" '
                               f'ry="{_n(shape[2] * .16)}" fill="{color}" opacity=".85"/>')
        if faint:
            drawing.insert(0, '<g opacity=".55">')
            drawing.append("</g>")
            cy = cej - shape[3] / 2 + shape[2] / 2 if upper else cej + shape[3] / 2 - shape[2] / 2
            over.append(f'<ellipse cx="{_n(cx)}" cy="{_n(cy)}" rx="{W / 2 - 2}" ry="{_n((shape[2] + shape[3]) / 2 + 4)}" '
                        f'fill="none" stroke="#FD7E14" stroke-dasharray="4,3" stroke-width="1.5"/>')
        if snap.get("hopeless"):
            top, bottom = (cej - shape[3], cej + shape[2]) if upper else (cej - shape[2], cej + shape[3])
            over.append(f'<line x1="{x + 10}" y1="{bottom}" x2="{x + W - 10}" y2="{top}" '
                        f'stroke="{COLORS["hopeless"]}" stroke-width="2.5"/>')

    parts = [f'<g transform="{place}">{"".join(drawing)}</g>']
    parts.append(_surface_diagram(cx, UPPER_SURF_Y if upper else LOWER_SURF_Y, tooth, upper,
                                  snap if not ghost_surfaces else DEFAULT, ghost=ghost_surfaces))
    parts += over

    # small markers beside the roots
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
        cy = (UPPER_NUM_Y + 16 + i * 15) if upper else (LOWER_NUM_Y - 16 - i * 15)
        parts.append(_badge(x + W - 7, cy, text, color))

    num_y = UPPER_NUM_Y if upper else LOWER_NUM_Y
    num_style = (f'fill="{COLORS["plan"]}" font-weight="800" text-decoration="underline"' if planned
                 else 'fill="#495057" font-weight="700"')
    parts.append(f'<text x="{_n(cx)}" y="{num_y}" text-anchor="middle" font-size="12" {num_style}>{tooth}</text>')

    title = f"{tooth}: {state_label(snap, site)}"
    if site is not None:
        title += f" — {site.implant_label}"
    if planned:
        title += " | " + _("Planned") + ": " + "; ".join(planned)
    top, height = (0, MID_Y) if upper else (MID_Y, HEIGHT - MID_Y)
    hit = f'<rect x="{x}" y="{top}" width="{W}" height="{height}" fill="transparent"/>'
    group = f'<g class="tooth" data-tooth="{tooth}"><title>{escape(title)}</title>{hit}{"".join(parts)}</g>'
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
        DEFS,
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
