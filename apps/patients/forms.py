import re

from django import forms
from django.conf import settings
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
from apps.core.models import current_place
from apps.core.utils import normalize_phone, parse_egyptian_national_id
from apps.core.egypt import cities_json
from apps.core.widgets import (
    AutocompleteInput, ChoiceButtons, CommaChecksWidget, DatalistInput, KeptPhotoInput, WeekdaysWidget,
)

from apps.dentists.forms import DentistChoiceField

from .models import (
    DayPart, Lead, LeadCall, MedicalCondition, MedicalConsult, OutReason, Patient, PatientDocument, PatientRelation,
    ReferralSource,
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
    patients = Patient.objects.here()  # only the patients of the place worked in
    matches = list(patients.filter(query)[:2])
    if not matches:
        # The full name, typed exactly, when only one patient has it.
        matches = list(patients.filter(full_name__iexact=value)[:2])
    return matches[0] if len(matches) == 1 else None


# Arabic letters (with their marks) and spaces only: the name as written on the Egyptian ID.
ARABIC_NAME = re.compile(r"^[\u0621-\u063A\u0640-\u0652\u0670-\u06D3 ]+$")


def clean_arabic_name(value):
    """A patient's full name: in Arabic letters, at least three names (the person, the father, the grandfather)."""
    name = " ".join((value or "").split())
    if not ARABIC_NAME.match(name):
        raise forms.ValidationError(_("Write the name in Arabic letters only, as on the ID."))
    if len(name.split()) < 3:
        raise forms.ValidationError(_("Write at least three names (the patient, the father and the grandfather), "
                                      "as on the ID."))
    return name


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
    """Explain who already owns a phone number (the patients of the place worked in, and the call list)."""
    patients = Patient.objects.here().filter(Q(phone_primary=phone) | Q(phone_secondary=phone))
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
        help_text=_("Optional: if you know which of our patients sent him, type the name, file number or mobile."),
    )
    relative_lookup = PatientLookupField(
        label=_("relative / friend who is our patient"), required=False,
        help_text=_("Optional: type the file number or mobile of a relative or friend already registered."),
    )
    relative_relation = forms.ChoiceField(
        label=_("relation"), required=False, choices=[("", "—")] + list(PatientRelation.Relation.choices)
    )
    id_front = forms.FileField(
        label=_("ID scan - front"), required=False, validators=[validate_upload], widget=KeptPhotoInput,
        help_text=_("Take it with the camera (the card is cut out and read) or choose a scan (JPG, PNG or PDF)."),
    )
    id_back = forms.FileField(label=_("ID scan - back"), required=False, validators=[validate_upload],
                              widget=KeptPhotoInput)
    assigned_dentist = DentistChoiceField(label=_("responsible dentist"), required=False)
    brought_by = DentistChoiceField(label=_("the doctor's own patient (brought by)"), required=False,
                                    empty_label=_("No: a patient of the clinic"))

    # Required at registration (round 13). The date of birth, the gender and the governorate are read from the
    # national ID when left empty, so they are checked in clean() after that.
    REQUIRED = ["phone_secondary", "marital_status", "occupation", "city"]
    FROM_ID = ["birth_date", "gender", "governorate"]
    ID_PHOTOS = ["id_front", "id_back"]

    fieldsets = [
        (_("ID scan"), ["id_front", "id_back"]),
        (_("Personal data"), ["full_name", "id_type", "national_id", "birth_date", "gender", "marital_status", "occupation"]),
        (_("Contact"), ["phone_primary", "phone_secondary", "preferred_phone", "governorate", "city", "address"]),
        (_("Visits"), ["travel_minutes", "preferred_days", "preferred_times"]),
        (_("Teeth and medical history (as told by the patient)"),
         ["missing_teeth", "missing_teeth_notes", "medical_conditions", "medical_notes"]),
        (_("Who referred you?"), ["referral_source", "referred_by_lookup", "referral_notes", "brought_by"]),
        (_("Relatives or friends among our patients"), ["relative_lookup", "relative_relation"]),
        (_("Follow-up"), ["registered_on", "assigned_dentist", "status", "out_reason", "out_notes", "notes"]),
    ]
    # Optional at the desk: the dentist takes the medical and dental history (round 10).
    folded = [_("Teeth and medical history (as told by the patient)"), _("Relatives or friends among our patients")]

    class Meta:
        model = Patient
        fields = [
            "full_name", "id_type", "national_id", "birth_date", "gender", "marital_status", "occupation",
            "phone_primary", "phone_secondary", "preferred_phone", "governorate", "city", "address",
            "travel_minutes", "preferred_days", "preferred_times",
            "missing_teeth", "missing_teeth_notes", "medical_conditions", "medical_notes",
            "referral_source", "referral_notes", "brought_by", "registered_on", "assigned_dentist", "status",
            "out_reason", "out_notes", "notes",
        ]
        widgets = {"medical_conditions": forms.CheckboxSelectMultiple, "preferred_days": WeekdaysWidget,
                   "preferred_times": CommaChecksWidget(choices=DayPart.choices)}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["medical_conditions"].queryset = MedicalCondition.objects.filter(is_active=True)
        self.fields["referral_source"].queryset = ReferralSource.objects.filter(is_active=True)
        self.fields["referral_source"].required = True
        for name in self.REQUIRED:
            self.fields[name].required = True
        for name in self.FROM_ID:
            self.fields[name].required = False
            self.fields[name].marked_required = True
        for name in ("phone_primary", "phone_secondary"):
            self.fields[name].widget.input_type = "tel"
            self.fields[name].widget.attrs["data-phone-check-url"] = _phone_check_url("patient", self.instance, name)
        self.fields["national_id"].widget.attrs.update({"data-digits": "1", "autocomplete": "off",
                                                        "data-nid-fills": "1"})
        self.fields["full_name"].widget.attrs.update({"lang": "ar", "dir": "rtl", "autocomplete": "off"})
        self.fields["full_name"].help_text = _("In Arabic, at least three names, as on the ID.")
        self.fields["birth_date"].help_text = _("Filled automatically from the national ID.")
        self.fields["gender"].help_text = _("Filled automatically from the national ID.")
        self.fields["governorate"].help_text = _("Filled automatically from the national ID: change it if he lives "
                                                 "in another governorate.")
        self.fields["city"].help_text = _("The list follows the governorate. Not on the list: choose “Other”.")
        self.fields["city"].widget.attrs.update({
            "data-city-list": cities_json(), "data-governorate": "governorate",
            "data-choose-label": _("— choose —"), "data-other-label": _("Other: write the area")})
        self.fields["occupation"].widget = DatalistInput(OCCUPATIONS, attrs=self.fields["occupation"].widget.attrs)
        self.fields["travel_minutes"].widget.attrs.update({"min": 0, "max": 600, "step": 5, "inputmode": "numeric"})
        self.fields["travel_minutes"].help_text = Patient._meta.get_field("travel_minutes").help_text
        self.fields["preferred_days"].help_text = _("Empty = any day.")
        self.fields["preferred_times"].help_text = _("Empty = any time.")
        for name in ("preferred_days", "preferred_times"):
            self.fields[name].col = "col-md-6 col-lg-4"
        self.fields["travel_minutes"].col = "col-md-6 col-lg-4"
        self.fields["registered_on"].required = False
        # At a clinic (El Khadem, CIC) a doctor may bring his own patient: it decides his share.
        place = self.instance.branch if self.instance.pk else current_place()
        if place is None or place.kind != place.Kind.CLINIC:
            del self.fields["brought_by"]
        else:
            self.fields["brought_by"].queryset = self.fields["brought_by"].queryset.working_at(place)
            self.fields["brought_by"].help_text = Patient._meta.get_field("brought_by").help_text
        for name, side in (("id_front", "front"), ("id_back", "back")):
            # data-id-card: the camera or the photo is checked, the card cut out and read (static/js/idcard.js).
            self.fields[name].widget.attrs.update({"accept": "image/*,application/pdf", "data-id-card": side})
            self.fields[name].col = "col-md-6"
        if self.instance.pk:
            # Relations are managed from the patient file after registration; new ID photos can be added here.
            for name in ("relative_lookup", "relative_relation"):
                del self.fields[name]
            self.fields["id_front"].help_text = _("Only to add or replace the photo: the ones saved stay in the file.")
            if self.instance.referred_by_id:
                self.fields["referred_by_lookup"].initial = lookup_value(self.instance.referred_by)
            self.fields["out_reason"].queryset = OutReason.objects.filter(is_active=True)
            self.fields["out_reason"].help_text = _("Needed when the status is “Out”.")
        else:
            for name in ("status", "out_reason", "out_notes"):
                del self.fields[name]

    def clean_national_id(self):
        value = clean_digits_value(self.cleaned_data.get("national_id")).upper().replace(" ", "")
        if self.cleaned_data.get("id_type") == Patient.IdType.NATIONAL_ID:
            self._nid_data = parse_egyptian_national_id(value)
        others = Patient.objects.filter(national_id=value).exclude(pk=self.instance.pk).select_related("branch")
        place = self.instance.branch if self.instance.pk else current_place()
        existing = others.filter(branch=place).first() if place is not None else others.first()
        if existing:
            raise forms.ValidationError(
                _("This ID is already registered for %(name)s (file %(file)s). Do not create a second file.")
                % {"name": existing.full_name, "file": existing.file_number}
            )
        elsewhere = others.exclude(status=Patient.Status.OUT).first()
        if elsewhere and not self.instance.pk:
            # Another place's patient: their name stays with that place.
            raise forms.ValidationError(
                _("This ID has an open file at %(place)s (file %(file)s). To move the patient here, open that file "
                  "at %(place)s and press “Move to another place”.")
                % {"place": elsewhere.branch.code, "file": elsewhere.file_number}
            )
        return value

    def clean_full_name(self):
        return clean_arabic_name(self.cleaned_data.get("full_name"))

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
        for name in self.FROM_ID:
            if not data.get(name) and name not in self.errors:
                self.add_error(name, forms.ValidationError(self.fields[name].error_messages["required"],
                                                           code="required"))
        if data.get("phone_primary") and data.get("phone_primary") == data.get("phone_secondary"):
            self.add_error("phone_secondary", _("The second mobile is the same as the first one."))
        # "Referred by one of our patients": choosing the patient is optional (round 13).
        referred_by = data.get("referred_by_lookup")
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
        fields = ["kind", "file", "location", "notes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["file"].widget.attrs.update({"accept": "image/*,application/pdf", "data-id-card": "any"})
        self.fields["location"].widget.attrs.update(dir="ltr", placeholder="\\\\CIA-SERVER\\CBCT\\…")
        for field in self.fields.values():
            field.col = "col-md-6 col-lg-3"

    def clean(self):
        data = super().clean()
        file, kind = data.get("file"), data.get("kind")
        if not file and not data.get("location"):
            raise forms.ValidationError(_("Choose a file, or write where the scan is kept."))
        if file:
            # X-rays and CBCT reports can be big pictures: they may be larger than the other documents.
            limit = settings.MAX_XRAY_UPLOAD_MB if kind == PatientDocument.Kind.XRAY else None
            try:
                validate_upload(file, limit)
            except forms.ValidationError as error:
                self.add_error("file", error)
        return data


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


# Suggestions for the occupation box (anything else can be typed).
OCCUPATIONS = [
    "طالب", "طالبة", "ربة منزل", "موظف", "موظفة", "موظف حكومي", "موظف قطاع خاص", "مدرس", "مدرسة", "طبيب", "طبيبة",
    "مهندس", "مهندسة", "محاسب", "محامي", "صيدلي", "ممرض", "ممرضة", "تاجر", "صاحب عمل", "عامل", "حرفي", "سائق",
    "فلاح", "ضابط", "أمين شرطة", "عسكري", "رجل أعمال", "بالمعاش", "لا يعمل", "عمل حر",
]


ANESTHESIA_CHOICES = [
    MedicalConsult.DEFAULT_ANESTHESIA,
    "Articaine 4% with epinephrine 1:200,000, local infiltration, 2 to 4 cartridges",
    "Mepivacaine 3% without epinephrine, local infiltration, 2 to 4 cartridges",
    "Lidocaine 2% with epinephrine 1:80,000, local infiltration and nerve block, 2 to 4 cartridges",
]
SPECIALTY_CHOICES = ["Internal medicine", "Cardiology", "Endocrinology (diabetes)", "Hematology", "Nephrology",
                     "Oncology", "Rheumatology", "Neurology"]


class CommaChoicesField(forms.MultipleChoiceField):
    """Ticks kept in the model as "code,code"."""

    def __init__(self, **kwargs):
        super().__init__(widget=forms.CheckboxSelectMultiple, **kwargs)

    def prepare_value(self, value):
        if isinstance(value, str):
            return [code for code in value.split(",") if code]
        return value


class MedicalConsultForm(StyledModelForm):
    """The ready consultation letter: the reason, the procedure, the anaesthesia and the medicines after it."""

    reasons = CommaChoicesField(label=_("why"), choices=MedicalConsult.Reason.choices)
    procedures = CommaChoicesField(label=_("planned procedure"), choices=MedicalConsult.Procedure.choices)
    dentist = DentistChoiceField(label=_("dentist"), required=False)

    fieldsets = [
        (_("Why we ask"), ["reasons", "findings"]),
        (_("To"), ["physician", "specialty"]),
        (_("The surgery"), ["procedures", "procedure_details", "duration", "bleeding", "anesthesia", "medications"]),
        (_("The letter"), ["question", "sent_on", "dentist"]),
    ]

    class Meta:
        model = MedicalConsult
        fields = ["reasons", "findings", "physician", "specialty", "procedures", "procedure_details", "duration",
                  "bleeding", "anesthesia", "medications", "question", "sent_on", "dentist"]
        widgets = {"findings": forms.Textarea(attrs={"rows": 4}), "medications": forms.Textarea(attrs={"rows": 4}),
                   "question": forms.Textarea(attrs={"rows": 3}),
                   "anesthesia": DatalistInput(ANESTHESIA_CHOICES),
                   "specialty": DatalistInput(SPECIALTY_CHOICES)}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("physician", "specialty", "procedure_details", "duration", "bleeding", "sent_on", "dentist"):
            self.fields[name].col = "col-md-6"
        self.fields["procedure_details"].col = "col-md-12"

    def clean_reasons(self):
        return ",".join(self.cleaned_data["reasons"])

    def clean_procedures(self):
        return ",".join(self.cleaned_data["procedures"])


class ConsultAnswerForm(StyledModelForm):
    """What the physician answered, copied from the paper the patient brought back (with its photo)."""

    class Meta:
        model = MedicalConsult
        fields = ["answer", "answer_notes", "answered_by", "answered_on", "recheck_on", "answer_file"]
        widgets = {"answer": ChoiceButtons(icons={
            "fit": "bi-check-circle", "precautions": "bi-exclamation-circle", "postpone": "bi-hourglass-split",
            "not_fit": "bi-x-circle"}), "answer_notes": forms.Textarea(attrs={"rows": 3}),
                   "answer_file": forms.ClearableFileInput(attrs={"accept": "image/*,application/pdf",
                                                                  "capture": "environment"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["answer"].required = True
        self.fields["answer"].choices = MedicalConsult.Answer.choices
        self.fields["answered_on"].initial = timezone.localdate()
        for name in ("answered_by", "answered_on", "recheck_on", "answer_file"):
            self.fields[name].col = "col-md-6"

    def clean_answer_file(self):
        return validate_upload(self.cleaned_data.get("answer_file"))

    def clean(self):
        data = super().clean()
        if data.get("answer") == MedicalConsult.Answer.PRECAUTIONS and not data.get("answer_notes"):
            self.add_error("answer_notes", _("Write the precautions the physician asked for."))
        return data
