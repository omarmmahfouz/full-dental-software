"""The shade guides the prosthodontist and the lab use, with a colour for each tab so the screen can show the guide.
The colours are close to the real tabs, not exact: a screen cannot show a shade truly, the real guide decides."""

from django.utils.translation import gettext_lazy as _

CLASSICAL = "classical"
MASTER = "3d_master"
GUIDES = [(CLASSICAL, _("VITA classical")), (MASTER, _("VITA 3D-Master"))]

# VITA classical A1–D4, in the order of the guide (by hue group).
CLASSICAL_TABS = [
    ("A1", "#F0E4C9"), ("A2", "#EAD7B3"), ("A3", "#E2CA9D"), ("A3.5", "#DABD8B"), ("A4", "#CDAC75"),
    ("B1", "#F3EBD6"), ("B2", "#ECDDB7"), ("B3", "#E1CB96"), ("B4", "#D7BD84"),
    ("C1", "#E5DDC7"), ("C2", "#D9CCAD"), ("C3", "#CCBC9A"), ("C4", "#BAA581"),
    ("D2", "#E5D9C2"), ("D3", "#D9C9A8"), ("D4", "#D2C199"),
]

# VITA 3D-Master: value group (0 = bleached … 5 = darkest), hue (L yellowish, M middle, R reddish) and chroma.
MASTER_SHADES = ["0M1", "0M2", "0M3", "1M1", "1M2", "2L1.5", "2L2.5", "2M1", "2M2", "2M3", "2R1.5", "2R2.5",
                 "3L1.5", "3L2.5", "3M1", "3M2", "3M3", "3R1.5", "3R2.5", "4L1.5", "4L2.5", "4M1", "4M2", "4M3",
                 "4R1.5", "4R2.5", "5M1", "5M2", "5M3"]


def master_colour(shade):
    """An approximate colour for a 3D-Master tab, from its value, hue and chroma."""
    value = int(shade[0])
    hue = shade[1]
    chroma = float(shade[2:])
    lightness = 93 - value * 6.2
    saturation = 18 + chroma * 13
    hue_deg = {"L": 46, "M": 40, "R": 32}[hue]
    return _hsl_hex(hue_deg, min(saturation, 62), lightness - chroma * 2.2)


def _hsl_hex(h, s, lightness):
    s, lightness = s / 100, lightness / 100
    c = (1 - abs(2 * lightness - 1)) * s
    x = c * (1 - abs((h / 60) % 2 - 1))
    m = lightness - c / 2
    r, g, b = (c, x, 0) if h < 60 else (x, c, 0)
    return "#{:02X}{:02X}{:02X}".format(*(round((v + m) * 255) for v in (r, g, b)))


MASTER_TABS = [(shade, master_colour(shade)) for shade in MASTER_SHADES]

# The shade of the prepared tooth (IPS Natural Die), for all-ceramic crowns and veneers.
STUMP_TABS = [("ND1", "#EADFC3"), ("ND2", "#E5D2AC"), ("ND3", "#D9BE8D"), ("ND4", "#CCAD7D"), ("ND5", "#D4B68E"),
              ("ND6", "#B99A72"), ("ND7", "#C3B59F"), ("ND8", "#A48E72"), ("ND9", "#8C7A69")]

TABS = {CLASSICAL: CLASSICAL_TABS, MASTER: MASTER_TABS}
COLOURS = {name: colour for tabs in (CLASSICAL_TABS, MASTER_TABS, STUMP_TABS) for name, colour in tabs}


def shade_choices(current=""):
    """The shades grouped by guide, for a drop-down (a shade typed before, not on a guide, is kept)."""
    known = set(COLOURS)
    extra = [(current, current)] if current and current not in known else []
    return [("", "—")] + extra + [(str(label), [(name, name) for name, _colour in TABS[code]]) for code, label in GUIDES]


def stump_choices():
    return [("", "—")] + [(name, name) for name, _colour in STUMP_TABS]


def guide_of(shade):
    for code, tabs in TABS.items():
        if shade in {name for name, _colour in tabs}:
            return code
    return ""


def picker_data():
    """What the shade picker on the page draws (static/js/app.js ``data-shade-picker``)."""
    return {"guides": {code: [{"name": n, "colour": c} for n, c in tabs] for code, tabs in TABS.items()},
            "stump": [{"name": n, "colour": c} for n, c in STUMP_TABS]}
