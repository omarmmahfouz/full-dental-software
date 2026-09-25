from django import forms
from django.forms import inlineformset_factory
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.clinical.models import TreatmentStepType
from apps.core.forms import BootstrapFormMixin, StyledForm, StyledModelForm
from apps.dentists.forms import DentistChoiceField
from apps.dentists.models import Dentist
from apps.patients.models import MedicalCondition

from .models import ClinicalPhoto, Examination, PlanItem, ToothState, TreatmentPlan
from .teeth import SURFACES, format_teeth, parse_teeth

SURFACE_CHOICES = [(s, s) for s in SURFACES]


class ExaminationForm(StyledModelForm):
    """The diagnostic chart: examination + medical history + dental history."""

    examined_by = DentistChoiceField(label=_("examined by"), required=False)
    supervisor = DentistChoiceField(kinds=(Dentist.Kind.SUPERVISOR,), label=_("supervisor"), required=False)
    update_chart = forms.BooleanField(
        label=_("Write these teeth onto the dental chart"), required=False, initial=True,
    )

    fieldsets = [
        (_("Examination"), ["exam_date", "examined_by", "supervisor", "referral", "chief_complaint"]),
        (_("Teeth (write tooth numbers, e.g. 16, 26 or 34-36)"), [
            "teeth_carious", "teeth_filled", "teeth_missing", "teeth_not_sure", "teeth_mobility", "teeth_hopeless",
            "teeth_implant_placed", "teeth_implant_failed", "update_chart",
            "inter_arch_space_right", "inter_arch_space_left", "operator_notices",
            "cbct_requested", "cbct_done", "new_cbct_requested",
        ]),
        (_("Medical health"), [
            "general_health", "pregnant", "lactating", "under_treatment", "recent_surgery", "medical_comment",
            "conditions", "other_condition", "conditions_comment",
        ]),
        (_("Blood pressure and glucose"), [
            "bp_last_systolic", "bp_last_diastolic", "bp_last_when", "bp_drug", "bp_clinic_systolic",
            "bp_clinic_diastolic", "glucose_level", "glucose_last", "glucose_last_when", "glucose_random_clinic",
            "hba1c", "hba1c_date",
        ]),
        (_("Allergies, bleeding and drugs"), [
            "allergy_penicillin", "allergy_sulfa", "allergy_other", "bleeding_or_aspirin", "digestion_problem",
            "illegal_drugs", "illegal_drugs_notes", "drugs_taken", "operator_comments",
        ]),
        (_("Dental history"), [
            "sensitive_hot_cold", "sensitive_sweets", "sensitive_biting", "bruxism", "smoker",
            "cigarettes_per_day", "mouth_injury", "satisfied_appearance", "cooperation_score",
            "implant_willingness_score",
        ]),
    ]

    class Meta:
        model = Examination
        exclude = ["patient", "created_by"]
        widgets = {"conditions": forms.CheckboxSelectMultiple}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["conditions"].queryset = MedicalCondition.objects.filter(is_active=True)
        for name in Examination.TOOTH_FIELDS:
            self.fields[name].widget.attrs.update({"data-digits": "1", "placeholder": "e.g. 16, 26"})
            self.fields[name].col = "col-md-6 col-lg-3"
        for name in ("chief_complaint", "operator_notices", "medical_comment", "conditions_comment",
                     "drugs_taken", "operator_comments"):
            self.fields[name].widget.attrs["rows"] = 2
        for name in ("bp_last_systolic", "bp_last_diastolic", "bp_clinic_systolic", "bp_clinic_diastolic",
                     "glucose_last", "glucose_random_clinic", "hba1c", "cigarettes_per_day", "cooperation_score",
                     "implant_willingness_score"):
            self.fields[name].col = "col-6 col-md-3"
        self.fields["update_chart"].col = "col-12"

    def clean(self):
        data = super().clean()
        for name in Examination.TOOTH_FIELDS:
            try:
                data[name] = format_teeth(parse_teeth(data.get(name)))
            except forms.ValidationError as error:
                self.add_error(name, error)
        return data


class ToothForm(StyledModelForm):
    caries_surfaces = forms.MultipleChoiceField(
        label=_("caries surfaces"), choices=SURFACE_CHOICES, required=False, widget=forms.CheckboxSelectMultiple
    )
    filling_surfaces = forms.MultipleChoiceField(
        label=_("filled surfaces"), choices=SURFACE_CHOICES, required=False, widget=forms.CheckboxSelectMultiple
    )

    class Meta:
        model = ToothState
        fields = ["status", "caries", "caries_surfaces", "filled", "filling_surfaces", "filling_material", "rct",
                  "crown", "crown_material", "hopeless", "fractured", "not_sure", "mobility", "notes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.initial["caries_surfaces"] = list(self.instance.caries_surfaces or "")
        self.initial["filling_surfaces"] = list(self.instance.filling_surfaces or "")
        for name in self.fields:
            self.fields[name].col = "col-md-4"
        self.fields["notes"].col = "col-12"
        self.fields["caries_surfaces"].help_text = _("M mesial, O occlusal/incisal, D distal, B buccal, L lingual/palatal")

    def clean_caries_surfaces(self):
        return "".join(s for s in SURFACES if s in self.cleaned_data["caries_surfaces"])

    def clean_filling_surfaces(self):
        return "".join(s for s in SURFACES if s in self.cleaned_data["filling_surfaces"])

    def clean(self):
        data = super().clean()
        if data.get("caries_surfaces"):
            data["caries"] = True
        if data.get("filling_surfaces"):
            data["filled"] = True
        return data


class TreatmentPlanForm(StyledModelForm):
    dentist = DentistChoiceField(label=_("planned by"), required=False)
    approved_by = DentistChoiceField(
        kinds=(Dentist.Kind.SUPERVISOR,), label=_("approved by supervisor"), required=False,
        help_text=_("Supervisors do not log in: choose who approved the plan."),
    )

    class Meta:
        model = TreatmentPlan
        fields = ["title", "difficulty", "dentist", "approved_by", "notes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["notes"].widget.attrs["rows"] = 2
        for name in ("title", "difficulty", "dentist", "approved_by"):
            self.fields[name].col = "col-md-6"

    def save(self, commit=True):
        plan = super().save(commit=False)
        if plan.approved_by_id and plan.status == TreatmentPlan.Status.PROPOSED:
            plan.status = TreatmentPlan.Status.APPROVED
            plan.approved_at = timezone.now()
        elif not plan.approved_by_id and plan.status == TreatmentPlan.Status.APPROVED and "approved_by" in self.changed_data:
            plan.status, plan.approved_at = TreatmentPlan.Status.PROPOSED, None
        if commit:
            plan.save()
        return plan


class PlanItemForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = PlanItem
        fields = ["phase", "step_type", "teeth", "details"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["step_type"].queryset = TreatmentStepType.objects.filter(is_active=True)
        self.fields["teeth"].widget.attrs.update({"data-digits": "1", "placeholder": "36, 37"})
        self.fields["details"].widget.attrs["placeholder"] = _("e.g. implant 4.5 x 10, zirconia crown")

    def clean_teeth(self):
        return format_teeth(parse_teeth(self.cleaned_data.get("teeth")))


PlanItemFormSet = inlineformset_factory(TreatmentPlan, PlanItem, form=PlanItemForm, extra=4, can_delete=True)


class PhotoUploadForm(StyledForm):
    taken_on = forms.DateField(label=_("date"))
    surgery = forms.ModelChoiceField(label=_("surgery"), queryset=None, required=False)
    teeth = forms.CharField(label=_("teeth"), required=False, max_length=100)
    notes = forms.CharField(label=_("notes"), required=False, max_length=255)

    def __init__(self, *args, patient=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["surgery"].queryset = patient.surgeries.all() if patient is not None else ClinicalPhoto.objects.none()
        for field in self.fields.values():
            field.col = "col-md-3"

    def clean_teeth(self):
        return format_teeth(parse_teeth(self.cleaned_data.get("teeth")))
