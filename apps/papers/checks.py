"""The system's own checks of what Claude read, before a person sees it: every value is cleaned the way the forms
expect it, compared between the two readings and between pages, and checked with the rules of the forms (the
national ID and what it says, the mobiles, the dates, the readings' usual range, the lists). A value with any
problem is marked "please check"; only a clear value both readings agree on is "sure"."""

import re
from collections import defaultdict
from datetime import date, datetime

from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.core.utils import EGYPT_GOVERNORATES, normalize_digits, normalize_phone, parse_egyptian_national_id, \
    validate_phone

from .fields import (BEST_PAGE, BY_NAME, CHOICE, CONDITIONS, DATE, DECIMAL, DENTIST, NAME, NAMES, NATIONAL_ID, NO,
                     NUMBER, PHONE, RANGES, REFERRAL, YES, YES_NO, choices_of)
from .models import PaperField, PaperPage, PaperReading
from .pages import clean_box, turn_box

MESSAGES = {
    "claude_check": gettext_lazy("Claude is not sure of the reading."),
    "unclear": gettext_lazy("Claude could not read it."),
    "readings_differ": gettext_lazy("The two readings differ: %(a)s / %(b)s."),
    "second_missed": gettext_lazy("One of the two readings did not find it."),
    "pages_differ": gettext_lazy("Written differently on two pages: %(a)s / %(b)s."),
    "not_in_list": gettext_lazy("Not one of the choices: %(value)s."),
    "bad_date": gettext_lazy("Not a real date: %(value)s."),
    "date_range": gettext_lazy("The date %(value)s cannot be right here."),
    "bad_number": gettext_lazy("Not a number: %(value)s."),
    "out_of_range": gettext_lazy("%(value)s is unusual here (usually %(low)s to %(high)s)."),
    "id_birth": gettext_lazy("The national ID says the date of birth is %(value)s."),
    "id_gender": gettext_lazy("The national ID says: %(value)s."),
    "id_governorate": gettext_lazy("The national ID says the governorate is %(value)s."),
    "id_disagrees": gettext_lazy("It does not agree with the %(what)s read on the paper."),
    "from_id": gettext_lazy("Taken from the national ID."),
    "unknown_dentist": gettext_lazy("No dentist with this name in the system: %(value)s."),
    "unknown_condition": gettext_lazy("Not in the list of diseases: %(value)s."),
    "from_conditions": gettext_lazy("Diseases written that are not in the list."),
    "note": gettext_lazy("Claude's note: %(value)s"),
}
# Only said, without asking for a check.
INFO = {"from_id", "note"}


def explain(code, params):
    """One problem in the reader's own language."""
    params = dict(params or {})
    if code == "bad_id":
        try:
            parse_egyptian_national_id(params.get("value", ""))
        except ValidationError as error:
            return _("Not a valid national ID: %(error)s") % {"error": error.messages[0]}
        return _("Not a valid national ID.")
    if code == "bad_phone":
        try:
            validate_phone(params.get("value", ""), mobile_only=params.get("mobile") == "1")
        except ValidationError as error:
            return error.messages[0]
        return _("Not a valid mobile number.")
    if code == "bad_name":
        from apps.patients.forms import clean_arabic_name

        try:
            clean_arabic_name(params.get("value", ""))
        except forms.ValidationError as error:
            return error.messages[0]
        return _("Write the name in Arabic letters only, as on the ID.")
    if code == "id_gender":
        params["value"] = _("male") if params.get("value") == "M" else _("female")
    if code == "id_governorate":
        params["value"] = str(EGYPT_GOVERNORATES.get(params.get("value", ""), params.get("value", "")))
    if code == "id_disagrees":
        spec = BY_NAME.get(params.get("what", ""))
        params["what"] = str(spec.label) if spec else params.get("what", "")
    message = MESSAGES.get(code)
    if message is None:
        return code
    return str(message) % params if params else str(message)


# ------------------------------------------------------------------------------------------- one value
_ARABIC = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ة": "ه", "ى": "ي"})
_TITLES = re.compile(r"^(dr\.?|doctor|د\.?|دكتور|دكتوره|الدكتور)\s+", re.IGNORECASE)


def _words(text):
    return " ".join(normalize_digits(str(text or "")).translate(_ARABIC).lower().replace("ـ", "").split())


def _match(text, options):
    """The code of the option the text names (by its code or one of its words), else None."""
    wanted = _words(text)
    if not wanted:
        return None
    for code, words in options:
        if wanted == _words(code) or any(wanted == _words(word) for word in words if word):
            return code
    return None


def _date(text):
    text = normalize_digits(str(text or "")).strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d", "%Y/%m/%d", "%d/%m/%y", "%d-%m-%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def clean_value(spec, raw):
    """(the value as the form expects it, as text; [problems]) for one answer."""
    raw = " ".join(str(raw or "").split())
    if not raw:
        return "", []
    kind = spec.kind
    if kind == NAME:
        from apps.patients.forms import clean_arabic_name

        try:
            return clean_arabic_name(raw), []
        except forms.ValidationError:
            return raw, [("bad_name", {"value": raw})]
    if kind == NATIONAL_ID:
        digits = re.sub(r"\D", "", normalize_digits(raw))
        try:
            parse_egyptian_national_id(digits)
        except ValidationError:
            return digits or raw, [("bad_id", {"value": digits or raw})]
        return digits, []
    if kind == PHONE:
        value = normalize_phone(raw)
        mobile = spec.name == "phone_primary"
        try:
            validate_phone(value, mobile_only=mobile)
        except ValidationError:
            return value or raw, [("bad_phone", {"value": value or raw, "mobile": "1" if mobile else "0"})]
        return value, []
    if kind == DATE:
        day = _date(raw)
        if day is None:
            return raw, [("bad_date", {"value": raw})]
        earliest = date(1900, 1, 1) if spec.name == "birth_date" else date(1980, 1, 1)
        if not earliest <= day <= timezone.localdate():
            return day.strftime("%d/%m/%Y"), [("date_range", {"value": day.strftime("%d/%m/%Y")})]
        return day.strftime("%d/%m/%Y"), []
    if kind in (NUMBER, DECIMAL):
        text = normalize_digits(raw).replace(",", ".").replace("٫", ".")
        found = re.search(r"\d+(\.\d+)?", text)
        if found is None:
            return raw, [("bad_number", {"value": raw})]
        number = float(found.group())
        value = f"{number:.1f}" if kind == DECIMAL else str(int(round(number)))
        low, high = RANGES.get(spec.name, (None, None))
        if low is not None and not low <= number <= high:
            return value, [("out_of_range", {"value": value, "low": str(low), "high": str(high)})]
        return value, []
    if kind == YES_NO:
        word = _words(raw)
        if word in YES:
            return "yes", []
        if word in NO:
            return "no", []
        return raw, [("not_in_list", {"value": raw})]
    if kind in (CHOICE, REFERRAL):
        code = _match(raw, choices_of(spec))
        return (code, []) if code is not None else (raw, [("not_in_list", {"value": raw})])
    if kind == DENTIST:
        options = choices_of(spec)
        code = _match(raw, options)
        if code is None:
            bare = _TITLES.sub("", _words(raw))
            close = [code for code, words in options if bare and any(bare in _TITLES.sub("", _words(w)) for w in words)]
            code = close[0] if len(close) == 1 else None
        return (code, []) if code is not None else ("", [("unknown_dentist", {"value": raw})])
    if kind == CONDITIONS:
        options, codes, problems = choices_of(spec), [], []
        for item in re.split(r"[,،;\n]+", raw):
            if not item.strip():
                continue
            code = _match(item, options)
            if code is None:
                problems.append(("unknown_condition", {"value": item.strip()}))
            elif code not in codes:
                codes.append(code)
        return ",".join(codes), problems
    return raw, []


# ------------------------------------------------------------------------------------------- a whole file
def _turn_for(page, readings):
    first = next((r for r in readings if r.number == 1 and r.result), None) or next(
        (r for r in readings if r.result), None)
    return int(first.result.get("turn") or 0) % 360 if first is not None else 0


def settle_pages(paper):
    """After reading: each page's kind, its notes, and the picture turned upright. Returns {page id: turn applied}."""
    from .pages import turn_page

    turns = {}
    for page in paper.pages.prefetch_related("readings"):
        readings = [r for r in page.readings.all() if r.status == PaperReading.Status.DONE and r.result]
        if not readings:
            continue
        first = min(readings, key=lambda r: r.number)
        kinds = {r.result.get("page_kind") for r in readings}
        page.kind = first.result.get("page_kind") or PaperPage.Kind.OTHER
        if page.kind not in PaperPage.Kind.values:
            page.kind = PaperPage.Kind.OTHER
        notes = [first.result.get("page_notes") or ""]
        if len(kinds) > 1:
            notes.append("The two readings saw a different kind of page.")
        page.notes = " ".join(note for note in notes if note)[:300]
        page.save(update_fields=["kind", "notes"])
        turn = _turn_for(page, readings)
        if turn:
            turn_page(page, turn)
        turns[page.pk] = turn
        if page.kind == PaperPage.Kind.COVER and not paper.cover_number:
            number = (first.result.get("cover_file_number") or "").strip().upper()
            paper.cover_number = normalize_digits(number)[:30]
    type(paper).objects.filter(pk=paper.pk).update(cover_number=paper.cover_number)
    return turns


def _box(entry, page, turn):
    """Claude's box for a value, on the upright picture."""
    width, height = (page.height, page.width) if turn in (90, 270) else (page.width, page.height)
    box = clean_box(entry.get("box"), width, height)
    return turn_box(box, turn, width, height) if box and turn else box


def _rank(name, page, entry):
    """Which answer to take when a value is on several pages: its usual page, then the clearest, then the first."""
    best = BEST_PAGE.get(name, ())
    usual = best.index(page.kind) if page.kind in best else len(best)
    certainty = {"sure": 0, "check": 1, "unclear": 2}.get(entry.get("certainty"), 2)
    return usual, certainty, page.number


def build_fields(paper, turns=None):
    """Make the values to check (PaperField rows) from the readings of a file, and guess whose file it is."""
    turns = turns or {}
    paper.fields.all().delete()
    found = defaultdict(lambda: {1: [], 2: []})  # name → {reading number: [(page, entry)]}
    two = False
    for page in paper.pages.prefetch_related("readings"):
        for reading in page.readings.all():
            if reading.status != PaperReading.Status.DONE or not reading.result:
                continue
            two = two or reading.number == 2
            for entry in reading.result.get("fields", []):
                if entry.get("name") in BY_NAME:
                    found[entry["name"]][reading.number].append((page, entry))
    rows = {}
    for name in NAMES:
        if name not in found:
            continue
        spec = BY_NAME[name]
        firsts = sorted(found[name][1] or found[name][2], key=lambda item: _rank(name, *item))
        page, entry = firsts[0]
        certainty = entry.get("certainty") if entry.get("certainty") in ("sure", "check", "unclear") else "check"
        value, problems = clean_value(spec, entry.get("value"))
        if certainty == "unclear":
            value, problems = "", [("unclear", {})]
        elif certainty == "check":
            problems.insert(0, ("claude_check", {}))
        if not value and certainty != "unclear" and not problems:
            continue  # nothing written
        for other_page, other in firsts[1:]:
            other_value = clean_value(spec, other.get("value"))[0]
            if other_value and value and other_value != value:
                problems.append(("pages_differ", {"a": entry.get("written") or value,
                                                  "b": other.get("written") or other_value}))
                break
        second_value = ""
        if two and not found[name][1]:
            problems.append(("second_missed", {}))
        elif two:
            seconds = sorted(found[name][2], key=lambda item: _rank(name, *item))
            if not seconds:
                if value:
                    problems.append(("second_missed", {}))
            else:
                second = seconds[0][1]
                second_value = "" if second.get("certainty") == "unclear" else clean_value(spec, second.get("value"))[0]
                if second_value != value:
                    problems.append(("readings_differ", {"a": entry.get("written") or value or "?",
                                                         "b": second.get("written") or second_value or "?"}))
                elif second.get("certainty") != "sure" and certainty == "sure":
                    problems.append(("claude_check", {}))
        if entry.get("note"):
            problems.append(("note", {"value": str(entry["note"])[:200]}))
        rows[name] = PaperField(
            file=paper, page=page, name=name, value=value, written=str(entry.get("written") or "")[:500],
            other=second_value if second_value != value else "", certainty=certainty,
            problems=problems, note=str(entry.get("note") or "")[:300], box=_box(entry, page, turns.get(page.pk, 0)))
    _national_id(paper, rows)
    _other_diseases(paper, rows)
    for row in rows.values():
        row.certainty = _certainty(row)
    PaperField.objects.bulk_create(rows.values())
    suggest_patient(paper, rows)
    return rows


def _certainty(row):
    if row.certainty == PaperField.Certainty.UNCLEAR and not row.value:
        return PaperField.Certainty.UNCLEAR
    if any(code not in INFO for code, _params in row.problems):
        return PaperField.Certainty.CHECK
    return PaperField.Certainty.SURE


def _national_id(paper, rows):
    """What the national ID says (date of birth, gender, governorate) against what the paper says; it fills them
    when they are not written."""
    row = rows.get("national_id")
    if row is None or not row.value:
        return
    try:
        data = parse_egyptian_national_id(row.value)
    except ValidationError:
        return
    told = {"birth_date": data["birth_date"].strftime("%d/%m/%Y"), "gender": data["gender"],
            "governorate": data["governorate_code"]}
    codes = {"birth_date": "id_birth", "gender": "id_gender", "governorate": "id_governorate"}
    for name, value in told.items():
        if not value:
            continue
        other = rows.get(name)
        if other is None or not other.value:
            rows[name] = PaperField(file=paper, page=row.page, name=name, value=value, certainty="sure",
                                    problems=[("from_id", {})], box=row.box)
        elif other.value != value:
            other.problems.append((codes[name], {"value": value}))
            row.problems.append(("id_disagrees", {"what": name}))


def _other_diseases(paper, rows):
    """Diseases written that are not in the list go to "other disease" (when nothing else is written there)."""
    row = rows.get("conditions")
    if row is None:
        return
    unknown = [params["value"] for code, params in row.problems if code == "unknown_condition"]
    if unknown and "other_condition" not in rows:
        rows["other_condition"] = PaperField(file=paper, page=row.page, name="other_condition",
                                             value="، ".join(unknown)[:200], written=row.written,
                                             certainty="check", problems=[("from_conditions", {})], box=row.box)


def suggest_patient(paper, rows=None):
    """Whose file this seems to be: the cover sheet's number, else the national ID, else a mobile."""
    from apps.patients.models import Patient

    if rows is None:
        rows = {row.name: row for row in paper.fields.all()}
    patients = Patient.objects.filter(branch=paper.branch)
    found, reason = None, ""
    if paper.cover_number:
        found, reason = patients.filter(file_number__iexact=paper.cover_number).first(), "cover"
    if found is None and rows.get("national_id") and rows["national_id"].value:
        found, reason = patients.filter(national_id=rows["national_id"].value).first(), "national_id"
    if found is None:
        phones = [rows[name].value for name in ("phone_primary", "phone_secondary") if rows.get(name) and rows[name].value]
        if phones:
            found, reason = patients.filter(Q(phone_primary__in=phones) | Q(phone_secondary__in=phones)).first(), "phone"
    paper.suggested = found
    paper.suggested_reason = reason if found is not None else ""
    type(paper).objects.filter(pk=paper.pk).update(suggested=found, suggested_reason=paper.suggested_reason)
    return found


SUGGESTED_BECAUSE = {
    "cover": gettext_lazy("the file number on the cover sheet"),
    "national_id": gettext_lazy("the same national ID"),
    "phone": gettext_lazy("the same mobile number"),
}
