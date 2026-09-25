from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from apps.clinical.models import LabRequest
from apps.complaints.models import Complaint
from apps.core.forms import clean_digits_value
from apps.core.mixins import AuditMixin, RoleRequiredMixin, SearchMixin, role_required
from apps.core.models import branch_for_user
from apps.core.roles import FRONT_DESK, has_role
from apps.core.utils import normalize_phone
from apps.scheduling.models import day_bounds

from .access import get_visible_patient_or_403, visible_patients
from .forms import LeadCallForm, LeadForm, PatientDocumentForm, PatientFilterForm, PatientForm, PatientRelationForm
from .models import Lead, LeadCall, Patient, PatientDocument, PatientRelation


def _text_search(qs, q, name_field="full_name", extra=()):
    q = clean_digits_value(q)
    if not q:
        return qs
    query = Q(**{f"{name_field}__icontains": q})
    phone = normalize_phone(q)
    if phone:
        query |= Q(phone_primary__contains=phone) | Q(phone_secondary__contains=phone)
    for field in extra:
        query |= Q(**{f"{field}__icontains": q})
    return qs.filter(query)


# ---------------------------------------------------------------- call list
class LeadListView(RoleRequiredMixin, SearchMixin, ListView):
    allowed_roles = FRONT_DESK
    model = Lead
    paginate_by = 30
    template_name = "patients/lead_list.html"

    def get_queryset(self):
        qs = Lead.objects.select_related("referral_source", "converted_patient")
        status = self.request.GET.get("status", "open")
        if status == "open":
            qs = qs.filter(status__in=Lead.OPEN_STATUSES)
        elif status in Lead.Status.values:
            qs = qs.filter(status=status)
        if self.request.GET.get("due"):
            _start, end = day_bounds(timezone.localdate())
            qs = qs.filter(Q(next_call_at__lt=end) | Q(next_call_at__isnull=True, status=Lead.Status.NEW))
        if self.request.GET.get("teeth"):
            qs = qs.filter(missing_teeth=self.request.GET["teeth"])
        qs = _text_search(qs, self.get_search_query())
        return qs.order_by("next_call_at", "-created_at") if self.request.GET.get("due") else qs

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
    lead.next_call_at = form.cleaned_data.get("next_call_at")
    lead.save(update_fields=["status", "next_call_at", "updated_at"])
    messages.success(request, _("Call saved."))
    return redirect(lead)


# ---------------------------------------------------------------- patients
class PatientListView(SearchMixin, ListView):
    model = Patient
    paginate_by = 30
    template_name = "patients/patient_list.html"

    def get_queryset(self):
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

    def get_lead(self):
        lead_id = self.request.GET.get("lead") or self.request.POST.get("lead")
        if lead_id and lead_id.isdigit():
            return Lead.objects.filter(pk=lead_id, converted_patient__isnull=True).first()
        return None

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
        context["lead"] = self.get_lead()
        context["title"] = _("Register new patient")
        return context

    @transaction.atomic
    def form_valid(self, form):
        form.instance.branch = branch_for_user(self.request.user)
        response = super().form_valid(form)
        patient = self.object
        for field, kind in (("id_front", PatientDocument.Kind.ID_FRONT), ("id_back", PatientDocument.Kind.ID_BACK)):
            upload = form.cleaned_data.get(field)
            if upload:
                if patient.id_type == Patient.IdType.PASSPORT and kind == PatientDocument.Kind.ID_FRONT:
                    kind = PatientDocument.Kind.PASSPORT
                PatientDocument.objects.create(patient=patient, kind=kind, file=upload, created_by=self.request.user)
        relative = form.cleaned_data.get("relative_lookup")
        if relative:
            PatientRelation.objects.create(
                patient=patient, related_patient=relative,
                relation=form.cleaned_data["relative_relation"], created_by=self.request.user,
            )
        lead = self.get_lead()
        if lead:
            lead.status = Lead.Status.CONVERTED
            lead.converted_patient = patient
            lead.save(update_fields=["status", "converted_patient", "updated_at"])
        messages.success(
            self.request,
            _("Patient registered. File number: %(file)s") % {"file": patient.file_number},
        )
        return response


class PatientUpdateView(RoleRequiredMixin, AuditMixin, UpdateView):
    allowed_roles = FRONT_DESK
    model = Patient
    form_class = PatientForm
    template_name = "patients/patient_form.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = _("Edit patient data")
        return context


def patient_detail(request, pk):
    patient = get_visible_patient_or_403(request.user, pk)
    context = {
        "patient": patient,
        "documents": patient.documents.all(),
        "relations": patient.relations(),
        "referred_patients": patient.referred_patients.all(),
        "appointments": patient.appointments.select_related("room", "dentist").order_by("-scheduled_at")[:50],
        "steps": patient.treatment_steps.select_related("step_type", "operator", "verified_by")[:100],
        "lab_requests": patient.lab_requests.select_related("work_type", "lab", "dentist"),
        "open_labs": patient.open_lab_requests().select_related("work_type"),
        "complaints": patient.complaints.all(),
        "medical_conditions": patient.medical_conditions.all(),
        "can_edit": has_role(request.user, *FRONT_DESK),
    }
    if context["can_edit"]:
        context["document_form"] = PatientDocumentForm()
        context["relation_form"] = PatientRelationForm(patient=patient)
    return render(request, "patients/patient_detail.html", context)


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
    document.file.delete(save=False)
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
