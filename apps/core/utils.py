"""Small helpers shared by every module (digits, phones, Egyptian national IDs)."""

import re
from datetime import date

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

# Arabic-Indic (٠١٢...) and Persian (۰۱۲...) digits typed on Arabic keyboards.
_DIGIT_MAP = {ord(c): str(i) for i, c in enumerate("٠١٢٣٤٥٦٧٨٩")}
_DIGIT_MAP.update({ord(c): str(i) for i, c in enumerate("۰۱۲۳۴۵۶۷۸۹")})

EGYPT_MOBILE_RE = re.compile(r"^01[0125]\d{8}$")
INTERNATIONAL_RE = re.compile(r"^\+\d{8,15}$")


def normalize_digits(value):
    """Convert Arabic/Persian digits to Western digits."""
    if value is None:
        return value
    return str(value).translate(_DIGIT_MAP)


# Letters typed in different ways in Arabic names: أحمد / احمد, فاطمة / فاطمه, مصطفى / مصطفي.
_ARABIC_VARIANTS = {}
for _group in ("اأإآ", "ةه", "ىي"):
    for _letter in _group:
        _ARABIC_VARIANTS[_letter] = f"[{_group}]"


def name_patterns(text):
    """One regular expression per word, matching the usual spelling variants of Arabic letters."""
    return ["".join(_ARABIC_VARIANTS.get(ch, re.escape(ch)) for ch in word) for word in str(text).split()]


def normalize_phone(value):
    """Return a canonical phone string so duplicates can be detected.

    Egyptian numbers become 11 digits starting with 01 (e.g. 01001234567),
    whatever way they were typed (+20 100 123 4567, 0020..., ١٠٠...).
    Foreign numbers keep a leading "+".
    """
    if not value:
        return ""
    value = normalize_digits(str(value)).strip()
    plus = value.startswith("+") or value.startswith("00")
    digits = re.sub(r"\D", "", value)
    if value.startswith("00"):
        digits = digits[2:]
    if digits.startswith("20") and len(digits) == 12 and digits[2] == "1":
        return "0" + digits[2:]
    if len(digits) == 10 and digits.startswith("1"):
        return "0" + digits
    if plus:
        return "+" + digits
    return digits


def validate_phone(value, mobile_only=True):
    """Validate a normalized phone number.

    Egyptian numbers must be mobiles (010/011/012/015) when ``mobile_only``;
    foreign numbers are accepted in +<country><number> form.
    """
    if INTERNATIONAL_RE.match(value) and not value.startswith("+20"):
        return value
    if EGYPT_MOBILE_RE.match(value):
        return value
    if not mobile_only and re.match(r"^0\d{7,10}$", value):
        return value  # landline
    digits = len(re.sub(r"\D", "", value))
    if value.startswith("01") and digits != 11:
        raise ValidationError(
            _("This mobile has %(n)s digits: Egyptian mobiles have exactly 11 (e.g. 01001234567).") % {"n": digits},
            code="invalid_phone",
        )
    raise ValidationError(
        _("Enter a valid mobile number, e.g. 01001234567 (or +country code for foreign numbers)."),
        code="invalid_phone",
    )


EGYPT_GOVERNORATES = {
    "01": _("Cairo"), "02": _("Alexandria"), "03": _("Port Said"), "04": _("Suez"),
    "11": _("Damietta"), "12": _("Dakahlia"), "13": _("Sharqia"), "14": _("Qalyubia"),
    "15": _("Kafr El Sheikh"), "16": _("Gharbia"), "17": _("Monufia"), "18": _("Beheira"),
    "19": _("Ismailia"), "21": _("Giza"), "22": _("Beni Suef"), "23": _("Fayoum"),
    "24": _("Minya"), "25": _("Asyut"), "26": _("Sohag"), "27": _("Qena"),
    "28": _("Aswan"), "29": _("Luxor"), "31": _("Red Sea"), "32": _("New Valley"),
    "33": _("Matrouh"), "34": _("North Sinai"), "35": _("South Sinai"), "88": _("Outside Egypt"),
}
GOVERNORATE_CHOICES = list(EGYPT_GOVERNORATES.items())


def parse_egyptian_national_id(value):
    """Validate a 14-digit Egyptian national ID and extract its data.

    Layout: C YYMMDD GG SSS G X
      C  = century (2 → 1900s, 3 → 2000s)
      GG = governorate code, the 13th digit is odd for males / even for females.
    Returns a dict with ``birth_date``, ``gender`` ("M"/"F"), ``governorate`` and its ``governorate_code``.
    Raises ValidationError when the number cannot be a real national ID.
    """
    value = normalize_digits(value or "").strip()
    if not re.fullmatch(r"\d{14}", value):
        raise ValidationError(_("The national ID must be exactly 14 digits."), code="invalid_nid")
    century = {"2": 1900, "3": 2000}.get(value[0])
    if century is None:
        raise ValidationError(_("The national ID must start with 2 or 3."), code="invalid_nid")
    try:
        birth = date(century + int(value[1:3]), int(value[3:5]), int(value[5:7]))
    except ValueError:
        raise ValidationError(_("The birth date inside the national ID is not valid."), code="invalid_nid")
    if birth > date.today():
        raise ValidationError(_("The birth date inside the national ID is in the future."), code="invalid_nid")
    return {
        "birth_date": birth,
        "gender": "M" if int(value[12]) % 2 else "F",
        "governorate": EGYPT_GOVERNORATES.get(value[7:9], ""),
        "governorate_code": value[7:9] if value[7:9] in EGYPT_GOVERNORATES else "",
    }


def age_from_birth_date(birth_date, today=None):
    if not birth_date:
        return None
    today = today or date.today()
    return today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))


def minutes_between(start, end):
    """Whole minutes from ``start`` to ``end`` (negative when end is earlier)."""
    if not start or not end:
        return None
    return round((end - start).total_seconds() / 60)
