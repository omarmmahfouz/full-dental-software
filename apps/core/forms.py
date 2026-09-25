from django import forms
from django.core.exceptions import ValidationError
from django.conf import settings
from django.utils.text import capfirst
from django.utils.translation import gettext_lazy as _

from .roles import users_with_role
from .utils import normalize_digits, normalize_phone, validate_phone


class DateInput(forms.DateInput):
    input_type = "date"

    def __init__(self, attrs=None):
        super().__init__(attrs=attrs, format="%Y-%m-%d")


class TimeInput(forms.TimeInput):
    input_type = "time"

    def __init__(self, attrs=None):
        super().__init__(attrs=attrs, format="%H:%M")


class DateTimeInput(forms.DateTimeInput):
    input_type = "datetime-local"

    def __init__(self, attrs=None):
        super().__init__(attrs=attrs, format="%Y-%m-%dT%H:%M")


class BootstrapFormMixin:
    """Adds Bootstrap classes to every widget and date/time pickers to date fields."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if field.label:
                field.label = capfirst(field.label)
            widget = field.widget
            if isinstance(field, forms.DateTimeField) and not isinstance(widget, forms.HiddenInput):
                field.widget = widget = DateTimeInput(attrs=widget.attrs)
            elif isinstance(field, forms.DateField) and not isinstance(widget, forms.HiddenInput):
                field.widget = widget = DateInput(attrs=widget.attrs)
            elif isinstance(field, forms.TimeField) and not isinstance(widget, forms.HiddenInput):
                field.widget = widget = TimeInput(attrs=widget.attrs)
            if isinstance(widget, (forms.CheckboxSelectMultiple, forms.RadioSelect)):
                css = ""
            elif isinstance(widget, forms.CheckboxInput):
                css = "form-check-input"
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                css = "form-select"
            else:
                css = "form-control"
            if isinstance(widget, forms.Textarea) and str(widget.attrs.get("rows")) == "10":
                widget.attrs["rows"] = 3  # Django's default (10) is far too tall for notes
            if css:
                widget.attrs["class"] = (widget.attrs.get("class", "") + " " + css).strip()


class FieldsetsMixin:
    """Group long forms into titled sections: ``fieldsets = [(title, [names])]``."""

    fieldsets = ()

    def bound_fieldsets(self):
        used, sections = set(), []
        for title, names in self.fieldsets:
            fields = [self[name] for name in names if name in self.fields and not self[name].is_hidden]
            used.update(names)
            if fields:
                sections.append((title, fields))
        rest = [field for field in self.visible_fields() if field.name not in used]
        if rest:
            sections.append(("", rest))
        return sections


class StyledForm(FieldsetsMixin, BootstrapFormMixin, forms.Form):
    pass


class StyledModelForm(FieldsetsMixin, BootstrapFormMixin, forms.ModelForm):
    pass


class UserChoiceField(forms.ModelChoiceField):
    """A drop-down of active staff holding one of ``roles``."""

    def __init__(self, roles, **kwargs):
        super().__init__(queryset=users_with_role(*roles), **kwargs)


def clean_phone_value(value, mobile_only=True):
    value = normalize_phone(value)
    if value:
        validate_phone(value, mobile_only=mobile_only)
    return value


def clean_digits_value(value):
    return normalize_digits(value or "").strip()


def validate_upload(file):
    """Accept images and PDFs up to MAX_UPLOAD_SIZE_MB."""
    if not file:
        return file
    limit = settings.MAX_UPLOAD_SIZE_MB
    if file.size > limit * 1024 * 1024:
        raise ValidationError(_("The file is too large (maximum %(size)s MB).") % {"size": limit})
    name = file.name.lower()
    if not name.endswith((".jpg", ".jpeg", ".png", ".webp", ".heic", ".pdf", ".tif", ".tiff", ".bmp")):
        raise ValidationError(_("Only images or PDF files can be uploaded."))
    return file


class DateRangeForm(StyledForm):
    date_from = forms.DateField(label=_("From"), required=False)
    date_to = forms.DateField(label=_("To"), required=False)
