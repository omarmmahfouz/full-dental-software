from django import forms
from django.forms import inlineformset_factory
from django.utils.text import capfirst
from django.utils.translation import gettext_lazy as _

from apps.charting.teeth import TOOTH_CHOICES, format_teeth, parse_teeth
from apps.core.forms import BootstrapFormMixin, StyledForm, StyledModelForm, validate_upload
from apps.dentists.forms import DentistChoiceField

from . import shades
from .models import (
    EndoCanal, EndoCase, EndoVisit, OrthoCase, OrthoVisit, Referral, ShadeRecord, TMJExam, TMJVisit,
)


def ticks(choices, label):
    """A list of tick boxes kept as a list of codes."""
    return forms.MultipleChoiceField(label=label, choices=choices, required=False,
                                     widget=forms.CheckboxSelectMultiple)


def doctors_here(form, place, *names):
    for name in names:
        form.fields[name].queryset = form.fields[name].queryset.working_at(place)


class RecordForm(StyledModelForm):
    """A specialist's chart: the doctor is one of the place's doctors (the one logged in by default)."""

    dentist = DentistChoiceField(label=_("doctor"))

    def __init__(self, *args, place=None, **kwargs):
        super().__init__(*args, **kwargs)
        doctors_here(self, place, "dentist")
        for name, field in self.fields.items():
            if isinstance(field.widget, forms.Textarea):
                field.widget.attrs["rows"] = 2
                field.col = "col-12"
            elif isinstance(field.widget, forms.CheckboxSelectMultiple):
                field.col = "col-12"
            else:
                field.col = getattr(field, "col", "col-md-6 col-lg-4")


# ------------------------------------------------------------------ referrals
class ReferralForm(StyledModelForm):
    from_dentist = DentistChoiceField(label=_("referred by"))
    to_dentist = DentistChoiceField(label=_("to the doctor"), required=False, empty_label=_("— outside the clinic —"))

    fieldsets = [("", ["from_dentist", "to_dentist", "to_outside", "specialty", "urgency", "teeth", "reason"])]

    class Meta:
        model = Referral
        fields = ["from_dentist", "to_dentist", "to_outside", "specialty", "urgency", "teeth", "reason"]
        widgets = {"reason": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, place=None, **kwargs):
        super().__init__(*args, **kwargs)
        doctors_here(self, place, "from_dentist", "to_dentist")
        self.fields["teeth"].widget.attrs.update({"data-teeth-picker": "multi", "data-digits": "1"})
        self.fields["specialty"].help_text = _("Filled from the doctor chosen.")
        for name in ("from_dentist", "to_dentist", "to_outside", "specialty", "urgency", "teeth"):
            self.fields[name].col = "col-md-6"
        self.fields["reason"].col = "col-12"

    def clean_teeth(self):
        return format_teeth(parse_teeth(self.cleaned_data.get("teeth")))

    def clean(self):
        data = super().clean()
        to = data.get("to_dentist")
        if not to and not data.get("to_outside"):
            self.add_error("to_dentist", _("Choose our doctor, or write the doctor or centre outside."))
        if to and to == data.get("from_dentist"):
            self.add_error("to_dentist", _("A doctor does not refer a patient to himself."))
        if to and not data.get("specialty") and to.specialty:
            data["specialty"] = self.instance.specialty = to.specialty
        return data


class ReplyForm(StyledForm):
    reply = forms.CharField(label=_("the specialist's answer"), widget=forms.Textarea(attrs={"rows": 4}),
                            help_text=Referral._meta.get_field("reply").help_text)


# ------------------------------------------------------------------ endodontics
class EndoCaseForm(RecordForm):
    tooth = forms.TypedChoiceField(label=_("tooth"), choices=[("", "—")] + TOOTH_CHOICES, coerce=int,
                                   widget=forms.Select(attrs={"data-teeth-picker": "single"}))
    pain_kinds = ticks(EndoCase.PAIN_KINDS, _("the pain"))
    difficulty_factors = ticks(EndoCase.DIFFICULTY_FACTORS, _("what makes it difficult"))
    irrigants = ticks(EndoCase.IRRIGANTS, _("irrigation"))

    fieldsets = [
        (_("The tooth"), ["tooth", "dentist", "started_on", "treatment"]),
        (_("History and tests"), ["chief_complaint", "pain", "pain_kinds", "cold_test", "heat_test", "ept",
                                  "percussion", "palpation", "mobility", "probing", "swelling", "sinus_tract",
                                  "radiographic"]),
        (_("Diagnosis (AAE)"), ["pulpal_diagnosis", "apical_diagnosis", "difficulty", "difficulty_factors"]),
        (_("How it is treated"), ["anaesthesia", "rubber_dam", "magnification", "instruments", "irrigants",
                                  "activation"]),
        (_("Obturation and after"), ["obturation", "sealer", "restoration", "prognosis", "recall", "notes"]),
    ]

    class Meta:
        model = EndoCase
        fields = ["tooth", "dentist", "started_on", "treatment", "chief_complaint", "pain", "pain_kinds",
                  "cold_test", "heat_test", "ept", "percussion", "palpation", "mobility", "probing", "swelling",
                  "sinus_tract", "radiographic", "pulpal_diagnosis", "apical_diagnosis", "difficulty",
                  "difficulty_factors", "anaesthesia", "rubber_dam", "magnification", "instruments", "irrigants",
                  "activation", "obturation", "sealer", "restoration", "prognosis", "recall", "notes"]


class CanalForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = EndoCanal
        fields = ["name", "reference", "working_length", "method", "master_file", "master_cone", "curvature",
                  "notes"]
        widgets = {"name": forms.TextInput(attrs={"list": "canal-names", "size": 6}),
                   "working_length": forms.NumberInput(attrs={"step": "0.5", "inputmode": "decimal"})}


CanalFormSet = inlineformset_factory(EndoCase, EndoCanal, form=CanalForm, extra=0, can_delete=True)


class EndoVisitForm(StyledModelForm):
    work = ticks(EndoVisit.WORK, _("done at this visit"))

    class Meta:
        model = EndoVisit
        fields = ["date", "work", "medication", "temporary", "pain", "notes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.col = "col-md-6 col-lg-3"
        self.fields["work"].col = "col-12"
        self.fields["notes"].col = "col-md-12 col-lg-6"


# ------------------------------------------------------------------ TMJ
class TMJExamForm(RecordForm):
    pain_sites = ticks(TMJExam.PAIN_SITES, _("where it hurts"))
    muscles = ticks(TMJExam.MUSCLES, _("tender muscles"))
    diagnoses = ticks(TMJExam.DIAGNOSES, _("diagnosis (DC/TMD)"))
    plan = ticks(TMJExam.PLAN, _("treatment plan"))

    fieldsets = [
        (_("The complaint"), ["exam_date", "dentist", "chief_complaint", "since", "pain_vas", "pain_sites", "headache",
                              "bruxism", "habits"]),
        (_("Jaw movements (mm)"), ["opening", "opening_max", "opening_pain", "right_lateral", "left_lateral",
                                   "protrusion", "path"]),
        (_("The joints and the muscles"), ["sound_right", "sound_left", "locking", "joint_tender_right",
                                           "joint_tender_left", "muscles", "occlusion", "imaging"]),
        (_("Diagnosis and plan"), ["diagnoses", "plan", "splint", "notes"]),
    ]

    class Meta:
        model = TMJExam
        fields = ["exam_date", "dentist", "chief_complaint", "since", "pain_vas", "pain_sites", "headache", "bruxism",
                  "habits", "opening", "opening_max", "opening_pain", "right_lateral", "left_lateral", "protrusion",
                  "path", "sound_right", "sound_left", "locking", "joint_tender_right", "joint_tender_left",
                  "muscles", "occlusion", "imaging", "diagnoses", "plan", "splint", "notes"]


class TMJVisitForm(StyledModelForm):
    class Meta:
        model = TMJVisit
        fields = ["date", "opening", "pain_vas", "done", "notes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.col = "col-md-4 col-lg-2"
        self.fields["done"].col = self.fields["notes"].col = "col-md-6 col-lg-3"


# ------------------------------------------------------------------ orthodontics
class OrthoCaseForm(RecordForm):
    anchorage = ticks(OrthoCase.ANCHORAGE, _("anchorage"))

    fieldsets = [
        (_("The case"), ["records_on", "dentist", "status", "chief_complaint"]),
        (_("The face"), ["profile", "symmetric", "lips", "smile_line"]),
        (_("The teeth"), ["molar_right", "molar_left", "canine_right", "canine_left", "overjet", "overbite",
                          "crossbite", "midline", "crowding_upper", "crowding_lower", "habits"]),
        (_("Cephalometric values"), ["sna", "snb", "anb", "fma", "u1_sn", "impa", "wits", "skeletal", "vertical"]),
        (_("Diagnosis and plan"), ["diagnosis", "appliance", "prescription", "extraction", "anchorage", "months",
                                   "retention", "bonded_on", "debonded_on", "notes"]),
    ]

    class Meta:
        model = OrthoCase
        fields = ["records_on", "dentist", "status", "chief_complaint", "profile", "symmetric", "lips", "smile_line",
                  "molar_right", "molar_left", "canine_right", "canine_left", "overjet", "overbite", "crossbite",
                  "midline", "crowding_upper", "crowding_lower", "habits", "sna", "snb", "anb", "fma", "u1_sn", "impa",
                  "wits", "skeletal", "vertical", "diagnosis", "appliance", "prescription", "extraction", "anchorage",
                  "months", "retention", "bonded_on", "debonded_on", "notes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("sna", "snb", "anb", "fma", "u1_sn", "impa", "wits"):
            self.fields[name].col = "col-6 col-md-3 col-lg-2"
            self.fields[name].widget.attrs.update(step="0.5", inputmode="decimal")

    def clean(self):
        data = super().clean()
        if data.get("sna") is not None and data.get("snb") is not None and data.get("anb") is None:
            data["anb"] = self.instance.anb = data["sna"] - data["snb"]  # worked out when left empty
        return data


class OrthoVisitForm(StyledModelForm):
    class Meta:
        model = OrthoVisit
        fields = ["date", "upper_wire", "lower_wire", "aligner", "elastics", "done", "hygiene", "next_weeks", "notes"]
        widgets = {"upper_wire": forms.TextInput(attrs={"list": "ortho-wires"}),
                   "lower_wire": forms.TextInput(attrs={"list": "ortho-wires"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.col = "col-md-4 col-lg-3"
        self.fields["done"].col = self.fields["notes"].col = "col-md-6"


# ------------------------------------------------------------------ the shade
def shade_select(label, required=False, current=""):
    return forms.ChoiceField(label=capfirst(label), required=required, choices=shades.shade_choices(current),
                             widget=forms.Select(attrs={"data-shade": "1"}))


class ShadeRecordForm(RecordForm):
    characters = ticks(ShadeRecord.CHARACTERS, _("characters to copy"))

    fieldsets = [
        ("", ["taken_on", "dentist", "teeth", "prosthesis"]),
        (_("The shade"), ["guide", "shade", "shade_cervical", "shade_incisal", "stump", "translucency", "surface",
                          "characters", "light"]),
        (_("Photo and notes"), ["photo", "notes"]),
    ]

    class Meta:
        model = ShadeRecord
        fields = ["taken_on", "dentist", "teeth", "prosthesis", "guide", "shade", "shade_cervical", "shade_incisal",
                  "stump", "translucency", "surface", "characters", "light", "photo", "notes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        instance = self.instance
        self.fields["shade"] = shade_select(_("shade (middle third)"), True, instance.shade)
        self.fields["shade_cervical"] = shade_select(_("cervical third"), current=instance.shade_cervical)
        self.fields["shade_incisal"] = shade_select(_("incisal third"), current=instance.shade_incisal)
        self.fields["stump"] = forms.ChoiceField(label=capfirst(_("prepared tooth (stump) shade")), required=False,
                                                 choices=shades.stump_choices(),
                                                 widget=forms.Select(attrs={"data-stump": "1"}),
                                                 help_text=ShadeRecord._meta.get_field("stump").help_text)
        self.fields["guide"].widget.attrs["data-shade-guide"] = "1"
        self.fields["teeth"].widget.attrs.update({"data-teeth-picker": "multi", "data-digits": "1"})
        self.fields["photo"].widget.attrs["accept"] = "image/*"
        self.fields["photo"].validators.append(validate_upload)
        for name in ("shade", "shade_cervical", "shade_incisal", "stump"):
            self.fields[name].widget.attrs["class"] = "form-select"
            self.fields[name].col = "col-md-6 col-lg-3"
        self.fields["guide"].col = "col-md-6 col-lg-3"
        self.fields["photo"].col = "col-md-6"
        self.fields["notes"].col = "col-md-6"

    def clean_teeth(self):
        return format_teeth(parse_teeth(self.cleaned_data.get("teeth")))

    def clean(self):
        data = super().clean()
        guide = data.get("guide")
        for name in ("shade", "shade_cervical", "shade_incisal"):
            value = data.get(name)
            if value and guide and shades.guide_of(value) not in ("", guide):
                self.add_error(name, _("This shade is not in the chosen shade guide."))
        return data
