from django import forms
from django.utils.translation import gettext_lazy as _

from apps.charting.teeth import format_teeth, parse_surfaces, parse_teeth
from apps.core.forms import StyledForm, StyledModelForm
from apps.core.roles import FRONT_DESK, has_role
from apps.dentists.forms import DentistChoiceField
from apps.dentists.models import Dentist
from apps.patients.access import visible_patients
from apps.patients.forms import PatientLookupField

from .models import ChartEffect, Lab, LabRequest, LabWorkType, TreatmentStep, TreatmentStepType


class _PatientScopedForm(StyledModelForm):
    """Adds a patient box limited to the patients the user may see."""

    def __init__(self, *args, user=None, patient=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        self.fields["patient_lookup"].initial = patient.file_number if patient else None
        if patient:
            self.fields["patient_lookup"].help_text = str(patient)

    def clean_patient_lookup(self):
        patient = self.cleaned_data["patient_lookup"]
        if not visible_patients(self.user).filter(pk=patient.pk).exists():
            raise forms.ValidationError(_("This patient is not one of your patients."))
        return patient


class TreatmentStepForm(_PatientScopedForm):
    """One line of the treatment log (date, treatment, operator, supervisor, next visit)."""

    patient_lookup = PatientLookupField(label=_("patient"))
    operator = DentistChoiceField(label=_("operator"), required=False)
    assistant = DentistChoiceField(label=_("assistant"), required=False)
    supervisor = DentistChoiceField(kinds=(Dentist.Kind.SUPERVISOR,), label=_("supervisor"), required=False)
    update_chart = forms.BooleanField(
        label=_("Update the dental chart for these teeth"), required=False, initial=True,
        help_text=_("The changes are listed below before you save."),
    )

    fieldsets = [
        ("", ["patient_lookup", "performed_at", "step_type", "notes", "teeth", "surfaces", "material"]),
        ("", ["operator", "assistant", "supervisor", "next_visit", "update_chart"]),
    ]

    class Meta:
        model = TreatmentStep
        fields = ["performed_at", "step_type", "teeth", "surfaces", "material", "operator", "assistant",
                  "supervisor", "notes", "next_visit"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["step_type"].queryset = TreatmentStepType.objects.filter(is_active=True)
        self.fields["step_type"].label = _("Treatment done")
        self.fields["notes"].label = _("Notes")
        self.fields["notes"].widget.attrs.update({"rows": 2, "placeholder": _("anything worth knowing about this visit")})
        self.fields["teeth"].widget.attrs.update({"data-digits": "1", "autocomplete": "off"})
        for name in ("patient_lookup", "performed_at", "step_type", "teeth", "surfaces", "material",
                     "operator", "assistant", "supervisor"):
            self.fields[name].col = "col-md-4"
        self.fields["notes"].col = "col-12"
        self.fields["next_visit"].col = "col-md-8"
        self.fields["update_chart"].col = "col-12"

    def clean_teeth(self):
        return format_teeth(parse_teeth(self.cleaned_data.get("teeth")))

    def clean_surfaces(self):
        return parse_surfaces(self.cleaned_data.get("surfaces"))

    def clean(self):
        data = super().clean()
        if not data.get("operator") and not data.get("supervisor"):
            self.add_error("operator", _("Choose who did the treatment (operator) or the supervisor."))
        step_type = data.get("step_type")
        if step_type and step_type.chart_effect != ChartEffect.NONE and not data.get("teeth"):
            self.add_error("teeth", _("Write the tooth numbers for this treatment."))
        if step_type and not data.get("material") and step_type.default_material:
            data["material"] = step_type.default_material
        return data


class StepReviewForm(StyledModelForm):
    class Meta:
        model = TreatmentStep
        fields = ["grade", "supervisor_comment"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["grade"].col = "col-md-3"
        self.fields["supervisor_comment"].col = "col-md-9"
        self.fields["supervisor_comment"].widget.attrs["rows"] = 2


class LabRequestForm(_PatientScopedForm):
    patient_lookup = PatientLookupField(label=_("patient"))
    dentist = DentistChoiceField(label=_("dentist"))
    supervisor = DentistChoiceField(kinds=(Dentist.Kind.SUPERVISOR,), label=_("reviewed by supervisor"), required=False)

    fieldsets = [
        ("", ["patient_lookup", "dentist", "supervisor", "lab", "work_type", "teeth", "units", "shade", "material",
              "due_date"]),
        ("", ["instructions", "lab_cost"]),
    ]

    class Meta:
        model = LabRequest
        fields = [
            "dentist", "supervisor", "lab", "work_type", "teeth", "units", "shade", "material",
            "due_date", "instructions", "lab_cost",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["lab"].queryset = Lab.objects.filter(is_active=True)
        self.fields["work_type"].queryset = LabWorkType.objects.filter(is_active=True)
        if not has_role(self.user, *FRONT_DESK):
            del self.fields["lab_cost"]
        self.fields["supervisor"].help_text = LabRequest._meta.get_field("supervisor").help_text

    def clean_teeth(self):
        return format_teeth(parse_teeth(self.cleaned_data.get("teeth")))


class LabActionForm(StyledForm):
    action = forms.CharField(widget=forms.HiddenInput)
    notes = forms.CharField(label=_("notes"), required=False, widget=forms.Textarea(attrs={"rows": 2}))
    checked = forms.BooleanField(label=_("I checked the work against the lab request"), required=False)


class StepFilterForm(StyledForm):
    date_from = forms.DateField(label=_("From"), required=False)
    date_to = forms.DateField(label=_("To"), required=False)
    dentist = DentistChoiceField(label=_("dentist"), required=False, empty_label=_("All"))
    step_type = forms.ModelChoiceField(
        label=_("treatment"), queryset=TreatmentStepType.objects.all(), required=False, empty_label=_("All")
    )
    tooth = forms.CharField(label=_("tooth"), required=False, max_length=2)
    unchecked = forms.BooleanField(label=_("not checked yet"), required=False)


class LabFilterForm(StyledForm):
    q = forms.CharField(label=_("Search"), required=False)
    status = forms.ChoiceField(
        label=_("status"), required=False,
        choices=[("", _("All")), ("open", _("Open (not delivered)"))] + list(LabRequest.Status.choices),
    )
    lab = forms.ModelChoiceField(label=_("lab"), queryset=Lab.objects.all(), required=False, empty_label=_("All"))
    overdue = forms.BooleanField(label=_("late at the lab"), required=False)
    mine = forms.BooleanField(label=_("my requests"), required=False)
