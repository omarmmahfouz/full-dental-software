from django import forms
from django.utils.translation import gettext_lazy as _

from apps.core.forms import StyledForm, StyledModelForm, UserChoiceField
from apps.core.roles import FRONT_DESK, INTERN, SUPERVISOR, has_role, is_only_intern
from apps.patients.access import visible_patients
from apps.patients.forms import PatientLookupField

from .models import Lab, LabRequest, LabWorkType, TreatmentStep, TreatmentStepType


class _PatientScopedForm(StyledModelForm):
    """Adds a patient box and hides the doctor choice for interns (they record their own work)."""

    doctor_field = None

    def __init__(self, *args, user=None, patient=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        self.fields["patient_lookup"].initial = patient.file_number if patient else None
        if patient:
            self.fields["patient_lookup"].help_text = str(patient)
        if is_only_intern(user):
            del self.fields[self.doctor_field]

    def clean_patient_lookup(self):
        patient = self.cleaned_data["patient_lookup"]
        if not visible_patients(self.user).filter(pk=patient.pk).exists():
            raise forms.ValidationError(_("This patient is not assigned to you."))
        return patient


class TreatmentStepForm(_PatientScopedForm):
    doctor_field = "performed_by"
    patient_lookup = PatientLookupField(label=_("patient"))
    performed_by = UserChoiceField(roles=(INTERN,), label=_("done by (intern)"))
    supervised_by = UserChoiceField(roles=(SUPERVISOR,), label=_("supervisor present"), required=False)

    fieldsets = [
        ("", ["patient_lookup", "step_type", "teeth", "performed_at", "performed_by", "supervised_by"]),
        (_("Implant details (if an implant was placed)"), ["implant_system", "implant_size"]),
        ("", ["notes"]),
    ]

    class Meta:
        model = TreatmentStep
        fields = [
            "step_type", "teeth", "performed_at", "performed_by", "supervised_by",
            "implant_system", "implant_size", "notes",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["step_type"].queryset = TreatmentStepType.objects.filter(is_active=True)


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
    doctor_field = "requested_by"
    patient_lookup = PatientLookupField(label=_("patient"))
    requested_by = UserChoiceField(roles=(INTERN, SUPERVISOR), label=_("requested by (doctor)"))

    fieldsets = [
        ("", ["patient_lookup", "requested_by", "lab", "work_type", "teeth", "units", "shade", "material", "due_date"]),
        ("", ["instructions", "lab_cost"]),
    ]

    class Meta:
        model = LabRequest
        fields = [
            "requested_by", "lab", "work_type", "teeth", "units", "shade", "material",
            "due_date", "instructions", "lab_cost",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["lab"].queryset = Lab.objects.filter(is_active=True)
        self.fields["work_type"].queryset = LabWorkType.objects.filter(is_active=True)
        if not has_role(self.user, *FRONT_DESK):
            del self.fields["lab_cost"]


class LabActionForm(StyledForm):
    action = forms.CharField(widget=forms.HiddenInput)
    notes = forms.CharField(label=_("notes"), required=False, widget=forms.Textarea(attrs={"rows": 2}))
    checked = forms.BooleanField(label=_("I checked the work against the lab request"), required=False)


class StepFilterForm(StyledForm):
    date_from = forms.DateField(label=_("From"), required=False)
    date_to = forms.DateField(label=_("To"), required=False)
    intern = UserChoiceField(roles=(INTERN,), label=_("intern"), required=False, empty_label=_("All"))
    step_type = forms.ModelChoiceField(
        label=_("step"), queryset=TreatmentStepType.objects.all(), required=False, empty_label=_("All")
    )
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
