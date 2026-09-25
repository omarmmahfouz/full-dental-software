from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST
from django.views.generic import ListView

from apps.charting.models import ToothChange
from apps.charting.plans import complete_plan_items
from apps.charting.rules import apply_changes, plan_changes
from apps.charting.teeth import parse_teeth
from apps.core.forms import clean_digits_value
from apps.core.mixins import SearchMixin, role_required
from apps.core.models import ClinicSettings, branch_for_user
from apps.core.roles import CLINICAL, MANAGEMENT, PATIENT_VIEWERS, has_role, is_only_dentist
from apps.dentists.models import Dentist
from apps.patients.access import get_clinical_patient_or_403, get_visible_patient_or_403, visible_patients
from apps.scheduling.models import Appointment, day_bounds

from .forms import (
    LabActionForm, LabFilterForm, LabRequestForm, OutsideRequestForm, StepFilterForm, StepReviewForm, TreatmentStepForm,
)
from .models import LabRequest, LabRequestEvent, OutsideRequest, TreatmentStep
from .services import ACTION_LABELS, TRANSITIONS, available_actions, perform_lab_action

ANY_STAFF = PATIENT_VIEWERS


def _patient_and_appointment(request):
    """Pre-selected patient / visit passed as ?patient=&appointment= (validated for the user)."""
    patient = appointment = None
    source = request.POST if request.method == "POST" else request.GET
    patient_id = source.get("patient") or request.GET.get("patient")
    if patient_id and str(patient_id).isdigit():
        patient = visible_patients(request.user).filter(pk=patient_id).first()
    appointment_id = source.get("appointment") or request.GET.get("appointment")
    if patient and appointment_id and str(appointment_id).isdigit():
        appointment = Appointment.objects.filter(pk=appointment_id, patient=patient).first()
    return patient, appointment


def record_treatment_on_chart(step, user, update_chart=True):
    """Apply the treatment's chart effect (when confirmed) and tick matching plan items."""
    teeth = parse_teeth(step.teeth)
    changed = 0
    if update_chart and teeth:
        changes = plan_changes(step.patient, step.step_type.chart_effect, teeth, step.surfaces, step.material)
        changed = apply_changes(step.patient, changes, user, ToothChange.Source.TREATMENT, treatment=step,
                                when=step.performed_at)
        if changed:
            TreatmentStep.objects.filter(pk=step.pk).update(chart_updated=True)
    completed = complete_plan_items(step.patient, step.step_type, teeth, treatment=step, when=step.performed_at)
    return changed, completed


# ------------------------------------------------------------ treatment log
class StepListView(SearchMixin, ListView):
    template_name = "clinical/step_list.html"
    paginate_by = 50

    def get_queryset(self):
        if not has_role(self.request.user, *CLINICAL):
            raise PermissionDenied
        self.filter_form = StepFilterForm(self.request.GET or None)
        qs = TreatmentStep.objects.select_related(
            "patient", "step_type", "operator", "assistant", "supervisor", "verified_by"
        )
        if is_only_dentist(self.request.user):
            # Their own work, and what they recorded for the course candidates.
            me = Dentist.for_user(self.request.user)
            mine = Q(created_by=self.request.user)
            if me is not None:
                mine |= Q(operator=me) | Q(assistant=me)
            qs = qs.filter(mine)
        if self.filter_form.is_valid():
            data = self.filter_form.cleaned_data
            if data.get("date_from"):
                qs = qs.filter(performed_at__gte=day_bounds(data["date_from"])[0])
            if data.get("date_to"):
                qs = qs.filter(performed_at__lt=day_bounds(data["date_to"])[1])
            if data.get("dentist"):
                qs = qs.filter(Q(operator=data["dentist"]) | Q(assistant=data["dentist"]))
            if data.get("step_type"):
                qs = qs.filter(step_type=data["step_type"])
            if data.get("tooth"):
                qs = qs.filter(teeth__contains=data["tooth"])
            if data.get("unchecked"):
                qs = qs.filter(verified_at__isnull=True)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filter_form"] = self.filter_form
        return context


def step_create(request):
    if not has_role(request.user, *CLINICAL):
        raise PermissionDenied
    patient, appointment = _patient_and_appointment(request)
    me = Dentist.for_user(request.user)
    initial = {"performed_at": timezone.localtime().replace(second=0, microsecond=0)}
    # The operator is usually the candidate the patient is booked with; the CIA
    # dentist who writes it down assists.
    if appointment and appointment.dentist_id:
        initial["operator"] = appointment.dentist
    elif patient and patient.assigned_dentist_id:
        initial["operator"] = patient.assigned_dentist
    elif me is not None:
        initial["operator"] = me
    if me is not None and initial.get("operator") != me:
        initial["assistant"] = me
    form = TreatmentStepForm(request.POST or None, user=request.user, patient=patient, initial=initial)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            step = form.save(commit=False)
            step.patient = form.cleaned_data["patient_lookup"]
            step.appointment = appointment if appointment and appointment.patient_id == step.patient.pk else None
            step.created_by = request.user
            step.save()
            changed, completed = record_treatment_on_chart(step, request.user, form.cleaned_data.get("update_chart"))
        message = _("Treatment saved.")
        if changed:
            message += " " + _("Dental chart updated for %(n)s teeth.") % {"n": changed}
        if completed:
            message += " " + _("%(n)s treatment plan items marked as done.") % {"n": len(completed)}
        messages.success(request, message)
        if "add_another" in request.POST:
            return redirect(f"{reverse('clinical:step_create')}?patient={step.patient_id}")
        return redirect(reverse("charting:chart", args=[step.patient_id]))
    return render(
        request, "clinical/step_form.html",
        {"form": form, "title": _("Record treatment"), "appointment": appointment, "patient": patient},
    )


def step_detail(request, pk):
    step = get_object_or_404(
        TreatmentStep.objects.select_related(
            "patient", "step_type", "operator", "assistant", "supervisor", "verified_by", "appointment"
        ),
        pk=pk,
    )
    get_clinical_patient_or_403(request.user, step.patient_id)
    can_review = has_role(request.user, *MANAGEMENT)
    form = StepReviewForm(request.POST or None, instance=step) if can_review else None
    if request.method == "POST":
        if not can_review:
            raise PermissionDenied
        if form.is_valid():
            step = form.save(commit=False)
            step.verified_by = request.user
            step.verified_at = timezone.now()
            step.save()
            messages.success(request, _("Treatment checked."))
            return redirect("clinical:step_detail", pk=step.pk)
    return render(
        request, "clinical/step_detail.html",
        {"step": step, "review_form": form, "chart_changes": step.tooth_changes.all()},
    )


# ------------------------------------------------------------ lab requests
class LabListView(SearchMixin, ListView):
    template_name = "clinical/lab_list.html"
    paginate_by = 50

    def get_queryset(self):
        user = self.request.user
        if not has_role(user, *ANY_STAFF):
            raise PermissionDenied
        self.filter_form = LabFilterForm(self.request.GET or None)
        qs = LabRequest.objects.select_related("patient", "work_type", "lab", "dentist")
        me = Dentist.for_user(user)
        if is_only_dentist(user):
            qs = qs.filter(Q(dentist=me) | Q(patient__assigned_dentist=me)) if me else qs.none()
        if self.filter_form.is_valid():
            data = self.filter_form.cleaned_data
            q = clean_digits_value(data.get("q"))
            if q:
                qs = qs.filter(
                    Q(number__icontains=q) | Q(patient__full_name__icontains=q) | Q(patient__file_number__icontains=q)
                )
            status = data.get("status")
            if status == "open":
                qs = qs.filter(status__in=LabRequest.OPEN_STATUSES)
            elif status:
                qs = qs.filter(status=status)
            if data.get("lab"):
                qs = qs.filter(lab=data["lab"])
            if data.get("overdue"):
                qs = qs.filter(status=LabRequest.Status.SENT, due_date__lt=timezone.localdate())
            if data.get("mine"):
                qs = qs.filter(dentist=me) if me else qs.none()
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filter_form"] = self.filter_form
        return context


def lab_create(request):
    if not has_role(request.user, *ANY_STAFF):
        raise PermissionDenied
    patient, appointment = _patient_and_appointment(request)
    me = Dentist.for_user(request.user)
    initial = {}
    if appointment and appointment.dentist_id:
        initial["dentist"] = appointment.dentist
    elif patient and patient.assigned_dentist_id:
        initial["dentist"] = patient.assigned_dentist
    elif me is not None:
        initial["dentist"] = me
    form = LabRequestForm(request.POST or None, user=request.user, patient=patient, initial=initial)
    if request.method == "POST" and form.is_valid():
        lab_request = form.save(commit=False)
        lab_request.patient = form.cleaned_data["patient_lookup"]
        lab_request.branch = branch_for_user(request.user)
        lab_request.appointment = appointment if appointment and appointment.patient_id == lab_request.patient.pk else None
        lab_request.created_by = request.user
        lab_request.save()
        LabRequestEvent.objects.create(request=lab_request, action=LabRequestEvent.Action.CREATED, by=request.user)
        if "submit_for_review" in request.POST:
            perform_lab_action(lab_request, "submit", request.user)
            if lab_request.status == LabRequest.Status.APPROVED:
                messages.success(request, _("Lab request saved as reviewed by %(supervisor)s. The secretary will send it "
                                            "to the lab.") % {"supervisor": lab_request.supervisor})
            else:
                messages.success(request, _("Lab request saved and sent for review."))
        else:
            messages.success(request, _("Lab request saved as draft."))
        return redirect(lab_request)
    return render(request, "clinical/lab_form.html", {"form": form, "title": _("New lab request")})


def lab_edit(request, pk):
    lab_request = get_object_or_404(LabRequest.objects.select_related("dentist"), pk=pk)
    get_visible_patient_or_403(request.user, lab_request.patient_id)
    editable = lab_request.status in (LabRequest.Status.DRAFT, LabRequest.Status.PENDING_REVIEW)
    if not editable or not has_role(request.user, *ANY_STAFF):
        raise PermissionDenied
    form = LabRequestForm(request.POST or None, instance=lab_request, user=request.user, patient=lab_request.patient)
    if request.method == "POST" and form.is_valid():
        lab_request = form.save(commit=False)
        lab_request.patient = form.cleaned_data["patient_lookup"]
        lab_request.save()
        messages.success(request, _("Lab request updated."))
        return redirect(lab_request)
    return render(request, "clinical/lab_form.html", {"form": form, "title": _("Edit lab request"), "object": lab_request})


def lab_detail(request, pk):
    lab_request = get_object_or_404(
        LabRequest.objects.select_related(
            "patient", "work_type", "lab", "dentist", "supervisor", "reviewed_by", "sent_by", "received_by"
        ),
        pk=pk,
    )
    get_visible_patient_or_403(request.user, lab_request.patient_id)
    actions = [
        {"code": code, "label": ACTION_LABELS[code], "needs_check": TRANSITIONS[code][3], "needs_notes": TRANSITIONS[code][4]}
        for code in available_actions(lab_request, request.user)
    ]
    return render(
        request,
        "clinical/lab_detail.html",
        {
            "lab_request": lab_request,
            "events": lab_request.events.select_related("by"),
            "actions": actions,
            "can_edit": lab_request.status in (LabRequest.Status.DRAFT, LabRequest.Status.PENDING_REVIEW)
            and has_role(request.user, *ANY_STAFF),
        },
    )


@require_POST
def lab_action(request, pk):
    lab_request = get_object_or_404(LabRequest, pk=pk)
    get_visible_patient_or_403(request.user, lab_request.patient_id)
    form = LabActionForm(request.POST)
    form.is_valid()
    data = form.cleaned_data
    try:
        perform_lab_action(
            lab_request, data.get("action", ""), request.user, notes=data.get("notes", ""), checked=data.get("checked", False)
        )
    except ValidationError as error:
        for message in error.messages:
            messages.error(request, message)
    else:
        messages.success(request, _("Done: %(action)s") % {"action": ACTION_LABELS[data["action"]]})
    return redirect(lab_request)


@role_required(*ANY_STAFF)
def lab_print(request, pk):
    lab_request = get_object_or_404(LabRequest.objects.select_related("patient", "work_type", "lab", "dentist"), pk=pk)
    get_visible_patient_or_403(request.user, lab_request.patient_id)
    return render(request, "clinical/lab_print.html", {"lab_request": lab_request})


# ------------------------------------------------------------ CBCT and medical lab requests
@role_required(*ANY_STAFF)
def outside_create(request):
    patient_id = request.GET.get("patient", "")
    patient = get_visible_patient_or_403(request.user, int(patient_id)) if patient_id.isdigit() else None
    if patient is None:
        raise Http404
    kind = request.GET.get("kind")
    if kind not in OutsideRequest.Kind.values:
        kind = OutsideRequest.Kind.CBCT
    me = Dentist.for_user(request.user)
    form = OutsideRequestForm(request.POST or None, kind=kind, initial={
        "requested_on": timezone.localdate(), "dentist": me or patient.assigned_dentist})
    if request.method == "POST" and form.is_valid():
        outside = form.save(commit=False)
        outside.patient, outside.kind, outside.created_by = patient, kind, request.user
        outside.save()
        return redirect(outside)
    return render(request, "includes/form_page.html", {
        "form": form, "title": f"{OutsideRequest.Kind(kind).label} — {patient.full_name}",
        "cancel_url": patient.get_absolute_url(), "submit_label": _("Save and print"),
    })


@role_required(*ANY_STAFF)
def outside_print(request, pk):
    outside = get_object_or_404(OutsideRequest.objects.select_related("patient", "dentist"), pk=pk)
    get_visible_patient_or_403(request.user, outside.patient_id)
    return render(request, "clinical/outside_print.html", {
        "outside": outside, "dicom_email": ClinicSettings.get().dicom_email, "branch": branch_for_user(request.user),
    })
