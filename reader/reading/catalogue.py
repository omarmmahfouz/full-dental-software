"""The values to read, as the dental system describes them in its lists file: each value's name, kind, labels in
English and Arabic, its part of the file, whether it is needed for a new patient, its choices and its usual range.
The reader builds its forms and Claude's instructions from it, so the two programs always agree."""

from dataclasses import dataclass, field

from django.utils.translation import get_language

# Kinds of values: how an answer is cleaned and checked (checks.py) and which box the review page shows.
TEXT, NAME, NATIONAL_ID, PHONE, DATE, CHOICE, YES_NO, NUMBER, DECIMAL, CONDITIONS, DENTIST, REFERRAL = (
    "text", "name", "national_id", "phone", "date", "choice", "yes_no", "number", "decimal", "conditions", "dentist",
    "referral")
LISTED = (CHOICE, REFERRAL, CONDITIONS, DENTIST)
PATIENT, HISTORY = "patient", "history"


@dataclass
class Spec:
    name: str
    part: str
    kind: str
    label_en: str
    label_ar: str = ""
    section_en: str = ""
    section_ar: str = ""
    required: bool = False
    long: bool = False
    choices: list = field(default_factory=list)  # [(code, english, arabic)]
    range: tuple = None

    @property
    def label(self):
        return (self.label_ar or self.label_en) if _arabic() else self.label_en

    @property
    def section(self):
        return (self.section_ar or self.section_en) if _arabic() else self.section_en

    def options(self):
        """[(code, [words...])] the paper may use for each choice."""
        return [(code, [word for word in (code, english, arabic) if word]) for code, english, arabic in self.choices]

    def choice_label(self, code):
        for value, english, arabic in self.choices:
            if value == code:
                return (arabic or english) if _arabic() else (english or arabic)
        return code


def _arabic():
    return (get_language() or "").startswith("ar")


_cache = {}


def specs(lists=None):
    """[Spec] in the order of the review page, from the lists file brought in (empty before)."""
    from .models import SystemLists

    lists = lists or SystemLists.get()
    key = (lists.pk, lists.imported_at)
    if key not in _cache:
        rows = []
        for item in lists.data.get("fields", []):
            rows.append(Spec(
                name=item["name"], part=item.get("part", PATIENT), kind=item.get("kind", TEXT),
                label_en=item.get("label_en", item["name"]), label_ar=item.get("label_ar", ""),
                section_en=item.get("section_en", ""), section_ar=item.get("section_ar", ""),
                required=bool(item.get("required")), long=bool(item.get("long")),
                choices=[tuple(choice) for choice in item.get("choices", [])],
                range=tuple(item["range"]) if item.get("range") else None))
        _cache.clear()
        _cache[key] = rows
    return _cache[key]


def by_name(lists=None):
    return {spec.name: spec for spec in specs(lists)}
