from django import forms
from django.utils.translation import gettext_lazy as _

from apps.charting.forms import HISTORY_FIELDSETS, MedicalHistoryForm
from apps.core.forms import StyledForm, StyledModelForm
from apps.dentists.forms import DentistChoiceField
from apps.patients.forms import PatientForm, PatientLookupField

from .models import PaperPage, PaperSettings

PAPER_UPLOAD_MB = 120  # one scanned file (a PDF of many pages, or the photos of its pages)


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    """Several files chosen at once (a stack of scanned files, or the photos of one file's pages)."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput(attrs={"accept": "application/pdf,image/*"}))
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single = super().clean
        if isinstance(data, (list, tuple)):
            return [single(item, initial) for item in data]
        return [single(data, initial)] if data else []


class UploadForm(StyledForm):
    files = MultipleFileField(
        label=_("Scanned files"),
        help_text=_("One PDF for each patient (choose many at once), or the photos of the pages of one file."))
    mode = forms.ChoiceField(label=_("Read"), choices=PaperSettings.Mode.choices, widget=forms.RadioSelect)

    def clean_files(self):
        from apps.core.uploads import is_blocked, looks_right

        files = self.cleaned_data.get("files") or []
        if not files:
            raise forms.ValidationError(_("Choose at least one file."))
        if len(files) > 200:
            raise forms.ValidationError(_("At most 200 files at once."))
        for upload in files:
            name = upload.name.lower()
            if is_blocked(upload) or not name.endswith((".pdf", ".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff",
                                                        ".bmp")):
                raise forms.ValidationError(_("%(name)s: only PDF files or photos.") % {"name": upload.name})
            if not looks_right(upload):
                raise forms.ValidationError(_("%(name)s is not a real PDF or picture.") % {"name": upload.name})
            if upload.size > PAPER_UPLOAD_MB * 1024 * 1024:
                raise forms.ValidationError(_("%(name)s is too large (at most %(mb)s MB).")
                                            % {"name": upload.name, "mb": PAPER_UPLOAD_MB})
        return files


class TargetForm(StyledForm):
    """Whose file the paper file goes into."""

    NEW, EXISTING = "new", "existing"
    target = forms.ChoiceField(label=_("Save into"), widget=forms.RadioSelect, choices=[
        (NEW, _("A new patient file")), (EXISTING, _("A patient already registered"))])
    patient = PatientLookupField(label=_("patient"), required=False)

    def clean(self):
        data = super().clean()
        if data.get("target") == self.EXISTING and not data.get("patient"):
            self.add_error("patient", _("Choose the patient."))
        return data


class PaperPatientForm(PatientForm):
    """The patient's data read from the paper, checked with the same rules as the registration form."""

    LEFT_OUT = ("id_front", "id_back", "relative_lookup", "relative_relation", "brought_by", "assigned_dentist",
                "status", "out_reason", "out_notes", "medical_conditions", "preferred_phone")
    fieldsets = [
        (_("Personal data"), ["full_name", "id_type", "national_id", "birth_date", "gender", "marital_status",
                              "occupation"]),
        (_("Contact"), ["phone_primary", "phone_secondary", "governorate", "city", "address"]),
        (_("Teeth and medical notes (as told by the patient)"), ["missing_teeth", "missing_teeth_notes",
                                                                  "medical_notes"]),
        (_("Who referred the patient"), ["referral_source", "referred_by_lookup", "referral_notes"]),
        (_("The file"), ["registered_on", "notes"]),
    ]
    folded = ()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in self.LEFT_OUT:
            self.fields.pop(name, None)
        self.fields["referral_source"].required = False
        self.fields["registered_on"].help_text = _("The date the paper file was opened.")
        for name in ("birth_date", "gender", "governorate"):
            self.fields[name].help_text = ""


class PaperHistoryForm(MedicalHistoryForm):
    """The medical and dental history read from the paper chart."""

    examined_by = DentistChoiceField(label=_("taken by (the dentist)"), required=False)
    fieldsets = [(_("The history on the paper"), ["exam_date", "examined_by"]), *HISTORY_FIELDSETS]

    class Meta(MedicalHistoryForm.Meta):
        fields = ["exam_date", "examined_by", *MedicalHistoryForm.Meta.fields]

    def __init__(self, *args, **kwargs):
        kwargs["dentist"] = True
        super().__init__(*args, **kwargs)
        self.fields["exam_date"].required = False
        self.fields["exam_date"].label = _("date the history was taken")
        self.fields["exam_date"].help_text = _("Empty = the date the file was opened.")


class PageForm(forms.Form):
    kind = forms.ChoiceField(choices=PaperPage.Kind.choices, required=False)
    turn = forms.ChoiceField(choices=[("", ""), ("left", "left"), ("right", "right")], required=False)


class CoversForm(StyledForm):
    patient = PatientLookupField(label=_("one patient"), required=False)
    registered_from = forms.DateField(label=_("or the patients whose file was opened from"), required=False)
    registered_to = forms.DateField(label=_("to"), required=False)
    blank = forms.IntegerField(label=_("and blank cover sheets for new files"), required=False, min_value=0,
                               max_value=100, help_text=_("The file number is written by hand on them."))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("registered_from", "registered_to", "blank"):
            self.fields[name].col = "col-md-4"


class PaperSettingsForm(StyledModelForm):
    class Meta:
        model = PaperSettings
        fields = ["enabled", "model", "effort", "two_readings", "default_mode", "monthly_limit"]
        widgets = {"default_mode": forms.RadioSelect, "model": forms.RadioSelect, "effort": forms.RadioSelect}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("model", "effort", "default_mode"):
            self.fields[name].col = "col-md-6 col-xl-4"
        self.fields["monthly_limit"].col = "col-md-4"
        self.fields["monthly_limit"].widget.attrs.update(min=0, step="10")
