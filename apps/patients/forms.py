from django import forms
from django.db.models import Q
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.forms import (
    StyledForm,
    StyledModelForm,
    clean_digits_value,
    clean_phone_value,
    validate_upload,
)
from apps.core.utils import normalize_phone, parse_egyptian_national_id
from apps.core.widgets import AutocompleteInput

from apps.dentists.forms import DentistChoiceField

from .models import (
    Lead, LeadCall, MedicalCondition, OutReason, Patient, PatientDocument, PatientRelation, ReferralSource,
)


def lookup_value(patient):
    """What a patient box shows when the patient is already chosen: the file number and the name."""
    return f"{patient.file_number} — {patient.full_name}"


def find_patient(value):
    """Find one patient by file number, mobile or national ID (as typed at the desk)."""
    if value and " — " in value:  # "CIA-00014 — name", as filled in for a chosen patient
        value = value.split(" — ", 1)[0]
    value = clean_digits_value(value)
    if not value:
        return None
    phone = normalize_phone(value)
    query = Q(file_number__iexact=value) | Q(national_id=value)
    if phone:
        query |= Q(phone_primary=phone) | Q(phone_secondary=phone)
    matches = list(Patient.objects.filter(query)[:2])
    if not matches:
        # The full name, typed exactly, when only one patient has it.
        matches = list(Patient.objects.filter(full_name__iexact=value)[:2])
    return matches[0] if len(matches) == 1 else None


class PatientLookupField(forms.CharField):
    """A box where the secretary types a patient's name, mobile, file number or ID and
    chooses from the suggestions."""

    def __init__(self, **kwargs):
        kwargs.setdefault("max_length", 150)
        kwargs.setdefault("help_text", _("Type the name, mobile, file number or national ID and choose the patient."))
        kwargs.setdefault("widget", AutocompleteInput(reverse_lazy("patients:lookup"), attrs={
            "placeholder": _("name, mobile or file number")}))
        super().__init__(**kwargs)

    def clean(self, value):
        value = super().clean(value)
        if not value:
            return None
        patient = find_patient(value)
        if patient is None:
            raise forms.ValidationError(_("No patient found with this file number, mobile or ID."))
        return patient


def duplicate_phone_error(phone, exclude_patient=None, exclude_lead=None):
    """Explain who already owns a phone number (patients and the call list)."""
    patients = Patient.objects.filter(Q(phone_primary=phone) | Q(phone_secondary=phone))
    if exclude_patient is not None and exclude_patient.pk:
        patients = patients.exclude(pk=exclude_patient.pk)
    patient = patients.first()
    if patient:
        return _("This mobile belongs to the registered patient %(name)s (file %(file)s).") % {
            "name": patient.full_name, "file": patient.file_number,
        }
    if exclude_lead is not False:
        leads = Lead.objects.filter(phone_primary=phone)
        if exclude_lead is not None and exclude_lead.pk:
            leads = leads.exclude(pk=exclude_lead.pk)
        lead = leads.first()
        if lead:
            return _("This mobile is already in the call list under the name %(name)s.") % {"name": lead.full_name}
    return None


def _phone_check_url(kind, instance, name):
    field = "secondary" if name.endswith("secondary") else "primary"
    return f"{reverse('patients:phone_check')}?kind={kind}&pk={instance.pk or ''}&field={field}"


class LeadForm(StyledModelForm):
    fieldsets = [
        (_("Caller"), ["full_name", "phone_primary", "phone_secondary", "preferred_phone", "age", "gender", "city"]),
        (_("Teeth and health (as told by the caller)"),
         ["missing_teeth", "missing_teeth_notes", "medical_conditions", "medical_notes"]),
        (_("Follow-up"), ["first_call_on", "referral_source", "referral_notes", "status", "notes"]),
    ]

    class Meta:
        model = Lead
        fields = [
            "full_name", "phone_primary", "phone_secondary", "preferred_phone", "age", "gender", "city",
            "missing_teeth", "missing_teeth_notes", "medical_conditions", "medical_notes",
            "first_call_on", "referral_source", "referral_notes", "status", "notes",
        ]
        widgets = {"medical_conditions": forms.CheckboxSelectMultiple}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["medical_conditions"].queryset = MedicalCondition.objects.filter(is_active=True)
        self.fields["referral_source"].queryset = ReferralSource.objects.filter(is_active=True)
        for name in ("phone_primary", "phone_secondary"):
            self.fields[name].widget.input_type = "tel"
            self.fields[name].widget.attrs["data-phone-check-url"] = _phone_check_url("lead", self.instance, name)
        self.fields["age"].widget.attrs.update({"min": 1, "max": 110})
        self.fields["first_call_on"].required = False
        if not self.instance.pk:
            self.fields["status"].choices = [
                c for c in Lead.Status.choices if c[0] != Lead.Status.CONVERTED
            ]

    def clean_first_call_on(self):
        return self.cleaned_data.get("first_call_on") or timezone.localdate()

    def clean_phone_primary(self):
        phone = clean_phone_value(self.cleaned_data["phone_primary"])
        error = duplicate_phone_error(phone, exclude_lead=self.instance)
        if error:
            raise forms.ValidationError(error)
        return phone

    def clean_phone_secondary(self):
        return clean_phone_value(self.cleaned_data.get("phone_secondary"), mobile_only=False)


class LeadCallForm(StyledModelForm):
    new_status = forms.ChoiceField(label=_("change status to"), required=False)

    class Meta:
        model = LeadCall
        fields = ["called_at", "outcome", "notes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["new_status"].choices = [("", _("— keep current —"))] + [
            c for c in Lead.Status.choices if c[0] != Lead.Status.CONVERTED
        ]
        self.fields["called_at"].initial = timezone.localtime().replace(second=0, microsecond=0)
        self.fields["notes"].widget.attrs["rows"] = 2
        for name in self.fields:
            self.fields[name].col = "col-md-6"
        self.fields["notes"].col = "col-12"


class PatientForm(StyledModelForm):
    referred_by_lookup = PatientLookupField(
        label=_("referring patient"), required=False,
        help_text=_("If referred by one of our patients: type their file number or mobile."),
    )
    relative_lookup = PatientLookupField(
        label=_("relative / friend who is our patient"), required=False,
        help_text=_("Optional: type the file number or mobile of a relative or friend already registered."),
    )
    relative_relation = forms.ChoiceField(
        label=_("relation"), required=False, choices=[("", "—")] + list(PatientRelation.Relation.choices)
    )
    id_front = forms.FileField(
        label=_("ID scan - front"), required=False, validators=[validate_upload],
        help_text=_("Scanned image or photo (JPG, PNG or PDF)."),
    )
    id_back = forms.FileField(label=_("ID scan - back"), required=False, validators=[validate_upload])
    assigned_dentist = DentistChoiceField(label=_("responsible dentist"), required=False)

    fieldsets = [
        (_("Personal data"), ["full_name", "id_type", "national_id", "birth_date", "gender", "marital_status", "occupation"]),
        (_("Contact"), ["phone_primary", "phone_secondary", "preferred_phone", "governorate", "city", "address"]),
        (_("ID scan"), ["id_front", "id_back"]),
        (_("Teeth and medical history (as told by the patient)"),
         ["missing_teeth", "missing_teeth_notes", "medical_conditions", "medical_notes"]),
        (_("Who referred you?"), ["referral_source", "referred_by_lookup", "referral_notes"]),
        (_("Relatives or friends among our patients"), ["relative_lookup", "relative_relation"]),
        (_("Follow-up"), ["registered_on", "assigned_dentist", "status", "out_reason", "out_notes", "notes"]),
    ]

    class Meta:
        model = Patient
        fields = [
            "full_name", "id_type", "national_id", "birth_date", "gender", "marital_status", "occupation",
            "phone_primary", "phone_secondary", "preferred_phone", "governorate", "city", "address",
            "missing_teeth", "missing_teeth_notes", "medical_conditions", "medical_notes",
            "referral_source", "referral_notes", "registered_on", "assigned_dentist", "status", "out_reason",
            "out_notes", "notes",
        ]
        widgets = {"medical_conditions": forms.CheckboxSelectMultiple}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["medical_conditions"].queryset = MedicalCondition.objects.filter(is_active=True)
        self.fields["referral_source"].queryset = ReferralSource.objects.filter(is_active=True)
        self.fields["referral_source"].required = True
        for name in ("phone_primary", "phone_secondary"):
            self.fields[name].widget.input_type = "tel"
            self.fields[name].widget.attrs["data-phone-check-url"] = _phone_check_url("patient", self.instance, name)
        self.fields["national_id"].widget.attrs.update({"data-digits": "1", "autocomplete": "off"})
        self.fields["birth_date"].help_text = _("Filled automatically from the national ID.")
        self.fields["gender"].help_text = _("Filled automatically from the national ID.")
        self.fields["governorate"].help_text = _("Filled automatically from the national ID.")
        self.fields["registered_on"].required = False
        for name in ("id_front", "id_back"):
            self.fields[name].widget.attrs["accept"] = "image/*,application/pdf"
        if self.instance.pk:
            # Documents and relations are managed from the patient file after registration.
            for name in ("id_front", "id_back", "relative_lookup", "relative_relation"):
                del self.fields[name]
            if self.instance.referred_by_id:
                self.fields["referred_by_lookup"].initial = self.instance.referred_by.file_number
            self.fields["out_reason"].queryset = OutReason.objects.filter(is_active=True)
            self.fields["out_reason"].help_text = _("Needed when the status is “Out”.")
        else:
            for name in ("status", "out_reason", "out_notes"):
                del self.fields[name]

    def clean_national_id(self):
        value = clean_digits_value(self.cleaned_data.get("national_id")).upper().replace(" ", "")
        if self.cleaned_data.get("id_type") == Patient.IdType.NATIONAL_ID:
            self._nid_data = parse_egyptian_national_id(value)
        existing = Patient.objects.filter(national_id=value).exclude(pk=self.instance.pk).first()
        if existing:
            raise forms.ValidationError(
                _("This ID is already registered for %(name)s (file %(file)s). Do not create a second file.")
                % {"name": existing.full_name, "file": existing.file_number}
            )
        return value

    def clean_registered_on(self):
        return self.cleaned_data.get("registered_on") or self.instance.registered_on or timezone.localdate()

    def clean_phone_primary(self):
        phone = clean_phone_value(self.cleaned_data.get("phone_primary"))
        error = duplicate_phone_error(phone, exclude_patient=self.instance, exclude_lead=False)
        if error:
            raise forms.ValidationError(error)
        return phone

    def clean_phone_secondary(self):
        return clean_phone_value(self.cleaned_data.get("phone_secondary"), mobile_only=False)

    def clean(self):
        data = super().clean()
        nid = getattr(self, "_nid_data", None)
        if nid:
            data["birth_date"] = data.get("birth_date") or nid["birth_date"]
            data["gender"] = data.get("gender") or nid["gender"]
            data["governorate"] = data.get("governorate") or nid["governorate_code"]
            if data["birth_date"] != nid["birth_date"]:
                self.add_error("birth_date", _("The date of birth does not match the national ID."))
        if data.get("phone_primary") and data.get("phone_primary") == data.get("phone_secondary"):
            self.add_error("phone_secondary", _("The second mobile is the same as the first one."))
        source = data.get("referral_source")
        referred_by = data.get("referred_by_lookup")
        if source and source.asks_for_patient and not referred_by:
            self.add_error("referred_by_lookup", _("Type the file number or mobile of the referring patient."))
        if referred_by and self.instance.pk and referred_by.pk == self.instance.pk:
            self.add_error("referred_by_lookup", _("A patient cannot refer himself."))
        if data.get("relative_lookup") and not data.get("relative_relation"):
            self.add_error("relative_relation", _("Choose the relation."))
        if "status" in self.fields:
            if data.get("status") == Patient.Status.OUT and not data.get("out_reason"):
                self.add_error("out_reason", _("Choose why the patient is out."))
            elif data.get("status") != Patient.Status.OUT:
                data["out_reason"], data["out_notes"] = None, ""
        return data

    def save(self, commit=True):
        self.instance.referred_by = self.cleaned_data.get("referred_by_lookup")
        return super().save(commit=commit)


class PatientDocumentForm(StyledModelForm):
    class Meta:
        model = PatientDocument
        fields = ["kind", "file", "notes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["file"].validators.append(validate_upload)
        self.fields["file"].widget.attrs["accept"] = "image/*,application/pdf"
        for field in self.fields.values():
            field.col = "col-md-4"


class PatientRelationForm(StyledModelForm):
    related_lookup = PatientLookupField(label=_("related patient"))

    class Meta:
        model = PatientRelation
        fields = ["relation", "notes"]

    def __init__(self, *args, patient=None, **kwargs):
        self.patient = patient
        super().__init__(*args, **kwargs)
        self.order_fields(["related_lookup", "relation", "notes"])
        for field in self.fields.values():
            field.col = "col-md-4"

    def clean_related_lookup(self):
        other = self.cleaned_data["related_lookup"]
        if other.pk == self.patient.pk:
            raise forms.ValidationError(_("A patient cannot be related to himself."))
        exists = PatientRelation.objects.filter(
            Q(patient=self.patient, related_patient=other) | Q(patient=other, related_patient=self.patient)
        ).exists()
        if exists:
            raise forms.ValidationError(_("This relation is already recorded."))
        return other


class PatientFilterForm(StyledForm):
    q = forms.CharField(label=_("Search"), required=False)
    status = forms.ChoiceField(
        label=_("status"), required=False, choices=[("", _("All"))] + list(Patient.Status.choices)
    )
    dentist = DentistChoiceField(label=_("dentist"), required=False, empty_label=_("All"))
    lab = forms.BooleanField(label=_("has open lab work"), required=False)
    mine = forms.BooleanField(label=_("only my patients"), required=False)
