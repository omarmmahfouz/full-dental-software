from django import forms
from django.forms import BaseInlineFormSet, inlineformset_factory
from django.utils.translation import gettext_lazy as _

from apps.charting.teeth import TOOTH_CHOICES
from apps.core.forms import BootstrapFormMixin, StyledModelForm, validate_upload
from apps.dentists.forms import DentistChoiceField
from apps.dentists.models import Dentist
from apps.patients.access import visible_patients
from apps.patients.forms import PatientLookupField

from .models import ImplantSystem, Surgery, SurgerySite


class SurgeryForm(StyledModelForm):
    patient_lookup = PatientLookupField(label=_("patient"))
    instructor = DentistChoiceField(kinds=(Dentist.Kind.SUPERVISOR,), label=_("instructor"), required=False)
    operator_1 = DentistChoiceField(label=_("operator 1"))
    operator_2 = DentistChoiceField(label=_("operator 2"), required=False)
    assistant = DentistChoiceField(label=_("assistant"), required=False)
    augmentation_sites = forms.MultipleChoiceField(
        label=_("augmentation site"), choices=Surgery.AUGMENTATION_CHOICES, required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    exposure = forms.NullBooleanField(
        label=_("exposure"), required=False,
        widget=forms.Select(choices=[("unknown", "—"), ("true", _("Yes")), ("false", _("No"))]),
    )
    update_chart = forms.BooleanField(
        label=_("Update the dental chart (extractions → missing, implants → implant)"), required=False, initial=True,
    )

    fieldsets = [
        (_("Surgery team"), ["patient_lookup", "date", "difficulty", "instructor", "operator_1", "operator_2", "assistant"]),
        (_("Guided bone regeneration"), [
            "block_graft", "block_donor", "block_donor_other", "cut_by", "screws_count", "bone_particle",
            "autogenous_percent", "bone_material", "acm_bur_area", "gbr_notes",
        ]),
        (_("Open sinus lift"), ["sinus_approach", "sinus_fill_material", "sinus_notes"]),
        (_("Membrane and tacks"), [
            "membrane_used", "membrane_size", "membrane_material", "membrane_company", "tacks_count", "tacks_company",
        ]),
        (_("Soft tissue"), [
            "soft_tissue_graft", "soft_tissue_technique", "exposure", "custom_healing_teeth", "donor_site",
            "soft_tissue_suture_material", "soft_tissue_suture_technique", "pack_type", "recipient_area",
            "augmentation_sites", "frenectomy", "soft_tissue_bone_graft", "soft_tissue_notes",
        ]),
        (_("Suture, temporization and X-ray"), [
            "suture_size", "suture_material", "suture_technique", "xray_taken", "xray_notes", "temporary",
        ]),
        (_("Notes"), ["notes", "complications", "update_chart"]),
    ]

    class Meta:
        model = Surgery
        exclude = ["branch", "patient", "appointment", "number", "created_by", "chart_updated"]

    def __init__(self, *args, user=None, patient=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        patient = patient or (self.instance.patient if self.instance.pk else None)
        if patient is not None:
            self.fields["patient_lookup"].initial = patient.file_number
            self.fields["patient_lookup"].help_text = str(patient)
        self.initial["augmentation_sites"] = (self.instance.augmentation_sites or "").split(",")
        for name in ("gbr_notes", "sinus_notes", "soft_tissue_notes", "notes", "complications"):
            self.fields[name].widget.attrs["rows"] = 2
        self.fields["update_chart"].col = "col-12"

    def clean_patient_lookup(self):
        patient = self.cleaned_data["patient_lookup"]
        if not visible_patients(self.user).filter(pk=patient.pk).exists():
            raise forms.ValidationError(_("This patient is not one of your patients."))
        return patient

    def clean_augmentation_sites(self):
        return ",".join(self.cleaned_data.get("augmentation_sites") or [])

    def clean(self):
        data = super().clean()
        team = [data.get("operator_1"), data.get("operator_2"), data.get("assistant")]
        chosen = [d for d in team if d]
        if len(chosen) != len({d.pk for d in chosen}):
            raise forms.ValidationError(_("The same dentist is chosen twice in the surgery team."))
        if data.get("bone_particle") == Surgery.Particle.MIX and data.get("autogenous_percent") is None:
            self.add_error("autogenous_percent", _("Write the autogenous percentage of the mix."))
        if data.get("block_graft") and not data.get("block_donor"):
            self.add_error("block_donor", _("Choose the donor site of the block."))
        return data


class SurgerySiteForm(BootstrapFormMixin, forms.ModelForm):
    tooth = forms.TypedChoiceField(label=_("tooth"), choices=[("", "—")] + TOOTH_CHOICES, coerce=int)

    class Meta:
        model = SurgerySite
        fields = [
            "tooth", "extraction", "flap", "simple_implant", "immediate_implant", "expansion", "splitting",
            "closed_sinus", "open_sinus", "gbr", "guided", "implant_system", "implant_diameter", "implant_length",
            "lot_number", "sticker", "insertion_torque", "isq", "subcrestal", "notes",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["implant_system"].queryset = ImplantSystem.objects.filter(is_active=True)
        self.fields["sticker"].validators.append(validate_upload)
        self.fields["sticker"].widget.attrs["accept"] = "image/*"
        for name in ("implant_diameter", "implant_length"):
            self.fields[name].widget.attrs.update({"step": "0.1", "min": "2", "max": "20"})

    def clean(self):
        data = super().clean()
        places_implant = any(data.get(n) for n in SurgerySite.IMPLANT_PROCEDURES)
        has_details = data.get("implant_system") or data.get("implant_diameter") or data.get("implant_length")
        if has_details and not places_implant:
            self.add_error("simple_implant", _("Tick how the implant was placed (simple, immediate or guided)."))
        if places_implant:
            for name in ("implant_system", "implant_diameter", "implant_length"):
                if not data.get(name):
                    self.add_error(name, _("Required when an implant is placed."))
        if data.get("tooth") and not any(data.get(name) for name, _label in SurgerySite.PROCEDURES):
            self.add_error("tooth", _("Tick at least one procedure for this tooth."))
        return data


class BaseSiteFormSet(BaseInlineFormSet):
    def clean(self):
        teeth = []
        duplicate = False
        for form in self.forms:
            data = getattr(form, "cleaned_data", None)
            if not data or data.get("DELETE") or not data.get("tooth"):
                continue
            tooth = data["tooth"]
            if tooth in teeth:
                form.add_error("tooth", _("Tooth %(tooth)s is written twice.") % {"tooth": tooth})
                duplicate = True
            teeth.append(tooth)
        if duplicate:
            return  # the message on the repeated tooth replaces Django's generic "duplicate values" one
        super().clean()
        if not teeth:
            raise forms.ValidationError(_("Add at least one tooth to the surgery chart."))


SurgerySiteFormSet = inlineformset_factory(
    Surgery, SurgerySite, form=SurgerySiteForm, formset=BaseSiteFormSet, extra=2, can_delete=True
)


class ImplantUpdateForm(StyledModelForm):
    class Meta:
        model = SurgerySite
        fields = ["implant_status", "uncovered_on", "impression_on", "loaded_on", "failed_on", "failure_reason", "notes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["implant_status"].required = True
        for field in self.fields.values():
            field.col = "col-md-4"

    def clean(self):
        data = super().clean()
        if data.get("implant_status") == SurgerySite.ImplantStatus.FAILED and not data.get("failed_on"):
            self.add_error("failed_on", _("Write the date of failure."))
        return data
