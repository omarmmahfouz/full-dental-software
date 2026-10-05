from django import forms
from django.forms import BaseInlineFormSet, inlineformset_factory
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.charting.teeth import TOOTH_CHOICES
from apps.core.forms import BootstrapFormMixin, StyledForm, StyledModelForm, validate_upload
from apps.core.widgets import DatalistInput
from apps.dentists.forms import DentistChoiceField
from apps.dentists.models import Dentist
from apps.patients.access import visible_patients
from apps.patients.forms import PatientLookupField, lookup_value

from .models import (
    DeliveryCheck, ImplantComplication, ImplantFollowUp, ImplantSystem, Prosthesis, Surgery, SurgeryOption,
    SurgerySite,
)


class SurgeryForm(StyledModelForm):
    patient_lookup = PatientLookupField(label=_("patient"))
    instructor = DentistChoiceField(kinds=(Dentist.Kind.SUPERVISOR,), label=_("instructor"), required=False)
    operator_1 = DentistChoiceField(label=_("operator 1"))
    operator_2 = DentistChoiceField(
        label=_("operator 2 (other teeth)"), required=False,
        help_text=_("A second dentist working on other teeth: choose him as the operator of those teeth below."))
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
            "sutured", "suture_size", "suture_material", "suture_technique", "xray_taken", "xray_notes", "temporary",
        ]),
        (_("Notes"), ["notes", "complications", "update_chart"]),
    ]

    class Meta:
        model = Surgery
        exclude = ["branch", "patient", "appointment", "number", "created_by", "chart_updated"]
        widgets = {"pontics": forms.HiddenInput(attrs={"data-arch-pontics": ""})}

    def __init__(self, *args, user=None, patient=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        patient = patient or (self.instance.patient if self.instance.pk else None)
        if patient is not None:
            self.fields["patient_lookup"].initial = lookup_value(patient)
            self.fields["patient_lookup"].help_text = str(patient)
        self.initial["augmentation_sites"] = (self.instance.augmentation_sites or "").split(",")
        for name in ("gbr_notes", "sinus_notes", "soft_tissue_notes", "notes", "complications"):
            self.fields[name].widget.attrs["rows"] = 2
        self.fields["update_chart"].col = "col-12"
        # The lists the owner keeps in Settings → Surgery chart lists (round 15).
        for kind in SurgeryOption.CHOICE_KINDS:
            field = self.fields[kind]
            self.fields[kind] = forms.ChoiceField(
                label=field.label, required=False, help_text=field.help_text,
                choices=[("", "---------")] + SurgeryOption.choices_for(kind, getattr(self.instance, kind, "")))
            self.fields[kind].widget.attrs["class"] = "form-select"
        suggested = [k for k, _label in SurgeryOption.Kind.choices if k not in SurgeryOption.CHOICE_KINDS]
        for kind in suggested:
            if kind in self.fields:
                self.fields[kind].widget = DatalistInput(_option_names(kind), attrs=self.fields[kind].widget.attrs)
        self.fields["sutured"] = forms.NullBooleanField(
            label=self.fields["sutured"].label, required=False, help_text=self.fields["sutured"].help_text,
            widget=forms.Select(choices=[("unknown", "—"), ("true", _("Yes")), ("false", _("No"))],
                                attrs={"class": "form-select"}))

    def clean_patient_lookup(self):
        patient = self.cleaned_data["patient_lookup"]
        if not visible_patients(self.user).filter(pk=patient.pk).exists():
            raise forms.ValidationError(_("This patient is not one of your patients."))
        return patient

    def clean_pontics(self):
        from apps.charting.teeth import format_teeth, parse_teeth

        return format_teeth(parse_teeth(self.cleaned_data.get("pontics")))

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
        if data.get("sutured") is None and (data.get("suture_size") or data.get("suture_material")):
            data["sutured"] = True
        return data

    # Round 15: a part chosen must be filled: the GBR when a tooth has a GBR, the sinus when a tooth has an open
    # sinus lift, the suture when it is "Yes", the membrane when one was used, the soft tissue graft when chosen.
    NEEDED = [
        ("gbr", ["bone_particle", "bone_material"]),
        ("open_sinus", ["sinus_approach", "sinus_fill_material"]),
        ("block_graft", ["block_donor", "cut_by", "screws_count"]),
        ("membrane_used", ["membrane_material", "membrane_size"]),
        ("sutured", ["suture_size", "suture_material", "suture_technique"]),
        ("soft_tissue_graft", ["soft_tissue_technique", "donor_site"]),
    ]

    def require_details(self, procedures):
        """Adds an error to each box of a chosen part left empty; ``procedures`` are the codes ticked on the teeth
        (gbr, open_sinus...). Returns True when all is filled."""
        data, ok = self.cleaned_data, True
        chosen = set(procedures)
        for name in ("block_graft", "membrane_used", "sutured", "soft_tissue_graft"):
            if data.get(name):
                chosen.add(name)
        for part, names in self.NEEDED:
            if part not in chosen:
                continue
            for name in names:
                if data.get(name) in (None, "") and name not in self.errors:
                    self.add_error(name, _("Needed: %(part)s was chosen.") % {"part": NEEDED_LABELS[part]})
                    ok = False
        return ok


NEEDED_LABELS = {"gbr": _("GBR"), "open_sinus": _("an open sinus lift"), "block_graft": _("a block graft"),
                 "membrane_used": _("a membrane"), "sutured": _("the suture"),
                 "soft_tissue_graft": _("a soft tissue graft")}


def _option_names(kind):
    def names():
        return [str(o) for o in SurgeryOption.objects.filter(kind=kind, is_active=True)]
    return names


class SurgerySiteForm(BootstrapFormMixin, forms.ModelForm):
    tooth = forms.TypedChoiceField(label=_("tooth"), choices=[("", "—")] + TOOTH_CHOICES, coerce=int,
                                   widget=forms.Select(attrs={"data-teeth-picker": "single"}))
    operator = DentistChoiceField(label=_("operator of this tooth"), required=False, empty_label=_("operator 1"))
    stock_choice = forms.ChoiceField(
        label=_("implant from stock (lot)"), required=False,
        help_text=_("Choose the company, then the implant in stock: its size and lot are filled in and it is taken out of stock."))

    class Meta:
        model = SurgerySite
        fields = [
            "tooth", "operator", "extraction", "flap", "simple_implant", "immediate_implant", "expansion", "splitting",
            "closed_sinus", "open_sinus", "gbr", "guided", "implant_system", "implant_diameter", "implant_length",
            "lot_number", "sticker", "insertion_torque", "isq", "subcrestal", "notes",
        ]

    def __init__(self, *args, branch=None, **kwargs):
        self.branch = branch  # the surgery's place: its own implants and the shared ones are offered
        super().__init__(*args, **kwargs)
        self.fields["implant_system"].queryset = ImplantSystem.objects.filter(is_active=True)
        self.fields["sticker"].validators.append(validate_upload)
        self.fields["sticker"].widget.attrs["accept"] = "image/*"
        for name in ("implant_diameter", "implant_length"):
            self.fields[name].widget.attrs.update({"step": "any", "min": "2", "max": "20"})
        self._stock_choices()

    def _stock_choices(self):
        """Lots in stock of the chosen company; the lot this tooth already took stays in the list."""
        from apps.stock.implants import choice_value, lot_choices

        instance = self.instance
        keep = (instance.implant_stock_item_id, instance.lot_number) if instance.implant_stock_item_id else None
        system = self.data.get(self.add_prefix("implant_system")) if self.is_bound else instance.implant_system_id
        rows = lot_choices(system=system, keep=keep, branch=self.branch) if system else []
        self.stock_rows = rows
        self.fields["stock_choice"].choices = [("", _("not from stock"))] + [(r["value"], r["label"]) for r in rows]
        self.fields["stock_choice"].widget.attrs["data-stock-lots"] = ""
        if keep:
            self.fields["stock_choice"].initial = choice_value(*keep)

    def clean(self):
        data = super().clean()
        from apps.stock.implants import parse_choice
        from apps.stock.models import StockItem

        chosen = parse_choice(data.get("stock_choice"))
        self.stock_key = None
        if chosen is None:
            self.instance.implant_stock_item = None
        else:
            item = StockItem.objects.filter(pk=chosen[0]).select_related("implant_system").first()
            if item is None or not item.is_implant:
                self.add_error("stock_choice", _("This implant is not in stock."))
            else:
                size = (data.get("implant_system"), data.get("implant_diameter"), data.get("implant_length"))
                if size != (item.implant_system, item.implant_diameter, item.implant_length):
                    self.add_error("stock_choice", _("The implant from stock is %(item)s: choose the same company and size, or another lot.")
                                   % {"item": f"{item.implant_system} {item.implant_diameter:g} x {item.implant_length:g}"})
                self.instance.implant_stock_item = item
                data["lot_number"] = chosen[1]
                self.stock_key = (item.pk, chosen[1])
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
    team = ()  # operator 1 and operator 2, set by the view: a tooth's operator must be one of them

    def clean(self):
        teeth = []
        duplicate = False
        for form in self.forms:
            data = getattr(form, "cleaned_data", None)
            if not data or data.get("DELETE") or not data.get("tooth"):
                continue
            if data.get("operator") and self.team and data["operator"] not in self.team:
                form.add_error("operator", _("Choose operator 1 or operator 2 of this surgery."))
            tooth = data["tooth"]
            if tooth in teeth:
                form.add_error("tooth", _("Tooth %(tooth)s is written twice.") % {"tooth": tooth})
                duplicate = True
            teeth.append(tooth)
        if duplicate:
            return  # the message on the repeated tooth replaces Django's generic "duplicate values" one
        self._check_stock()
        super().clean()
        if not teeth:
            raise forms.ValidationError(_("Add at least one tooth to the surgery chart."))


    def _check_stock(self):
        """Two teeth cannot take the last implant of a lot."""
        from apps.stock.implants import available

        wanted = {}
        for form in self.forms:
            data = getattr(form, "cleaned_data", None)
            key = getattr(form, "stock_key", None)
            if not data or data.get("DELETE") or key is None:
                continue
            movement = form.instance.stock_movement if form.instance.stock_movement_id else None
            if movement is None or (movement.item_id, movement.lot) != key:  # not already taken for this tooth
                wanted.setdefault(key, []).append(form)
        for (item_id, lot), forms_ in wanted.items():
            left = available(item_id, lot)
            if len(forms_) > left:
                for form in forms_:
                    form.add_error("stock_choice", _("Only %(n)s left of this lot.") % {"n": f"{left:g}"})


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


class ImplantCheckboxes(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        status = obj.get_implant_status_display()
        return f"{obj.tooth} — {obj.implant_label}" + (f" ({status})" if status else "")


class ProsthesisForm(StyledModelForm):
    implants = ImplantCheckboxes(label=_("on the implants"), queryset=SurgerySite.objects.none(),
                                 widget=forms.CheckboxSelectMultiple)
    dentist = DentistChoiceField(label=_("dentist"), required=False)

    fieldsets = [
        ("", ["kind", "jaw", "teeth", "implants"]),
        (_("Details"), ["retention", "material", "is_temporary", "status", "delivered_on", "dentist", "lab_request",
                        "notes"]),
    ]

    class Meta:
        model = Prosthesis
        fields = ["kind", "jaw", "teeth", "implants", "retention", "material", "is_temporary", "status",
                  "delivered_on", "dentist", "lab_request", "notes"]

    def __init__(self, *args, patient, **kwargs):
        from apps.charting.sync import missing_teeth

        super().__init__(*args, **kwargs)
        self.patient = patient
        self.fields["implants"].queryset = (
            SurgerySite.objects.filter(surgery__patient=patient).exclude(implant_status__in=["", SurgerySite.ImplantStatus.FAILED])
            .select_related("implant_system").order_by("tooth"))
        self.fields["lab_request"].queryset = patient.lab_requests.select_related("work_type").order_by("-pk")
        self.fields["teeth"].widget.attrs.update({"data-teeth-picker": "multi", "data-digits": "1",
                                                  "data-teeth-missing": ",".join(str(t) for t in missing_teeth(patient))})
        for name in ("kind", "jaw", "retention", "material", "status", "delivered_on"):
            self.fields[name].col = "col-md-4"
        self.fields["teeth"].col = "col-md-4"
        self.fields["delivered_on"].help_text = _("Delivered: the implants are marked as loaded on this day.")

    def clean_teeth(self):
        from apps.charting.teeth import format_teeth, parse_teeth

        return format_teeth(parse_teeth(self.cleaned_data.get("teeth")))

    def clean(self):
        from apps.charting.teeth import LOWER, UPPER, format_teeth, parse_teeth

        data = super().clean()
        kind, implants = data.get("kind"), list(data.get("implants") or [])
        teeth = parse_teeth(data.get("teeth")) if data.get("teeth") else []
        implant_teeth = sorted(site.tooth for site in implants)
        if not implants:
            return data
        K = Prosthesis.Kind
        if kind == K.SINGLE:
            if len(implants) != 1:
                self.add_error("implants", _("A single crown sits on one implant."))
            elif not teeth:
                data["teeth"] = format_teeth(implant_teeth)
            elif teeth != implant_teeth:
                self.add_error("teeth", _("A single crown replaces the tooth of its implant."))
        elif kind == K.BRIDGE:
            teeth = sorted(set(teeth) | set(implant_teeth))
            if len(teeth) < 2:
                self.add_error("teeth", _("Write all the teeth of the bridge, e.g. 34-37."))
            elif not (set(teeth) <= set(UPPER) or set(teeth) <= set(LOWER)):
                self.add_error("teeth", _("A bridge is in one jaw."))
            data["teeth"] = format_teeth(teeth)
        elif kind in Prosthesis.FULL_ARCH:
            jaw = data.get("jaw")
            if not jaw:
                self.add_error("jaw", _("Choose the jaw of the full arch."))
            else:
                arch = UPPER if jaw == Prosthesis.Jaw.UPPER else LOWER
                if any(tooth not in arch for tooth in implant_teeth):
                    self.add_error("implants", _("Choose implants of this jaw only."))
                if teeth and any(tooth not in arch for tooth in teeth):
                    self.add_error("teeth", _("Choose teeth of this jaw only."))
            if kind == K.FULL_FIXED and len(implants) < 2:
                self.add_error("implants", _("A fixed full arch needs at least 2 implants."))
        if data.get("status") == Prosthesis.Status.DELIVERED and not data.get("delivered_on"):
            data["delivered_on"] = timezone.localdate()
        return data


class DeliveryCheckForm(StyledModelForm):
    """The written part of the delivery checklist (the points themselves are ticks on the page)."""

    dentist = DentistChoiceField(label=_("dentist"), required=False)

    class Meta:
        model = DeliveryCheck
        fields = ["date", "dentist", "torque_ncm", "shade", "follow_up_on", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("date", "dentist", "torque_ncm", "shade", "follow_up_on"):
            self.fields[name].col = "col-6 col-md-4"
        self.fields["torque_ncm"].widget.attrs.update({"inputmode": "numeric", "placeholder": "35"})


# ------------------------------------------------------------------ the life of an implant (round 15)
YES_NO = [("", "—"), ("true", _("Yes")), ("false", _("No"))]


class _YesNo(forms.NullBooleanField):
    def __init__(self, **kwargs):
        super().__init__(widget=forms.Select(choices=YES_NO), **kwargs)


class ImplantFollowUpForm(StyledModelForm):
    """One check of an implant: the findings, then the class of the tissues (found from them when left empty)."""

    dentist = DentistChoiceField(label=_("dentist"), required=False)
    bleeding = _YesNo(label=_("bleeding on probing"), required=False)
    suppuration = _YesNo(label=_("suppuration (pus)"), required=False)
    mobility = _YesNo(label=_("mobility of the implant"), required=False)
    plaque = _YesNo(label=_("plaque"), required=False)

    fieldsets = [
        ("", ["checked_on", "dentist"]),
        (_("Findings"), ["probing_depth", "bleeding", "suppuration", "mobility", "plaque", "keratinized_mm",
                         "isq", "xray_taken", "bone_loss"]),
        (_("Result"), ["status", "notes", "next_check"]),
    ]

    class Meta:
        model = ImplantFollowUp
        fields = ["checked_on", "dentist", "probing_depth", "bleeding", "suppuration", "mobility", "plaque",
                  "keratinized_mm", "isq", "xray_taken", "bone_loss", "status", "notes", "next_check"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("checked_on", "dentist", "next_check"):
            self.fields[name].col = "col-md-6"
        for name in ("probing_depth", "bleeding", "suppuration", "mobility", "plaque", "keratinized_mm", "isq",
                     "bone_loss"):
            self.fields[name].col = "col-6 col-md-3"
        self.fields["xray_taken"].col = "col-6 col-md-3"
        self.fields["status"].help_text = _("Empty: found from the findings (bleeding or pus = mucositis; with bone "
                                            "loss of 3 mm or more = peri-implantitis).")
        self.fields["status"].col = "col-md-6"


class ImplantComplicationForm(StyledModelForm):
    """A complication of an implant, in detail (for the follow-up and for papers)."""

    dentist = DentistChoiceField(label=_("found by"), required=False)

    fieldsets = [
        (_("The complication"), ["kind", "found_on", "timing", "severity", "dentist", "signs", "cause"]),
        (_("Nerve injury"), ["nerve", "side", "area", "sensory_test"]),
        (_("Treatment and outcome"), ["treatment", "treatment_notes", "outcome", "resolved_on", "next_check",
                                      "notes"]),
    ]

    class Meta:
        model = ImplantComplication
        fields = ["kind", "found_on", "timing", "severity", "dentist", "signs", "cause", "nerve", "side", "area",
                  "sensory_test", "treatment", "treatment_notes", "outcome", "resolved_on", "next_check", "notes"]
        widgets = {"signs": forms.Textarea(attrs={"rows": 2}), "treatment_notes": forms.Textarea(attrs={"rows": 2}),
                   "notes": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # The kinds in their groups (biological, surgical, nerve...), as an optgroup list.
        groups = dict(ImplantComplication.Group.choices)
        grouped = {}
        for code, label, group in ImplantComplication.KINDS:
            grouped.setdefault(groups.get(group, _("Other")), []).append((code, label))
        self.fields["kind"].choices = [("", "---------")] + [(title, rows) for title, rows in grouped.items()]
        for name in ("kind", "found_on", "timing", "severity", "dentist", "nerve", "side", "treatment", "outcome",
                     "resolved_on", "next_check"):
            self.fields[name].col = "col-md-6 col-lg-4"
        for name in ("area", "sensory_test", "cause"):
            self.fields[name].col = "col-md-6"
        # The nerve's boxes show for a nerve injury only (static/js/app.js).
        self.fields["kind"].widget.attrs["data-nerve-kinds"] = ",".join(
            code for code, _label, group in ImplantComplication.KINDS if group == "nerve")

    def clean(self):
        data = super().clean()
        if ImplantComplication.KIND_GROUP.get(data.get("kind")) == "nerve" and not data.get("nerve"):
            self.add_error("nerve", _("Choose the nerve."))
        if data.get("outcome") in (ImplantComplication.Outcome.RESOLVED, ImplantComplication.Outcome.IMPLANT_LOST) \
                and data.get("resolved_on") and data.get("found_on") and data["resolved_on"] < data["found_on"]:
            self.add_error("resolved_on", _("It cannot end before it was found."))
        return data


class ComplicationFilterForm(StyledForm):
    """The complications finder (for papers): by group, kind, timing, outcome, implant, operator, dates."""

    date_from = forms.DateField(label=_("From"), required=False)
    date_to = forms.DateField(label=_("To"), required=False)
    group = forms.ChoiceField(label=_("group"), required=False,
                              choices=[("", _("All"))] + list(ImplantComplication.Group.choices))
    kind = forms.ChoiceField(label=_("complication"), required=False,
                             choices=[("", _("All"))] + ImplantComplication.KIND_CHOICES)
    timing = forms.ChoiceField(label=_("when it showed"), required=False,
                               choices=[("", _("All"))] + list(ImplantComplication.Timing.choices))
    outcome = forms.ChoiceField(label=_("outcome"), required=False,
                                choices=[("", _("All"))] + list(ImplantComplication.Outcome.choices))
    system = forms.ModelChoiceField(label=_("implant type"), required=False, queryset=ImplantSystem.objects.all(),
                                    empty_label=_("All"))
    operator = DentistChoiceField(everyone=True, label=_("operator"), required=False, empty_label=_("All"))
