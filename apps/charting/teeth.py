"""FDI tooth numbers (permanent dentition) and helpers to read what dentists type."""

import re

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from apps.core.utils import normalize_digits

# Chart order: patient's right on the viewer's left.
UPPER = [18, 17, 16, 15, 14, 13, 12, 11, 21, 22, 23, 24, 25, 26, 27, 28]
LOWER = [48, 47, 46, 45, 44, 43, 42, 41, 31, 32, 33, 34, 35, 36, 37, 38]
ALL_TEETH = UPPER + LOWER
VALID_TEETH = frozenset(ALL_TEETH)
TOOTH_CHOICES = [(t, str(t)) for t in ALL_TEETH]

SURFACES = "MODBL"  # mesial, occlusal/incisal, distal, buccal/labial, lingual/palatal
_SURFACE_ALIASES = {"I": "O", "F": "B", "V": "B", "P": "L"}


def chart_order(teeth):
    return sorted(set(teeth), key=ALL_TEETH.index)


def parse_teeth(text):
    """Read "36, 37", "11-13", "13-23" (across the midline) or "36 46" into tooth numbers."""
    text = normalize_digits(text or "").strip()
    if not text:
        return []
    teeth = []
    for token in re.split(r"[\s,،;؛+/&]+", text):
        if not token:
            continue
        match = re.fullmatch(r"(\d{2})\s*[-–]\s*(\d{2})", token)
        if match:
            start, end = int(match.group(1)), int(match.group(2))
            arch = UPPER if start in UPPER else LOWER
            if start not in VALID_TEETH or end not in VALID_TEETH or end not in arch:
                raise ValidationError(
                    _("%(range)s is not a valid range: both teeth must be in the same jaw.") % {"range": token}
                )
            i, j = sorted((arch.index(start), arch.index(end)))
            teeth.extend(arch[i:j + 1])
            continue
        if not re.fullmatch(r"\d{2}", token) or int(token) not in VALID_TEETH:
            raise ValidationError(
                _("%(tooth)s is not a tooth number. Use FDI numbers 11-18, 21-28, 31-38, 41-48.") % {"tooth": token}
            )
        teeth.append(int(token))
    return chart_order(teeth)


def format_teeth(teeth):
    return ", ".join(str(t) for t in chart_order(teeth))


def parse_surfaces(text):
    """Normalise surfaces like "mod", "DO", "B" (I→O, F→B, P→L) to letters in MODBL order."""
    letters = set()
    for char in (text or "").upper():
        if char in " ,-/":
            continue
        char = _SURFACE_ALIASES.get(char, char)
        if char not in SURFACES:
            raise ValidationError(_("Surfaces must be letters among M, O, D, B, L (I, F, P are also accepted)."))
        letters.add(char)
    return "".join(s for s in SURFACES if s in letters)


def merge_surfaces(a, b):
    return "".join(s for s in SURFACES if s in set(a) | set(b))


def remove_surfaces(a, b):
    return "".join(s for s in SURFACES if s in set(a) - set(b))


def jaw(tooth):
    return "upper" if tooth // 10 in (1, 2) else "lower"


def tooth_type(tooth):
    position = tooth % 10
    if position <= 2:
        return "incisor"
    if position == 3:
        return "canine"
    if position <= 5:
        return "premolar"
    return "molar"


def is_anterior(tooth):
    return tooth % 10 <= 3


# Plain Arabic names, so the reception understands the numbers: 36 = الضرس الأول السفلي الأيسر.
_TOOTH_AR = {1: "القاطع الأوسط", 2: "القاطع الجانبي", 3: "الناب", 4: "الضاحك الأول", 5: "الضاحك الثاني",
             6: "الضرس الأول", 7: "الضرس الثاني", 8: "ضرس العقل"}
_BABY_TOOTH_AR = {1: "القاطع اللبني الأوسط", 2: "القاطع اللبني الجانبي", 3: "الناب اللبني",
                  4: "الضرس اللبني الأول", 5: "الضرس اللبني الثاني"}
_QUADRANT_AR = {1: ("العلوي", "الأيمن"), 2: ("العلوي", "الأيسر"), 3: ("السفلي", "الأيسر"), 4: ("السفلي", "الأيمن")}


def tooth_name_ar(number):
    """"الضرس الأول السفلي الأيسر" for 36; "" for anything that is not an FDI tooth number."""
    try:
        quadrant, position = divmod(int(number), 10)
    except (TypeError, ValueError):
        return ""
    names = _TOOTH_AR if quadrant <= 4 else _BABY_TOOTH_AR
    if quadrant > 4:
        quadrant -= 4
    if quadrant not in _QUADRANT_AR or position not in names:
        return ""
    jaw, side = _QUADRANT_AR[quadrant]
    return f"{names[position]} {jaw} {side}"


def teeth_explained_ar(text):
    """[(36, "الضرس الأول السفلي الأيسر"), ...] for what the dentist typed; [] if it cannot be read."""
    try:
        teeth = parse_teeth(text)
    except ValidationError:
        return []
    return [(tooth, tooth_name_ar(tooth)) for tooth in teeth]


def teeth_ar(text):
    """"36 (الضرس الأول السفلي الأيسر)، 46 (...)" or the text as typed if it cannot be read."""
    explained = teeth_explained_ar(text)
    if not explained:
        return text or ""
    return "، ".join(f"{tooth} ({name})" for tooth, name in explained)


# Round 15: how big a prosthesis (or a planned one) is, read from its teeth and its name.
SPAN_CHOICES = [("single", _("Single crown / unit")), ("bridge", _("Bridge")), ("full_arch", _("Full arch"))]
_FULL_ARCH_WORDS = ("all-on", "full arch", "full-arch", "overdenture", "complete denture")
_PROSTHETIC_GROUPS = ("fixed", "implant_teeth", "removable")


def span_kind(teeth, name="", group=""):
    """"single", "bridge" or "full_arch" for prosthetic work (crowns, bridges, teeth on implants, dentures), else "".
    A full arch: its name says so (All-on-X, overdenture, denture) or 10 teeth or more in one jaw; a bridge: 2 teeth
    or more; a single crown: one tooth."""
    if group and group not in _PROSTHETIC_GROUPS:
        return ""
    lower = (name or "").lower()
    if any(word in lower for word in _FULL_ARCH_WORDS) or ("denture" in lower and "partial" not in lower):
        return "full_arch"
    try:
        numbers = parse_teeth(teeth) if isinstance(teeth, str) else list(teeth or [])
    except Exception:  # noqa: BLE001 - an old value that does not read
        numbers = []
    if not numbers:
        return ""
    by_jaw = {}
    for tooth in numbers:
        by_jaw[tooth // 10 in (1, 2, 5, 6)] = by_jaw.get(tooth // 10 in (1, 2, 5, 6), 0) + 1
    if max(by_jaw.values()) >= 10:
        return "full_arch"
    return "bridge" if len(numbers) > 1 else "single"


def span_label(kind):
    return dict(SPAN_CHOICES).get(kind, "")
