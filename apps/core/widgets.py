"""Form widgets that work the same in every browser and language:
dates typed or picked as dd/mm/yyyy, times chosen from a list in fixed steps
(00, 15, 30, 45 for appointments), and a search-as-you-type box."""

from datetime import datetime, time

from django import forms
from django.utils import formats, timezone

from .utils import normalize_digits

DATE_FORMAT = "%d/%m/%Y"


class DateInput(forms.DateInput):
    """A text box for dd/mm/yyyy with a calendar (flatpickr). Old dates can be typed directly."""

    input_type = "text"

    def __init__(self, attrs=None):
        attrs = {"class": "js-date", "placeholder": "dd/mm/yyyy", "autocomplete": "off", "dir": "ltr", **(attrs or {})}
        super().__init__(attrs=attrs, format=DATE_FORMAT)

    def value_from_datadict(self, data, files, name):
        return normalize_digits(super().value_from_datadict(data, files, name))


def time_label(value):
    return formats.time_format(value, "g:i A")


def time_choices(step=15, start=time(0), end=time(23, 59)):
    first = start.hour * 60 + start.minute
    last = end.hour * 60 + end.minute
    first += -first % step
    return [(f"{m // 60:02d}:{m % 60:02d}", time_label(time(m // 60, m % 60))) for m in range(first, last + 1, step)]


class TimeSelect(forms.Select):
    """Times from a list in ``step`` minutes (9:00, 9:15, 9:30...). A saved time that is
    not on the list (e.g. 10:07) is still shown so editing never changes it silently."""

    def __init__(self, attrs=None, step=15, start=time(0), end=time(23, 59)):
        self.step, self.start, self.end = step, start, end
        super().__init__(attrs=attrs)

    def format_value(self, value):
        if isinstance(value, (time, datetime)):
            value = value.strftime("%H:%M")
        return super().format_value(value)

    def get_context(self, name, value, attrs):
        choices = [("", "—")] + time_choices(self.step, self.start, self.end)
        current = self.format_value(value)
        current = current[0] if current else ""
        if current and current not in dict(choices):
            try:
                hour, minute = (int(part) for part in current.split(":")[:2])
                choices.append((current, time_label(time(hour, minute))))
                choices.sort(key=lambda c: c[0] or "")
            except ValueError:
                pass
        self.choices = choices
        return super().get_context(name, value, attrs)


class DateTimeSplitWidget(forms.MultiWidget):
    """A dd/mm/yyyy date box next to a list of times. Posts one value, "dd/mm/yyyy HH:MM",
    so it works with an ordinary DateTimeField."""

    template_name = "core_widgets/datetime_split.html"

    def __init__(self, attrs=None, step=5, start=time(0), end=time(23, 59)):
        widgets = [DateInput(attrs={"class": "form-control js-date"}),
                   TimeSelect(attrs={"class": "form-select"}, step=step, start=start, end=end)]
        super().__init__(widgets, attrs)

    def decompress(self, value):
        if isinstance(value, datetime):
            if timezone.is_aware(value):
                value = timezone.localtime(value)
            return [value.date(), value.time().replace(second=0, microsecond=0)]
        if isinstance(value, str) and value:
            date_part, _sep, time_part = value.replace("T", " ").partition(" ")
            return [date_part, time_part[:5]]
        return [None, None]

    def value_from_datadict(self, data, files, name):
        if f"{name}_0" not in data and name in data:
            return normalize_digits(data.get(name))  # one value, e.g. "25/09/2026 10:30" or ISO
        date_value, time_value = super().value_from_datadict(data, files, name)
        date_value, time_value = (date_value or "").strip(), (time_value or "").strip()
        if not date_value:
            return ""
        return f"{date_value} {time_value or '00:00'}"


class AutocompleteInput(forms.TextInput):
    """Suggestions appear while typing; choosing one fills the box with its value."""

    def __init__(self, url, attrs=None):
        self.url = url
        super().__init__(attrs={"autocomplete": "off", **(attrs or {})})

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context["widget"]["attrs"]["data-autocomplete-url"] = str(self.url)
        return context


class WeekdaysWidget(forms.CheckboxSelectMultiple):
    """Ticks for the days of the week, kept in a text field as "3,4" (Thursday, Friday)."""

    def __init__(self, attrs=None):
        from .models import UserProfile

        super().__init__(attrs, choices=UserProfile.WEEKDAYS)

    def format_value(self, value):
        if isinstance(value, str):
            value = [day for day in value.split(",") if day]
        return super().format_value(value)

    def value_from_datadict(self, data, files, name):
        days = data.getlist(name) if hasattr(data, "getlist") else data.get(name) or []
        return ",".join(sorted(days, key=lambda day: (int(day) - 5) % 7 if day.isdigit() else 9))


class DatalistInput(forms.TextInput):
    """A text box with suggestions to pick from (free text is still allowed)."""

    template_name = "core_widgets/datalist.html"

    def __init__(self, options=(), attrs=None):
        self.options = options
        super().__init__(attrs=attrs)

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        options = self.options() if callable(self.options) else self.options
        context["widget"]["options"] = list(options)
        context["widget"]["attrs"]["list"] = f"{context['widget']['attrs'].get('id', name)}_list"
        return context
