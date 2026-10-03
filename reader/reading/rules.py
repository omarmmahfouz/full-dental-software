"""The clinic's rules for a value, as in the dental system (which checks everything again when it imports): Arabic
digits, Egyptian mobiles, the 14-digit national ID and what it holds, and a full name in Arabic. Kept here so the
reader is a program of its own."""

import re
from datetime import date

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

_DIGITS = {ord(c): str(i) for i, c in enumerate("٠١٢٣٤٥٦٧٨٩")}
_DIGITS.update({ord(c): str(i) for i, c in enumerate("۰۱۲۳۴۵۶۷۸۹")})
EGYPT_MOBILE = re.compile(r"^01[0125]\d{8}$")
INTERNATIONAL = re.compile(r"^\+\d{8,15}$")
ARABIC_NAME = re.compile(r"^[ء-غـ-ْٰ-ۓ ]+$")


def normalize_digits(value):
    return "" if value is None else str(value).translate(_DIGITS)


def normalize_phone(value):
    """11 digits starting with 01 for an Egyptian number, whatever way it was written; "+" and digits else."""
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
    return "+" + digits if plus else digits


def validate_phone(value, mobile_only=True):
    if INTERNATIONAL.match(value) and not value.startswith("+20"):
        return value
    if EGYPT_MOBILE.match(value):
        return value
    if not mobile_only and re.match(r"^0\d{7,10}$", value):
        return value
    digits = len(re.sub(r"\D", "", value))
    if value.startswith("01") and digits != 11:
        raise ValidationError(_("This mobile has %(n)s digits: Egyptian mobiles have exactly 11 (e.g. 01001234567).")
                              % {"n": digits})
    raise ValidationError(_("Enter a valid mobile number, e.g. 01001234567 (or +country code for foreign numbers)."))


def parse_national_id(value):
    """{birth_date, gender, governorate_code} from a 14-digit Egyptian national ID, or ValidationError."""
    value = normalize_digits(value or "").strip()
    if not re.fullmatch(r"\d{14}", value):
        raise ValidationError(_("The national ID must be exactly 14 digits."))
    century = {"2": 1900, "3": 2000}.get(value[0])
    if century is None:
        raise ValidationError(_("The national ID must start with 2 or 3."))
    try:
        birth = date(century + int(value[1:3]), int(value[3:5]), int(value[5:7]))
    except ValueError:
        raise ValidationError(_("The birth date inside the national ID is not valid."))
    if birth > date.today():
        raise ValidationError(_("The birth date inside the national ID is in the future."))
    return {"birth_date": birth, "gender": "M" if int(value[12]) % 2 else "F", "governorate_code": value[7:9]}


def clean_arabic_name(value):
    name = " ".join((value or "").split())
    if not ARABIC_NAME.match(name):
        raise ValidationError(_("Write the name in Arabic letters only, as on the ID."))
    if len(name.split()) < 3:
        raise ValidationError(_("Write at least three names (the patient, the father and the grandfather), as on "
                                "the ID."))
    return name
