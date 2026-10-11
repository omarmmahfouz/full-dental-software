import io
import os
import re

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DetailView, ListView, UpdateView
from PIL import Image

from apps.charting.forms import HISTORY_FIELDS, MedicalHistoryForm
from apps.charting.models import Examination, PlanItem
from apps.charting.sync import sync_medical_history
from apps.clinical.models import LabRequest
from apps.complaints.models import Complaint
from apps.core import previews
from apps.core.forms import clean_digits_value
from apps.core.approvals import needs_approval, pending_for, request_change
from apps.core.kept_uploads import carry, chosen
from apps.core.mixins import AuditMixin, RoleRequiredMixin, SearchMixin, role_required
from apps.core.models import Branch, ChangeRequest, branch_for_user, working_places
from apps.core.roles import CLINICAL, FRONT_DESK, PATIENT_VIEWERS, has_role
from apps.core.utils import hours_minutes, name_patterns, normalize_phone, validate_phone

from .access import (
    file_parts,
    other_place_page,
    get_clinical_patient_or_403,
    get_visible_patient_or_403,
    my_patients,
    visible_patients,
)
from .forms import (
    LeadCallForm, LeadForm, PatientDocumentForm, PatientFilterForm, PatientForm, PatientRelationForm,
    duplicate_phone_error,
)
from .models import DayPart, Lead, LeadCall, Patient, PatientDocument, PatientRelation
from .sequence import file_steps, next_step


FILE_CODE = re.compile(r"^([A-Za-z]{2,4})[-\s]?0*(\d{1,6})$")


def _number_search(qs, q, files=True):
    """A number typed (round 16): starting with 0 (or +20) it is the beginning of a mobile (0122 → every mobile
    starting with 0122); otherwise the file number of this place exactly (12 → CIA-00012 here, CIC-00012 at CIC),
    or a whole national ID. None when ``q`` is not a number."""
    text = q.replace(" ", "").replace("-", "")
    if text.startswith("+"):
        text = normalize_phone(text) or text
    code = FILE_CODE.match(q.replace(" ", ""))
    if files and code:  # "CIA-12", "cic12": that place's file number
        return qs.filter(file_number__iregex=rf"^{code.group(1)}-0*{int(code.group(2))}$")
    if not text.isdigit():
        return None
    if text.startswith("0"):
        return qs.filter(Q(phone_primary__startswith=text) | Q(phone_secondary__startswith=text))
    if not files:
        return qs.filter(Q(phone_primary__contains=text) | Q(phone_secondary__contains=text))
    if len(text) >= 10:
        return qs.filter(national_id=text)
    return qs.filter(file_number__iregex=rf"^[A-Za-z]+-0*{int(text)}$")


def _text_search(qs, q, name_field="full_name", extra=(), files=True):
    """Every word of the name (in any spelling of أ/ا, ة/ه, ى/ي); a number is a mobile's beginning (0…) or the exact
    file number of this place (round 16: the search was too wide)."""
    q = clean_digits_value(q)
    if not q:
        return qs
    numbers = _number_search(qs, q.strip(), files=files)
    if numbers is not None:
        return numbers
    query = Q()
    for pattern in name_patterns(q):
        query &= Q(**{f"{name_field}__iregex": pattern})
    phone = normalize_phone(q)
    if phone:
        query |= Q(phone_primary__contains=phone) | Q(phone_secondary__contains=phone)
    for field in extra:
        query |= Q(**{f"{field}__icontains": q})
    return qs.filter(query)


def patient_lookup(request):
    """Suggestions for the patient boxes while typing a name, mobile, file number or ID."""
    q = request.GET.get("q", "").strip()
    if len(q) < 2 or not has_role(request.user, *PATIENT_VIEWERS):
        return JsonResponse({"results": []})
    patients = _text_search(visible_patients(request.user), q, extra=("file_number", "national_id"))
    return JsonResponse({"results": [
        {"value": p.file_number, "label": f"{p.full_name} — {p.file_number} — {p.phone_primary}"}
        for p in patients.order_by("full_name")[:12]
    ]})


def patient_prefs(request):
    """For the booking page: how far the patient lives and the days and times he prefers (round 13)."""
    from .forms import find_patient

    if not has_role(request.user, *FRONT_DESK):
        return JsonResponse({})
    patient = find_patient(request.GET.get("q", ""))
    if patient is None:
        return JsonResponse({})
    parts = []
    if patient.travel_minutes:
        parts.append(_("lives %(time)s away") % {"time": hours_minutes(patient.travel_minutes)})
    if patient.preferred_days:
        parts.append(_("prefers: %(days)s") % {"days": "، ".join(patient.preferred_day_list)})
    if patient.preferred_times:
        parts.append(", ".join(patient.preferred_time_list))
    return JsonResponse({
        "text": " · ".join(str(part) for part in parts),
        "days": [int(day) for day in patient.preferred_days.split(",") if day.isdigit()],
        "times": [DayPart.hours(code) for code in patient.preferred_times.split(",") if code in DayPart.values],
    })


def phone_check(request):
    """While the secretary types a mobile: is it a real number, and does another file already have it?"""
    phone = normalize_phone(request.GET.get("phone", ""))
    if not phone or not has_role(request.user, *FRONT_DESK):
        return JsonResponse({})
    primary = request.GET.get("field") != "secondary"
    try:
        validate_phone(phone, mobile_only=primary)
    except ValidationError as error:
        return JsonResponse({"title": _("Check the mobile number"), "message": error.messages[0]})
    if not primary:
        return JsonResponse({})
    pk = request.GET.get("pk", "")
    if request.GET.get("kind") == "lead":
        lead = Lead.objects.filter(pk=pk).first() if pk.isdigit() else None
        message = duplicate_phone_error(phone, exclude_lead=lead or Lead())
    else:
        patient = Patient.objects.filter(pk=pk).first() if pk.isdigit() else None
        if patient is None and Patient.objects.here().filter(phone_primary=phone, is_expected=True).exists():
            return JsonResponse({})  # the new patient's page asks "Did this patient come?" instead (round 16)
        message = duplicate_phone_error(phone, exclude_patient=patient or Patient(), exclude_lead=False)
    return JsonResponse({"title": _("This mobile is already registered"), "message": str(message)} if message else {})


def expected_candidates(place, phones=(), name="", limit=4):
    """The expected patients of a place who may be the person registering now (round 16): the short files booked
    from the call list and the open calls, with the same mobile or a name alike (typed with a mistake too)."""
    from apps.core.utils import names_alike

    phones = {p for p in (normalize_phone(phone) for phone in phones) if p}
    found = []
    expected = Patient.objects.filter(branch=place, is_expected=True)
    leads = Lead.objects.filter(branch=place, status__in=Lead.OPEN_STATUSES, converted_patient__isnull=True)
    for kind, rows in (("patient", expected), ("lead", leads)):
        for row in rows.only("pk", "full_name", "phone_primary", "phone_secondary")[:2000]:
            same_phone = bool(phones & {row.phone_primary, row.phone_secondary})
            alike = names_alike(name, row.full_name) if name else 0
            if same_phone or alike >= 0.8:
                found.append((kind, row, same_phone, alike))
    found.sort(key=lambda item: (not item[2], -item[3]))
    return found[:limit]


def expected_match(request):
    """While the reception types a new patient's name or mobile: is he an expected patient (booked from the call list,
    or still on it)? The page asks "Did this patient come?" (round 16)."""
    from apps.scheduling.models import Appointment

    if not has_role(request.user, *FRONT_DESK):
        return JsonResponse({"matches": []})
    place = branch_for_user(request.user)
    rows = expected_candidates(place, [request.GET.get("phone", ""), request.GET.get("phone2", "")],
                               request.GET.get("name", "").strip())
    matches = []
    for kind, row, same_phone, alike in rows:
        booked = ""
        if kind == "patient":
            visit = Appointment.objects.filter(patient=row, status__in=Appointment.BOOKED_STATUSES).order_by(
                "scheduled_at").first()
            if visit is not None:
                booked = timezone.localtime(visit.scheduled_at).strftime("%d/%m/%Y %I:%M %p")
        matches.append({
            "key": f"{kind}:{row.pk}", "name": row.full_name, "phone": row.phone_primary,
            "phone2": row.phone_secondary, "file": row.file_number if kind == "patient" else "",
            "booked": booked,
            "why": str(_("the same mobile") if same_phone else _("a name alike")),
        })
    return JsonResponse({"matches": matches})


def chosen_expected(request):
    """The expected patient the reception said is the one who came (``expected`` = "patient:12" or "lead:5")."""
    kind, _sep, pk = (request.POST.get("expected") or "").partition(":")
    if not pk.isdigit():
        return None, None
    place = branch_for_user(request.user)
    if kind == "patient":
        return Patient.objects.filter(pk=pk, branch=place, is_expected=True).first(), None
    if kind == "lead":
        return None, Lead.objects.filter(pk=pk, branch=place, converted_patient__isnull=True).first()
    return None, None


def keep_both_mobiles(patient, old_numbers, main):
    """The patient came with another mobile than the one booked (someone else may have booked for him): the new
    mobile is the main one (or the old one, ``main == "old"``), and the other is kept as mobile 2 or in the notes."""
    typed = [patient.phone_primary, patient.phone_secondary]
    old = [number for number in old_numbers if number and number not in typed]
    if not old:
        return
    if main == "old":
        patient.phone_primary, patient.phone_secondary = old[0], typed[0]
        extra = [number for number in typed[1:] + old[1:] if number and number not in (old[0], typed[0])]
    else:
        if not patient.phone_secondary:
            patient.phone_secondary = old.pop(0)
        extra = old
    if extra:
        line = _("Other mobile (from the booking): %(phones)s") % {"phones": ", ".join(extra)}
        patient.notes = f"{patient.notes}\n{line}".strip()


# ---------------------------------------------------------------- call list
class LeadListView(RoleRequiredMixin, SearchMixin, ListView):
    allowed_roles = FRONT_DESK
    model = Lead
    paginate_by = 30
    template_name = "patients/lead_list.html"

    def get_queryset(self):
        qs = Lead.objects.filter(branch=branch_for_user(self.request.user)).select_related(
            "referral_source", "converted_patient")
        status = self.request.GET.get("status", "open")
        if status == "open":
            qs = qs.filter(status__in=Lead.OPEN_STATUSES)
        elif status in Lead.Status.values:
            qs = qs.filter(status=status)
        if self.request.GET.get("due"):
            qs = qs.filter(status__in=(Lead.Status.NEW, Lead.Status.FOLLOW_UP))
        if self.request.GET.get("teeth"):
            qs = qs.filter(missing_teeth=self.request.GET["teeth"])
        qs = _text_search(qs, self.get_search_query(), files=False)
        return qs.order_by("first_call_on", "created_at")  # who called first comes first

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["statuses"] = Lead.Status.choices
        context["teeth_choices"] = Lead._meta.get_field("missing_teeth").choices
        context["status"] = self.request.GET.get("status", "open")
        context["counts"] = dict(Lead.objects.values_list("status").annotate(n=Count("id")))
        return context


class LeadCreateView(RoleRequiredMixin, AuditMixin, CreateView):
    allowed_roles = FRONT_DESK
    model = Lead
    form_class = LeadForm
    template_name = "includes/form_page.html"
    extra_context = {"title": gettext_lazy("New expected patient (incoming call)")}

    def form_valid(self, form):
        form.instance.branch = branch_for_user(self.request.user)
        return super().form_valid(form)


class LeadUpdateView(RoleRequiredMixin, AuditMixin, UpdateView):
    allowed_roles = FRONT_DESK
    model = Lead
    form_class = LeadForm
    template_name = "includes/form_page.html"
    extra_context = {"title": gettext_lazy("Edit expected patient")}


class LeadDetailView(RoleRequiredMixin, DetailView):
    allowed_roles = FRONT_DESK
    model = Lead
    template_name = "patients/lead_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["call_form"] = kwargs.get("call_form") or LeadCallForm()
        context["calls"] = self.object.calls.select_related("created_by")
        return context


@role_required(*FRONT_DESK)
@require_POST
def lead_book(request, pk):
    """An expected patient wants an appointment (round 15): a short file is opened from the call list (the name, the
    mobiles and what he told on the phone) and the booking page opens with the day's schedule. The reception
    completes the file (the ID and the rest) when he comes."""
    lead = get_object_or_404(Lead, pk=pk)
    patient = lead.converted_patient
    if patient is None:
        patient = Patient.objects.filter(branch=lead.branch, phone_primary=lead.phone_primary).first()
    if patient is None:
        with transaction.atomic():
            patient = Patient.objects.create(
                branch=lead.branch, full_name=lead.full_name, national_id="", is_expected=True,
                phone_primary=lead.phone_primary, phone_secondary=lead.phone_secondary,
                preferred_phone=lead.preferred_phone, gender=lead.gender, city=lead.city,
                missing_teeth=lead.missing_teeth, missing_teeth_notes=lead.missing_teeth_notes,
                medical_notes=lead.medical_notes, referral_source=lead.referral_source,
                referral_notes=lead.referral_notes, created_by=request.user)
            patient.medical_conditions.set(lead.medical_conditions.all())
    lead.converted_patient = patient
    if lead.status in (Lead.Status.NEW, Lead.Status.FOLLOW_UP):
        lead.status = Lead.Status.BOOKED
    lead.save(update_fields=["converted_patient", "status", "updated_at"])
    if patient.is_expected:
        messages.info(request, _("A short file was opened for %(name)s (%(file)s): choose the day and the time. "
                                 "Complete the file when he comes.") % {"name": patient.full_name,
                                                                         "file": patient.file_number})
    return redirect(f"{reverse('scheduling:appointment_create')}?patient={patient.pk}")


@role_required(*FRONT_DESK)
@require_POST
def lead_add_call(request, pk):
    lead = get_object_or_404(Lead, pk=pk)
    form = LeadCallForm(request.POST)
    if not form.is_valid():
        view = LeadDetailView()
        view.setup(request, pk=pk)
        view.object = lead
        return render(request, view.template_name, view.get_context_data(object=lead, call_form=form))
    call = form.save(commit=False)
    call.lead = lead
    call.created_by = request.user
    call.save()
    new_status = form.cleaned_data.get("new_status")
    if new_status:
        lead.status = new_status
    elif call.outcome == LeadCall.Outcome.BOOKED:
        lead.status = Lead.Status.BOOKED
    elif call.outcome == LeadCall.Outcome.WRONG_NUMBER:
        lead.status = Lead.Status.UNREACHABLE
    elif lead.status == Lead.Status.NEW:
        lead.status = Lead.Status.FOLLOW_UP
    lead.save(update_fields=["status", "updated_at"])
    messages.success(request, _("Call saved."))
    return redirect(lead)


# ---------------------------------------------------------------- patients
class PatientListView(SearchMixin, ListView):
    model = Patient
    paginate_by = 30
    template_name = "patients/patient_list.html"

    def get_queryset(self):
        if not has_role(self.request.user, *PATIENT_VIEWERS):
            raise PermissionDenied
        self.filter_form = PatientFilterForm(self.request.GET or None)
        qs = visible_patients(self.request.user).select_related("assigned_dentist")
        qs = qs.annotate(
            open_labs=Count("lab_requests", filter=Q(lab_requests__status__in=LabRequest.OPEN_STATUSES), distinct=True),
            open_complaints=Count(
                "complaints", filter=Q(complaints__status__in=Complaint.OPEN_STATUSES), distinct=True
            ),
        )
        if self.filter_form.is_valid():
            data = self.filter_form.cleaned_data
            qs = _text_search(qs, data.get("q"), extra=("file_number", "national_id"))
            if data.get("status"):
                qs = qs.filter(status=data["status"])
            if data.get("dentist"):
                qs = qs.filter(assigned_dentist=data["dentist"])
            if data.get("lab"):
                qs = qs.filter(open_labs__gt=0)
            if data.get("mine"):
                qs = qs.filter(pk__in=my_patients(self.request.user).values("pk"))
        return qs.order_by("-created_at")

    def get(self, request, *args, **kwargs):
        response = super().get(request, *args, **kwargs)
        # Searching an exact file number / ID / mobile jumps straight to the file.
        q = self.get_search_query()
        page = response.context_data["page_obj"]
        if q and page.paginator.count == 1 and page.number == 1:
            return redirect(page.object_list[0])
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filter_form"] = self.filter_form
        return context


class PatientCreateView(RoleRequiredMixin, AuditMixin, CreateView):
    allowed_roles = FRONT_DESK
    model = Patient
    form_class = PatientForm
    template_name = "patients/patient_form.html"
    success_message = None

    def get(self, request, *args, **kwargs):
        lead_id = request.GET.get("lead", "")
        expected = Lead.objects.filter(pk=lead_id, converted_patient__is_expected=True).values_list(
            "converted_patient", flat=True).first() if lead_id.isdigit() else None
        if expected:  # booked from the call list: its short file is completed (round 15)
            return redirect("patients:update", expected)
        return super().get(request, *args, **kwargs)

    def get_lead(self):
        if self.request.method == "POST":
            _patient, lead = chosen_expected(self.request)
            if lead is not None:  # "Yes, it is him" on an open call of the call list (round 16)
                return lead
        lead_id = self.request.GET.get("lead") or self.request.POST.get("lead")
        if lead_id and lead_id.isdigit():
            return Lead.objects.filter(pk=lead_id, converted_patient__isnull=True).first()
        return None

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        self.expected = None
        if self.request.method == "POST":
            self.expected, lead = chosen_expected(self.request)
            if self.expected is not None or lead is not None:
                kwargs["spare_phone"] = (self.expected or lead).phone_primary
            if self.expected is not None:
                # The expected patient came: the new patient's form is saved on his short file (his bookings stay).
                kwargs["instance"], kwargs["as_new"] = self.expected, True
                self.expected_numbers = [self.expected.phone_primary, self.expected.phone_secondary]
        return kwargs

    def get_initial(self):
        initial = super().get_initial()
        lead = self.get_lead()
        if lead:
            initial.update(
                {
                    "full_name": lead.full_name,
                    "phone_primary": lead.phone_primary,
                    "phone_secondary": lead.phone_secondary,
                    "preferred_phone": lead.preferred_phone,
                    "gender": lead.gender,
                    "city": lead.city,
                    "missing_teeth": lead.missing_teeth,
                    "missing_teeth_notes": lead.missing_teeth_notes,
                    "medical_conditions": list(lead.medical_conditions.all()),
                    "medical_notes": lead.medical_notes,
                    "referral_source": lead.referral_source,
                    "referral_notes": lead.referral_notes,
                }
            )
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["lead"] = None if self.request.POST.get("expected") else self.get_lead()
        context["title"] = _("Register new patient")
        context["expected_check"] = reverse("patients:expected_match")
        if self.request.POST.get("expected"):
            patient, lead = chosen_expected(self.request)
            context["expected_name"] = (patient or lead).full_name if (patient or lead) else ""
        return context

    def form_invalid(self, form):
        carry(self.request, form, PatientForm.ID_PHOTOS)  # the ID photos are kept for the next try
        return super().form_invalid(form)

    @transaction.atomic
    def form_valid(self, form):
        form.instance.branch = form.instance.branch if self.expected is not None else branch_for_user(self.request.user)
        lead = self.get_lead()
        main = self.request.POST.get("main_phone", "new")
        if self.expected is not None:
            form.instance.is_expected = False  # completed: he takes his final number (round 16)
            form.instance.registered_on = form.cleaned_data.get("registered_on") or timezone.localdate()
            keep_both_mobiles(form.instance, self.expected_numbers, main)
        elif lead is not None and self.request.POST.get("expected"):
            keep_both_mobiles(form.instance, [lead.phone_primary, lead.phone_secondary], main)
        response = super().form_valid(form)
        patient = self.object
        if self.expected is not None:
            Lead.objects.filter(converted_patient=patient).update(status=Lead.Status.CONVERTED)
        save_id_photos(self.request, form, patient)
        relative = form.cleaned_data.get("relative_lookup")
        if relative:
            PatientRelation.objects.create(
                patient=patient, related_patient=relative,
                relation=form.cleaned_data["relative_relation"], created_by=self.request.user,
            )
        if lead:
            lead.status = Lead.Status.CONVERTED
            lead.converted_patient = patient
            lead.save(update_fields=["status", "converted_patient", "updated_at"])
        if self.expected is not None:
            messages.success(self.request, _("The expected file of %(name)s is completed: file number %(file)s. "
                                             "His bookings stay.") % {"name": patient.full_name,
                                                                      "file": patient.file_number})
        else:
            messages.success(
                self.request,
                _("Patient registered. File number: %(file)s") % {"file": patient.file_number},
            )
        return response


def save_id_photos(request, form, patient):
    """The ID photos of the patient form (chosen now, or kept from a try that came back with an error)."""
    saved = 0
    for field, kind in (("id_front", PatientDocument.Kind.ID_FRONT), ("id_back", PatientDocument.Kind.ID_BACK)):
        upload = chosen(request, form, field) if field in form.fields else None
        if upload:
            if patient.id_type == Patient.IdType.PASSPORT and kind == PatientDocument.Kind.ID_FRONT:
                kind = PatientDocument.Kind.PASSPORT
            PatientDocument.objects.create(patient=patient, kind=kind, file=upload, created_by=request.user)
            saved += 1
    return saved


class PatientUpdateView(RoleRequiredMixin, AuditMixin, UpdateView):
    allowed_roles = FRONT_DESK
    model = Patient
    form_class = PatientForm
    template_name = "patients/patient_form.html"

    def form_invalid(self, form):
        carry(self.request, form, PatientForm.ID_PHOTOS)
        return super().form_invalid(form)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["can_renumber"] = not needs_approval(self.request.user)
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = _("Edit patient data")
        if self.object.is_expected:
            context["title"] = _("Complete the file of %(name)s") % {"name": self.object.full_name}
        elif needs_approval(self.request.user):
            context["intro"] = _("Your changes go to the head of CIA and are applied after approval.")
        return context

    def form_valid(self, form):
        # New ID photos are saved at once, like a document added to the file (no approval needed).
        photos = save_id_photos(self.request, form, Patient.objects.get(pk=self.object.pk))
        if self.object.is_expected:
            # The short file of an expected patient is completed when he comes: this is his registration (round 15).
            form.instance.is_expected = False
            if "registered_on" not in form.changed_data:
                form.instance.registered_on = timezone.localdate()
            response = super().form_valid(form)
            Lead.objects.filter(converted_patient=self.object).update(status=Lead.Status.CONVERTED)
            messages.success(self.request, _("Patient registered. File number: %(file)s")
                             % {"file": self.object.file_number})
            return response
        if not needs_approval(self.request.user):
            return super().form_valid(form)
        original = Patient.objects.get(pk=self.object.pk)  # the form already changed self.object in memory
        values = {}
        for name in form.changed_data:
            if name in PatientForm.ID_PHOTOS:
                continue
            if name == "referred_by_lookup":
                values["referred_by"] = form.cleaned_data[name]
            elif name in form._meta.fields:
                values[name] = form.cleaned_data[name]
        if "status" in values:
            values.update(out_reason=form.cleaned_data.get("out_reason"), out_notes=form.cleaned_data.get("out_notes", ""))
        if request_change(ChangeRequest.Kind.PATIENT, original, values, self.request.user):
            messages.warning(self.request, _("Sent to the head of CIA for approval. The file changes once it is approved."))
        elif photos:
            messages.success(self.request, _("The ID photos were saved."))
        else:
            messages.info(self.request, _("Nothing was changed."))
        return redirect(original)


def patient_detail(request, pk):
    from .medical import clearance

    # A file of another place this person works at (e.g. opened from a notification): switch place first.
    switch = other_place_page(request, Patient.objects.filter(pk=pk).values_list("branch", flat=True).first())
    if switch is not None:
        return switch
    patient = get_visible_patient_or_403(request.user, pk)
    context = {
        "patient": patient,
        "documents": patient.documents.all(),
        "xrays": patient.documents.filter(kind=PatientDocument.Kind.XRAY),
        "relations": patient.relations(),
        "referred_patients": patient.referred_patients.all(),
        "appointments": patient.appointments.select_related("room", "dentist", "branch").order_by("-scheduled_at")[:50],
        "steps": patient.treatment_steps.select_related("step_type", "operator", "verified_by")[:100],
        "plans": patient.treatment_plans.exclude(status="cancelled").select_related("dentist").prefetch_related(
            Prefetch("items", queryset=PlanItem.objects.select_related("step_type"))),
        "lab_requests": patient.lab_requests.select_related("work_type", "lab", "dentist"),
        "outside_requests": patient.outside_requests.select_related("dentist", "result"),
        "id_cards": [d for d in patient.documents.all() if d.kind in PatientDocument.CARD_KINDS and d.is_image][:2],
        "open_labs": patient.open_lab_requests().select_related("work_type"),
        "complaints": patient.complaints.visible_to(request.user),
        "prostheses": patient.prostheses.prefetch_related("implants"),
        "medical_conditions": patient.medical_conditions.all(),
        "can_edit": has_role(request.user, *FRONT_DESK),
        "pending_changes": pending_for(patient),
        "exam": patient.examinations.select_related("examined_by").prefetch_related("conditions").first(),
        "chart_missing": patient.tooth_states.filter(status="missing").exists(),
        "parts": file_parts(request.user),
        "open_referrals": patient.referrals.filter(status__in=("sent", "booked")).count(),
        "consents": patient.consents.select_related("template"),  # round 16
        "sick_leaves": patient.sick_leaves.all(),
    }
    if has_role(request.user, *CLINICAL) and patient.branch.specialist_clinic:
        # El Khadem (round 16): the file by specialty, not the steps of an implant case.
        from apps.specialties.strip import specialty_strip

        context["specialty_strip"] = specialty_strip(patient)
        histories = patient.examinations.order_by("-exam_date")
        medical = histories.filter(medical_taken=True).values_list("exam_date", flat=True).first()
        dental = histories.filter(dental_taken=True).values_list("exam_date", flat=True).first()
        exam = histories.filter(history_only=False).values_list("exam_date", flat=True).first()
        context["strip_history"] = {"medical": medical, "dental": dental, "exam": exam}
    elif has_role(request.user, *CLINICAL):
        context["file_steps"] = file_steps(patient)
        context["next_step"] = next_step(context["file_steps"])
    context["clearance"] = clearance(patient)
    if context["can_edit"]:
        context["document_form"] = PatientDocumentForm()
        context["relation_form"] = PatientRelationForm(patient=patient)
        if patient.status != Patient.Status.OUT:
            context["move_places"] = Branch.objects.filter(is_active=True).exclude(kind=Branch.Kind.LAB).exclude(
                pk=patient.branch_id).order_by("sort_order", "pk")
    if patient.transferred_to_id:
        context["moved_to"] = patient.transferred_to
        context["moved_to_opens"] = working_places(request.user).filter(pk=patient.transferred_to.branch_id).exists()
    return render(request, "patients/patient_detail.html", context)


@role_required(*FRONT_DESK)
@require_POST
def patient_transfer(request, pk):
    """Move the patient to another of our places: a new file there, this one closed (see transfer.py)."""
    from .transfer import transfer

    patient = get_visible_patient_or_403(request.user, pk)
    place = Branch.objects.filter(code=request.POST.get("place"), is_active=True).exclude(kind=Branch.Kind.LAB).first()
    if place is None:
        messages.error(request, _("Choose the place the patient moves to."))
        return redirect(patient)
    try:
        new, cancelled = transfer(patient, place, request.user)
    except ValidationError as error:
        messages.error(request, error.messages[0])
        return redirect(patient)
    message = _("The patient moved to %(place)s with the new file %(file)s. This file is now out.") % {
        "place": place.code, "file": new.file_number}
    if cancelled:
        message += " " + _("%(n)s coming visits here were cancelled.") % {"n": cancelled}
    messages.success(request, message)
    return redirect(patient)


def medical_history(request, pk):
    """The medical and dental history of the paper chart, taken by the dentist (the reception only when the owner
    allows it in Settings → Access; otherwise it sees a short summary). ``?part=medical`` or ``?part=dental`` shows
    one of the two, as the first two steps of the file (sequence.py). It is kept like an examination, so the
    dentist's examination starts from it."""
    from .sequence import after_step

    patient = get_visible_patient_or_403(request.user, pk)
    if not has_role(request.user, *FRONT_DESK, *CLINICAL) or "medical" not in file_parts(request.user):
        raise PermissionDenied
    part = request.GET.get("part") if request.GET.get("part") in MedicalHistoryForm.PARTS else None
    dentist = has_role(request.user, *CLINICAL)
    latest = patient.examinations.prefetch_related("conditions").first()
    draft = latest if latest is not None and latest.history_only else None
    instance, initial = draft, {}
    if draft is None:
        instance = Examination(patient=patient, medical_taken=False, dental_taken=False)
        if latest is not None:
            # Start from the last history (also the part not shown on this page), so only what changed is edited.
            for name in HISTORY_FIELDS:
                field = Examination._meta.get_field(name)
                if not field.many_to_many:
                    setattr(instance, field.attname, getattr(latest, field.attname))
                    initial[name] = getattr(latest, field.attname)
            instance.medical_taken, instance.dental_taken = latest.medical_taken, latest.dental_taken
            initial["conditions"] = list(latest.conditions.all())
        else:
            initial["conditions"] = list(patient.medical_conditions.all())
    form = MedicalHistoryForm(request.POST or None, instance=instance, initial=initial, part=part, dentist=dentist)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            history = form.save(commit=False)
            if history.pk is None:
                history.history_only, history.created_by = True, request.user
            history.exam_date = timezone.localdate()
            if part in (None, "medical"):
                history.medical_taken = True
            if part in (None, "dental"):
                history.dental_taken = True
            history.save()
            form.save_m2m()
            if "conditions" not in form.fields and draft is None:
                history.conditions.set(initial["conditions"])
            sync_medical_history(history)
        if part in (None, "medical"):
            from .medical import reading_flags, sync_recalls

            sync_recalls(Patient.objects.filter(pk=patient.pk))  # a new reading closes or opens a call for a test

            for _code, text in reading_flags(history):
                messages.warning(request, _("%(reading)s: a physician's opinion is needed before surgery "
                                            "(the medical follow-up).") % {"reading": text})
        if part == "medical":
            messages.success(request, _("Medical history saved."))
        elif part == "dental":
            messages.success(request, _("Dental history saved."))
        else:
            messages.success(request, _("Medical and dental history saved. The dentist sees it at the next examination."))
        return redirect(after_step(request, patient, part or "dental") or reverse("patients:detail", args=[pk]))
    titles = {"medical": _("Medical history — %(name)s"), "dental": _("Dental history — %(name)s")}
    return render(request, "patients/history_form.html", {
        "form": form, "patient": patient,
        "title": titles.get(part, _("Medical and dental history — %(name)s")) % {"name": patient.full_name},
        "intro": _("The same questions as the paper chart. Ask the patient and tick or write the answers."),
        "cancel_url": patient.get_absolute_url(),
        "file_steps": file_steps(patient, current=part) if dentist else None,
        "flow": request.GET.get("flow"),
    })


@role_required(*CLINICAL)
def records_step(request, pk):
    """Two steps of the file: the primary impression or diagnostic scan, and the CBCT. The dentist taps what was
    done (a treatment step is written for today) or skips it; going through the file ("flow") it goes on to the
    next step."""
    from apps.clinical.models import TreatmentStep, TreatmentStepType
    from apps.dentists.models import Dentist

    from .sequence import after_step

    patient = get_visible_patient_or_403(request.user, pk)
    step = request.GET.get("step") if request.GET.get("step") in ("impression", "cbct") else "impression"
    types = TreatmentStepType.objects.filter(is_active=True, journey_step=step)
    if request.method == "POST":
        chosen = request.POST.get("type", "")
        if chosen != "skip":
            step_type = get_object_or_404(types, pk=chosen) if chosen.isdigit() else None
            if step_type is None:
                raise PermissionDenied
            TreatmentStep.objects.create(
                patient=patient, step_type=step_type, operator=Dentist.for_user(request.user) or patient.assigned_dentist,
                notes=request.POST.get("notes", "")[:500], created_by=request.user)
            messages.success(request, _("Recorded: %(what)s.") % {"what": step_type})
        return redirect(after_step(request, patient, step) or patient.get_absolute_url())
    return render(request, "patients/records_step.html", {
        "patient": patient, "step": step, "types": types, "flow": request.GET.get("flow"),
        "file_steps": file_steps(patient, current=step),
        "recorded": patient.treatment_steps.filter(step_type__journey_step=step).select_related("step_type", "operator"),
        "cbct_requests": patient.outside_requests.filter(kind="cbct").select_related("dentist") if step == "cbct" else (),
        "cbct_files": patient.documents.filter(kind=PatientDocument.Kind.XRAY) if step == "cbct" else (),
    })


@role_required(*FRONT_DESK)
@require_POST
def document_rotate(request, pk, doc_pk):
    """Turn a scanned card a quarter turn (when it was photographed sideways)."""
    document = get_object_or_404(PatientDocument, pk=doc_pk, patient_id=pk)
    if document.is_image:
        with document.file.open("rb") as handle:
            image = Image.open(handle)
            image.load()
        output = io.BytesIO()
        image.convert("RGB").rotate(-90 if request.POST.get("way") != "left" else 90, expand=True).save(
            output, "JPEG", quality=92)
        old = document.file.name
        document.file.save(os.path.basename(old).rsplit(".", 1)[0] + ".jpg", ContentFile(output.getvalue()), save=True)
        document.file.storage.delete(old)
        previews.delete_previews(old)
        previews.make_previews(document.file.name)
    return redirect(reverse("patients:detail", args=[pk]))


@role_required(*FRONT_DESK)
@require_POST
def document_upload(request, pk):
    patient = get_object_or_404(Patient, pk=pk)
    form = PatientDocumentForm(request.POST, request.FILES)
    if form.is_valid():
        document = form.save(commit=False)
        document.patient = patient
        document.created_by = request.user
        document.save()
        previews.make_previews(document.file.name)
        messages.success(request, _("Document uploaded."))
    else:
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
    return redirect(reverse("patients:detail", args=[pk]) + "#documents")


@role_required(*FRONT_DESK)
@require_POST
def document_delete(request, pk, doc_pk):
    document = get_object_or_404(PatientDocument, pk=doc_pk, patient_id=pk)
    previews.delete_previews(document.file.name)
    document.file.delete(save=False)
    if document.original:
        document.original.delete(save=False)
    document.delete()
    messages.success(request, _("Document deleted."))
    return redirect(reverse("patients:detail", args=[pk]) + "#documents")


@role_required(*FRONT_DESK)
@require_POST
def relation_add(request, pk):
    patient = get_object_or_404(Patient, pk=pk)
    form = PatientRelationForm(request.POST, patient=patient)
    if form.is_valid():
        relation = form.save(commit=False)
        relation.patient = patient
        relation.related_patient = form.cleaned_data["related_lookup"]
        relation.created_by = request.user
        relation.save()
        messages.success(request, _("Relation saved."))
    else:
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
    return redirect(reverse("patients:detail", args=[pk]) + "#relations")


@role_required(*FRONT_DESK)
@require_POST
def relation_delete(request, pk, rel_pk):
    relation = get_object_or_404(PatientRelation, Q(patient_id=pk) | Q(related_patient_id=pk), pk=rel_pk)
    relation.delete()
    messages.success(request, _("Relation removed."))
    return redirect(reverse("patients:detail", args=[pk]) + "#relations")


def patient_word(request, pk):
    """The whole patient file as a Word document (.docx)."""
    from .word import patient_docx

    patient = get_clinical_patient_or_403(request.user, pk)
    return FileResponse(patient_docx(patient), as_attachment=True,
                        filename=f"{patient.file_number} {patient.full_name}.docx")


def patient_excel(request, pk):
    """The whole patient file as an Excel workbook (.xlsx), one sheet per part."""
    from .word import patient_xlsx

    patient = get_clinical_patient_or_403(request.user, pk)
    return FileResponse(patient_xlsx(patient), as_attachment=True,
                        filename=f"{patient.file_number} {patient.full_name}.xlsx")
