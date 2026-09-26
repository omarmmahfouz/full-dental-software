from django import forms
from django.forms import BaseInlineFormSet, inlineformset_factory
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.charting.teeth import TOOTH_CHOICES
from apps.core.forms import BootstrapFormMixin, StyledModelForm, validate_upload
from apps.dentists.forms import DentistChoiceField
from apps.dentists.models import Dentist
from apps.patients.access import visible_patients
from apps.patients.forms import PatientLookupField, lookup_value

from .models import ImplantSystem, Prosthesis, Surgery, SurgerySite


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
            self.fields["patient_lookup"].initial = lookup_value(patient)
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["implant_system"].queryset = ImplantSystem.objects.filter(is_active=True)
        self.fields["sticker"].validators.append(validate_upload)
        self.fields["sticker"].widget.attrs["accept"] = "image/*"
        for name in ("implant_diameter", "implant_length"):
            self.fields[name].widget.attrs.update({"step": "0.1", "min": "2", "max": "20"})
        self._stock_choices()

    def _stock_choices(self):
        """Lots in stock of the chosen company; the lot this tooth already took stays in the list."""
        from apps.stock.implants import choice_value, lot_choices

        instance = self.instance
        keep = (instance.implant_stock_item_id, instance.lot_number) if instance.implant_stock_item_id else None
        system = self.data.get(self.add_prefix("implant_system")) if self.is_bound else instance.implant_system_id
        rows = lot_choices(system=system, keep=keep) if system else []
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
