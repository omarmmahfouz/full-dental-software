from django import forms
from django.utils.translation import gettext_lazy as _

from apps.charting.forms import HISTORY_FIELDSETS, MedicalHistoryForm
from apps.core.forms import StyledForm
from apps.dentists.forms import DentistChoiceField
from apps.patients.forms import PatientForm, PatientLookupField

PACKAGE_MB = 1000  # one package of the Paper Reader (the scans of many files)


class PackageForm(StyledForm):
    package = forms.FileField(
        label=_("Package from the Paper Reader"),
        help_text=_("The .zip file made by the Paper Reader (Send to the dental system)."))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["package"].widget.attrs["accept"] = ".zip,application/zip"

    def clean_package(self):
        package = self.cleaned_data["package"]
        package.seek(0)
        if not package.name.lower().endswith(".zip") or package.read(4) != b"PK\x03\x04":
            raise forms.ValidationError(_("This is not a package of the Paper Reader (a .zip file)."))
        package.seek(0)
        if package.size > PACKAGE_MB * 1024 * 1024:
            raise forms.ValidationError(_("The package is too large (at most %(mb)s MB): make smaller packages in "
                                          "the reader.") % {"mb": PACKAGE_MB})
        return package


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
