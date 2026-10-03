"""The Paper Reader's forms. The review forms are built from the lists file (the dental system's own fields, labels
and choices), with the clinic's rules; the dental system checks everything again when it imports."""

from decimal import Decimal, InvalidOperation

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from .catalogue import (CHOICE, CONDITIONS, DATE, DECIMAL, DENTIST, NAME, NATIONAL_ID, NUMBER, PATIENT, PHONE, REFERRAL,
                        YES_NO, specs)
from .models import KnownPatient, PaperPage, ReaderSettings
from .rules import clean_arabic_name, normalize_digits, normalize_phone, parse_national_id, validate_phone

DATE_FORMATS = ["%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"]
UPLOAD_MB = 120


class Styled:
    """Bootstrap classes on every box, and the sections of a long form (``fieldsets``)."""

    fieldsets = ()

    def style(self):
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, (forms.CheckboxSelectMultiple, forms.RadioSelect)):
                continue
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs["class"] = "form-check-input"
            elif isinstance(widget, forms.Select):
                widget.attrs["class"] = "form-select"
            else:
                widget.attrs["class"] = "form-control"
            if isinstance(widget, forms.Textarea):
                widget.attrs["rows"] = 2

    def bound_fieldsets(self):
        used, sections = set(), []
        for title, names in self.fieldsets:
            fields = [self[name] for name in names if name in self.fields]
            used.update(names)
            if fields:
                sections.append((title, fields))
        rest = [self[name] for name in self.fields if name not in used and not self[name].is_hidden]
        if rest:
            sections.append(("", rest))
        return sections


class StyledForm(Styled, forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.style()


class StyledModelForm(Styled, forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.style()


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput(attrs={"accept": "application/pdf,image/*"}))
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single = super().clean
        if isinstance(data, (list, tuple)):
            return [single(item, initial) for item in data]
        return [single(data, initial)] if data else []


SIGNATURES = {
    ".pdf": lambda head: b"%PDF" in head[:1024],
    ".jpg": lambda head: head.startswith(b"\xff\xd8\xff"),
    ".jpeg": lambda head: head.startswith(b"\xff\xd8\xff"),
    ".png": lambda head: head.startswith(b"\x89PNG\r\n\x1a\n"),
    ".webp": lambda head: head[:4] == b"RIFF" and head[8:12] == b"WEBP",
    ".tif": lambda head: head[:4] in (b"II*\x00", b"MM\x00*"),
    ".tiff": lambda head: head[:4] in (b"II*\x00", b"MM\x00*"),
    ".bmp": lambda head: head[:2] == b"BM",
}


def looks_right(upload):
    """True when a PDF or a picture holds what its name says (a program renamed .pdf is refused)."""
    name = upload.name.lower()
    check = next((test for ext, test in SIGNATURES.items() if name.endswith(ext)), None)
    if check is None:
        return False
    upload.seek(0)
    head = upload.read(1024)
    upload.seek(0)
    return check(head)


class UploadForm(StyledForm):
    files = MultipleFileField(
        label=_("Scanned files"),
        help_text=_("One PDF for each patient (choose many at once), or the photos of the pages of one file."))
    mode = forms.ChoiceField(label=_("Read"), choices=ReaderSettings.Mode.choices, widget=forms.RadioSelect)

    def clean_files(self):
        files = self.cleaned_data.get("files") or []
        if not files:
            raise ValidationError(_("Choose at least one file."))
        if len(files) > 200:
            raise ValidationError(_("At most 200 files at once."))
        for upload in files:
            if not looks_right(upload):
                raise ValidationError(_("%(name)s is not a real PDF or picture.") % {"name": upload.name})
            if upload.size > UPLOAD_MB * 1024 * 1024:
                raise ValidationError(_("%(name)s is too large (at most %(mb)s MB).")
                                      % {"name": upload.name, "mb": UPLOAD_MB})
        return files


# ------------------------------------------------------------------------------------------- the review
class TargetForm(StyledForm):
    """Whose file the paper file goes into in the dental system."""

    NEW, EXISTING = "new", "existing"
    target = forms.ChoiceField(label=_("Save into"), widget=forms.RadioSelect, choices=[
        (NEW, _("A new patient file")), (EXISTING, _("A patient already registered"))])
    file_number = forms.CharField(label=_("file number"), required=False, max_length=20,
                                  help_text=_("Type the file number or choose from the list (name or mobile)."))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["file_number"].widget.attrs.update(list="known-patients", autocomplete="off", dir="ltr")

    def clean_file_number(self):
        value = normalize_digits(self.cleaned_data.get("file_number") or "").split(" — ")[0].strip().upper()
        return value

    def clean(self):
        data = super().clean()
        if data.get("target") == self.EXISTING:
            number = data.get("file_number")
            if not number:
                self.add_error("file_number", _("Choose the patient."))
            elif not KnownPatient.objects.filter(file_number__iexact=number).exists():
                self.add_error("file_number", _("No registered patient with this file number in the lists from the "
                                                "system. Bring in new lists if the patient is new there."))
        return data


def _date_field(spec):
    return forms.DateField(input_formats=DATE_FORMATS, widget=forms.TextInput(attrs={
        "placeholder": "dd/mm/yyyy", "dir": "ltr", "autocomplete": "off"}))


def make_field(spec):
    """The box of one value on the review page."""
    kind = spec.kind
    if kind == DATE:
        field = _date_field(spec)
    elif kind == YES_NO:
        field = forms.BooleanField()
    elif kind == NUMBER:
        low, high = spec.range or (None, None)
        field = forms.IntegerField(min_value=low, max_value=high)
        field.widget.attrs["inputmode"] = "numeric"
    elif kind == DECIMAL:
        field = forms.DecimalField(max_digits=5, decimal_places=1)
        field.widget.attrs["inputmode"] = "decimal"
    elif kind == CONDITIONS:
        field = forms.MultipleChoiceField(widget=forms.CheckboxSelectMultiple, choices=[
            (code, spec.choice_label(code)) for code, *_rest in spec.choices])
    elif kind in (CHOICE, REFERRAL, DENTIST):
        field = forms.ChoiceField(choices=[("", "—")] + [(code, spec.choice_label(code)) for code, *_rest in
                                                          spec.choices])
    elif spec.long:
        field = forms.CharField(widget=forms.Textarea)
    else:
        field = forms.CharField(max_length=255)
    field.label = spec.label
    field.required = False
    field.spec = spec
    if kind in (NAME,):
        field.widget.attrs.update(dir="rtl", lang="ar")
    if kind in (NATIONAL_ID, PHONE):
        field.widget.attrs.update(dir="ltr", inputmode="numeric")
    return field


class ValuesForm(StyledForm):
    """The values of one part of the file (the patient's data, or the history), built from the lists file."""

    def __init__(self, *args, part=PATIENT, new_patient=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.part, self.new_patient = part, new_patient
        sections = {}
        for spec in specs():
            if spec.part != part:
                continue
            self.fields[spec.name] = make_field(spec)
            if new_patient and spec.required and part == PATIENT:
                self.fields[spec.name].required = True
            sections.setdefault(spec.section, []).append(spec.name)
        self.fieldsets = list(sections.items())
        self.style()
        for field in self.fields.values():
            if isinstance(field.widget, forms.Textarea) or field.spec.kind == CONDITIONS:
                field.col = "col-12"
            else:
                field.col = "col-md-6 col-xl-4"

    def clean(self):
        data = super().clean()
        for name, field in self.fields.items():
            value = data.get(name)
            if value in (None, "", [], False):
                continue
            kind = field.spec.kind
            try:
                if kind == NAME:
                    data[name] = clean_arabic_name(value)
                elif kind == NATIONAL_ID:
                    data[name] = normalize_digits(value).replace(" ", "")
                    parse_national_id(data[name])
                elif kind == PHONE:
                    data[name] = normalize_phone(value)
                    validate_phone(data[name], mobile_only=name == "phone_primary")
            except ValidationError as error:
                self.add_error(name, error)
        return data

    def values(self):
        """{name: value as text} of the cleaned values (the form of the package)."""
        out = {}
        for name, field in self.fields.items():
            value = self.cleaned_data.get(name)
            if value in (None, "", [], False):
                continue
            kind = field.spec.kind
            if kind == DATE:
                out[name] = value.strftime("%d/%m/%Y")
            elif kind == YES_NO:
                out[name] = "yes"
            elif kind == CONDITIONS:
                out[name] = ",".join(value)
            elif kind == DECIMAL:
                try:
                    out[name] = f"{Decimal(value):.1f}"
                except InvalidOperation:
                    out[name] = str(value)
            else:
                out[name] = str(value)
        return out


def initial_values(paper, part):
    """The values read, as the review form shows them."""
    from .catalogue import by_name

    known, out = by_name(), {}
    for row in paper.fields.all():
        spec = known.get(row.name)
        if spec is None or spec.part != part or not row.value:
            continue
        if spec.kind == CONDITIONS:
            out[row.name] = [code for code in row.value.split(",") if code]
        elif spec.kind == YES_NO:
            out[row.name] = row.value == "yes"
        else:
            out[row.name] = row.value
    return out


class PageForm(forms.Form):
    kind = forms.ChoiceField(choices=PaperPage.Kind.choices, required=False)
    turn = forms.ChoiceField(choices=[("", ""), ("left", "left"), ("right", "right")], required=False)


# ------------------------------------------------------------------------------------------- settings and people
class SettingsForm(StyledModelForm):
    class Meta:
        model = ReaderSettings
        fields = ["enabled", "model", "effort", "two_readings", "default_mode", "monthly_limit"]
        widgets = {"default_mode": forms.RadioSelect, "model": forms.RadioSelect, "effort": forms.RadioSelect}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("model", "effort", "default_mode"):
            self.fields[name].col = "col-md-6 col-xl-4"
        self.fields["monthly_limit"].col = "col-md-4"


class ListsForm(StyledForm):
    lists = forms.FileField(label=_("The lists file from the dental system"),
                            help_text=_("In the dental system: Patients → Old paper files → Lists for the reader."))


class PersonForm(StyledForm):
    username = forms.CharField(label=_("username"), max_length=150)
    first_name = forms.CharField(label=_("name"), max_length=150)
    password = forms.CharField(label=_("password"), widget=forms.PasswordInput, required=False,
                               help_text=_("Leave empty to keep the password."))
    admin = forms.BooleanField(label=_("in charge (settings, lists and people)"), required=False)
    active = forms.BooleanField(label=_("can log in"), required=False, initial=True)

    def __init__(self, *args, person=None, **kwargs):
        self.person = person
        super().__init__(*args, **kwargs)
        if person is None:
            self.fields["password"].required = True
            self.fields["password"].help_text = ""

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        others = get_user_model().objects.filter(username__iexact=username)
        if self.person is not None:
            others = others.exclude(pk=self.person.pk)
        if others.exists():
            raise ValidationError(_("This username is taken."))
        return username

    def clean_password(self):
        password = self.cleaned_data.get("password")
        if password:
            validate_password(password)
        return password


class OwnerForm(StyledForm):
    """The first person (in charge), made on the first run."""

    username = forms.CharField(label=_("username"), max_length=150)
    first_name = forms.CharField(label=_("name"), max_length=150)
    password = forms.CharField(label=_("password"), widget=forms.PasswordInput)
    again = forms.CharField(label=_("the password again"), widget=forms.PasswordInput)

    def clean(self):
        data = super().clean()
        if data.get("password") and data.get("password") != data.get("again"):
            self.add_error("again", _("The two passwords are not the same."))
        elif data.get("password"):
            try:
                validate_password(data["password"])
            except ValidationError as error:
                self.add_error("password", error)
        return data
