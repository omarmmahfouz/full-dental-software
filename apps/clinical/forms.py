from django import forms
from django.utils.translation import gettext_lazy as _

from apps.charting.teeth import format_teeth, parse_surfaces, parse_teeth
from apps.core.forms import StyledForm, StyledModelForm
from apps.core.roles import FRONT_DESK, has_role
from apps.dentists.forms import DentistChoiceField
from apps.dentists.models import Dentist
from apps.patients.access import visible_patients
from apps.patients.forms import PatientLookupField, lookup_value

from .models import ChartEffect, Lab, LabRequest, LabWorkType, OutsideRequest, TreatmentStep, TreatmentStepType


class _PatientScopedForm(StyledModelForm):
    """Adds a patient box limited to the patients the user may see."""

    def __init__(self, *args, user=None, patient=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        self.fields["patient_lookup"].initial = lookup_value(patient) if patient else None
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

    bill_service = forms.ModelChoiceField(
        label=_("Bill for this treatment (optional)"), required=False, queryset=None,
        help_text=_("Choose the paid service: the reception sees it to collect, with the bill ready."))
    bill_price = forms.DecimalField(label=_("price"), required=False, min_value=0, max_digits=10, decimal_places=2,
                                    help_text=_("Leave empty for the price of the list."))

    fieldsets = [
        ("", ["patient_lookup", "performed_at", "step_type", "notes", "teeth", "surfaces", "material"]),
        ("", ["operator", "assistant", "supervisor", "next_visit", "update_chart"]),
        (_("Bill"), ["bill_service", "bill_price"]),
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
        self.fields["teeth"].widget.attrs.update(
            {"data-digits": "1", "autocomplete": "off", "data-teeth-picker": "multi"})
        for name in ("patient_lookup", "performed_at", "step_type", "teeth", "surfaces", "material",
                     "operator", "assistant", "supervisor"):
            self.fields[name].col = "col-md-4"
        self.fields["notes"].col = "col-12"
        self.fields["next_visit"].col = "col-md-8"
        self.fields["update_chart"].col = "col-12"
        from apps.billing.forms import ServiceChoiceField
        from apps.billing.models import Service

        self.fields["bill_service"] = ServiceChoiceField(
            label=self.fields["bill_service"].label, required=False, help_text=self.fields["bill_service"].help_text,
            queryset=Service.objects.filter(is_active=True))
        self.fields["bill_service"].widget.attrs["class"] = "form-select"
        self.fields["bill_service"].col = "col-md-6"
        self.fields["bill_price"].col = "col-md-3"
        if self.instance.pk:  # the bill is added once, with the new treatment
            del self.fields["bill_service"], self.fields["bill_price"]

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


class StepOperatorForm(StyledModelForm):
    operator = DentistChoiceField(label=_("operator"), required=False)
    assistant = DentistChoiceField(label=_("assistant"), required=False)

    class Meta:
        model = TreatmentStep
        fields = ["operator", "assistant"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.col = "col-md-6"


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
        ("", ["patient_lookup", "dentist", "supervisor", "lab", "work_type", "work_form", "teeth", "units",
              "shade_guide", "shade", "material", "due_date"]),
        ("", ["instructions", "lab_cost"]),
    ]

    class Meta:
        model = LabRequest
        fields = [
            "dentist", "supervisor", "lab", "work_type", "work_form", "teeth", "units", "shade_guide", "shade",
            "material", "due_date", "instructions", "lab_cost",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["lab"].queryset = Lab.objects.filter(is_active=True)
        self.fields["work_type"].queryset = LabWorkType.objects.filter(is_active=True)
        self.fields["teeth"].widget.attrs["data-teeth-picker"] = "multi"
        # The shade from the guide's own list (the page shows the list of the chosen guide).
        guides = [(str(LabRequest.ShadeGuide.CLASSICAL.label), [(v, v) for v in LabRequest.CLASSICAL_SHADES]),
                  (str(LabRequest.ShadeGuide.MASTER.label), [(v, v) for v in LabRequest.MASTER_SHADES])]
        current = self.instance.shade if self.instance.pk else ""
        known = set(LabRequest.CLASSICAL_SHADES) | set(LabRequest.MASTER_SHADES)
        extra = [(current, current)] if current and current not in known else []
        self.fields["shade"] = forms.ChoiceField(
            label=_("shade"), required=False, choices=[("", "—")] + extra + guides,
            widget=forms.Select(attrs={"class": "form-select", "data-shade": "1"}))
        self.fields["shade_guide"].widget.attrs["data-shade-guide"] = "1"
        self.fields["work_form"].required = False
        self.fields["due_date"].help_text = _("Leave empty: set from the usual days of the work type when sent.")
        if not has_role(self.user, *FRONT_DESK):
            del self.fields["lab_cost"]
        self.fields["supervisor"].help_text = LabRequest._meta.get_field("supervisor").help_text

    def clean_teeth(self):
        return format_teeth(parse_teeth(self.cleaned_data.get("teeth")))

    def clean(self):
        data = super().clean()
        shade, guide = data.get("shade"), data.get("shade_guide")
        lists = {LabRequest.ShadeGuide.CLASSICAL: LabRequest.CLASSICAL_SHADES,
                 LabRequest.ShadeGuide.MASTER: LabRequest.MASTER_SHADES}
        if shade and guide and shade in set(LabRequest.CLASSICAL_SHADES) | set(LabRequest.MASTER_SHADES) \
                and shade not in lists[guide]:
            self.add_error("shade", _("This shade is not in the chosen shade guide."))
        if shade and not guide:
            data["shade_guide"] = next((g for g, values in lists.items() if shade in values), "")
        if not data.get("work_form"):
            data["work_form"] = LabRequest.WorkForm.PHYSICAL
            self.instance.work_form = LabRequest.WorkForm.PHYSICAL
        return data


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


class OutsideRequestForm(StyledModelForm):
    """CBCT or medical lab request, printed for the patient to take."""

    purposes = forms.MultipleChoiceField(label=_("for"), required=False, choices=OutsideRequest.PURPOSES,
                                         widget=forms.CheckboxSelectMultiple)
    tests = forms.MultipleChoiceField(label=_("tests"), required=False, choices=OutsideRequest.TESTS,
                                      widget=forms.CheckboxSelectMultiple)
    dentist = DentistChoiceField(label=_("requested by"), required=False)

    CBCT_FIELDS = ["requested_on", "dentist", "region", "teeth", "field_of_view", "purposes", "notes"]
    LAB_FIELDS = ["requested_on", "dentist", "tests", "other_tests", "notes"]

    class Meta:
        model = OutsideRequest
        fields = ["requested_on", "dentist", "region", "teeth", "field_of_view", "purposes", "tests", "other_tests",
                  "notes"]

    def __init__(self, *args, kind=OutsideRequest.Kind.CBCT, **kwargs):
        self.kind = kind
        super().__init__(*args, **kwargs)
        keep = self.CBCT_FIELDS if kind == OutsideRequest.Kind.CBCT else self.LAB_FIELDS
        for name in list(self.fields):
            if name not in keep:
                del self.fields[name]
        for name in ("requested_on", "dentist", "region", "teeth", "field_of_view", "other_tests"):
            if name in self.fields:
                self.fields[name].col = "col-md-6"
        if "teeth" in self.fields:
            self.fields["teeth"].widget.attrs["data-teeth-picker"] = "multi"
        if "notes" in self.fields:
            self.fields["notes"].widget.attrs["rows"] = 2

    def clean_teeth(self):
        teeth = self.cleaned_data.get("teeth", "")
        return format_teeth(parse_teeth(teeth)) if teeth else ""

    def clean(self):
        data = super().clean()
        if self.kind == OutsideRequest.Kind.CBCT:
            if not data.get("region"):
                self.add_error("region", _("Choose the area to scan."))
            elif data["region"] == OutsideRequest.Region.TEETH and not data.get("teeth"):
                self.add_error("teeth", _("Write the teeth to scan."))
        elif not data.get("tests") and not data.get("other_tests"):
            self.add_error("tests", _("Choose at least one test."))
        return data
