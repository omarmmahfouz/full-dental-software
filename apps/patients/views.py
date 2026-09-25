import io
import os

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
from apps.core.forms import clean_digits_value
from apps.core.approvals import needs_approval, pending_for, request_change
from apps.core.mixins import AuditMixin, RoleRequiredMixin, SearchMixin, role_required
from apps.core.models import ChangeRequest, branch_for_user
from apps.core.roles import CLINICAL, FRONT_DESK, PATIENT_VIEWERS, has_role
from apps.core.utils import name_patterns, normalize_phone, validate_phone

from .access import get_clinical_patient_or_403, get_visible_patient_or_403, my_patients, visible_patients
from .forms import (
    LeadCallForm, LeadForm, PatientDocumentForm, PatientFilterForm, PatientForm, PatientRelationForm,
    duplicate_phone_error,
)
from .models import Lead, LeadCall, Patient, PatientDocument, PatientRelation


def _text_search(qs, q, name_field="full_name", extra=()):
    """Every word of the name (in any spelling of أ/ا, ة/ه, ى/ي), or the mobile, file number or ID."""
    q = clean_digits_value(q)
    if not q:
        return qs
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
        message = duplicate_phone_error(phone, exclude_patient=patient or Patient(), exclude_lead=False)
    return JsonResponse({"title": _("This mobile is already registered"), "message": str(message)} if message else {})


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
            qs = qs.filter(status__in=(Lead.Status.NEW, Lead.Status.FOLLOW_UP))
        if self.request.GET.get("teeth"):
            qs = qs.filter(missing_teeth=self.request.GET["teeth"])
        qs = _text_search(qs, self.get_search_query())
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
        if needs_approval(self.request.user):
            context["intro"] = _("Your changes go to the head of CIA and are applied after approval.")
        return context

    def form_valid(self, form):
        if not needs_approval(self.request.user):
            return super().form_valid(form)
        original = Patient.objects.get(pk=self.object.pk)  # the form already changed self.object in memory
        values = {}
        for name in form.changed_data:
            if name == "referred_by_lookup":
                values["referred_by"] = form.cleaned_data[name]
            elif name in form._meta.fields:
                values[name] = form.cleaned_data[name]
        if "status" in values:
            values.update(out_reason=form.cleaned_data.get("out_reason"), out_notes=form.cleaned_data.get("out_notes", ""))
        if request_change(ChangeRequest.Kind.PATIENT, original, values, self.request.user):
            messages.warning(self.request, _("Sent to the head of CIA for approval. The file changes once it is approved."))
        else:
            messages.info(self.request, _("Nothing was changed."))
        return redirect(original)


def patient_detail(request, pk):
    patient = get_visible_patient_or_403(request.user, pk)
    context = {
        "patient": patient,
        "documents": patient.documents.all(),
        "relations": patient.relations(),
        "referred_patients": patient.referred_patients.all(),
        "appointments": patient.appointments.select_related("room", "dentist").order_by("-scheduled_at")[:50],
        "steps": patient.treatment_steps.select_related("step_type", "operator", "verified_by")[:100],
        "plans": patient.treatment_plans.exclude(status="cancelled").select_related("dentist").prefetch_related(
            Prefetch("items", queryset=PlanItem.objects.select_related("step_type"))),
        "lab_requests": patient.lab_requests.select_related("work_type", "lab", "dentist"),
        "outside_requests": patient.outside_requests.select_related("dentist"),
        "id_cards": [d for d in patient.documents.all() if d.kind in PatientDocument.CARD_KINDS and d.is_image][:2],
        "open_labs": patient.open_lab_requests().select_related("work_type"),
        "complaints": patient.complaints.all(),
        "medical_conditions": patient.medical_conditions.all(),
        "can_edit": has_role(request.user, *FRONT_DESK),
        "pending_changes": pending_for(patient),
        "exam": patient.examinations.select_related("examined_by").prefetch_related("conditions").first(),
        "chart_missing": patient.tooth_states.filter(status="missing").exists(),
    }
    if context["can_edit"]:
        context["document_form"] = PatientDocumentForm()
        context["relation_form"] = PatientRelationForm(patient=patient)
    return render(request, "patients/patient_detail.html", context)


def medical_history(request, pk):
    """The medical and dental history of the paper chart, asked at the reception (or by a dentist).
    It is kept like an examination, so the dentist's next examination starts from it."""
    patient = get_visible_patient_or_403(request.user, pk)
    if not has_role(request.user, *FRONT_DESK, *CLINICAL):
        raise PermissionDenied
    latest = patient.examinations.prefetch_related("conditions").first()
    draft = latest if latest is not None and latest.history_only else None
    initial = {}
    if draft is None and latest is not None:
        initial = {name: getattr(latest, Examination._meta.get_field(name).attname) for name in HISTORY_FIELDS
                   if not Examination._meta.get_field(name).many_to_many}
        initial["conditions"] = list(latest.conditions.all())
    elif latest is None:
        initial["conditions"] = list(patient.medical_conditions.all())
    form = MedicalHistoryForm(request.POST or None, instance=draft or Examination(patient=patient), initial=initial)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            history = form.save(commit=False)
            if history.pk is None:
                history.history_only, history.created_by = True, request.user
            history.exam_date = timezone.localdate()
            history.save()
            form.save_m2m()
            sync_medical_history(history)
        messages.success(request, _("Medical and dental history saved. The dentist sees it at the next examination."))
        return redirect(reverse("patients:detail", args=[pk]))
    return render(request, "includes/form_page.html", {
        "form": form, "title": _("Medical and dental history — %(name)s") % {"name": patient.full_name},
        "intro": _("The same questions as the paper chart. Ask the patient and tick or write the answers."),
        "cancel_url": patient.get_absolute_url(),
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
