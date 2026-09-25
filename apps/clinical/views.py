from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST
from django.views.generic import ListView

from apps.core.forms import clean_digits_value
from apps.core.mixins import SearchMixin, role_required
from apps.core.models import branch_for_user
from apps.core.roles import CLINICAL, FRONT_DESK, INTERN, MANAGEMENT, has_role, is_only_intern
from apps.patients.access import get_visible_patient_or_403, visible_patients
from apps.scheduling.models import Appointment, day_bounds

from .forms import LabActionForm, LabFilterForm, LabRequestForm, StepFilterForm, StepReviewForm, TreatmentStepForm
from .models import LabRequest, LabRequestEvent, TreatmentStep
from .services import ACTION_LABELS, TRANSITIONS, available_actions, perform_lab_action

ANY_STAFF = FRONT_DESK + (INTERN,)


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


# ------------------------------------------------------------ treatment steps
class StepListView(SearchMixin, ListView):
    template_name = "clinical/step_list.html"
    paginate_by = 50

    def get_queryset(self):
        if not has_role(self.request.user, *ANY_STAFF):
            raise PermissionDenied
        self.filter_form = StepFilterForm(self.request.GET or None)
        qs = TreatmentStep.objects.select_related("patient", "step_type", "performed_by", "verified_by")
        if is_only_intern(self.request.user):
            qs = qs.filter(performed_by=self.request.user)
        if self.filter_form.is_valid():
            data = self.filter_form.cleaned_data
            if data.get("date_from"):
                qs = qs.filter(performed_at__gte=day_bounds(data["date_from"])[0])
            if data.get("date_to"):
                qs = qs.filter(performed_at__lt=day_bounds(data["date_to"])[1])
            if data.get("intern"):
                qs = qs.filter(performed_by=data["intern"])
            if data.get("step_type"):
                qs = qs.filter(step_type=data["step_type"])
            if data.get("unchecked"):
                qs = qs.filter(verified_at__isnull=True)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filter_form"] = self.filter_form
        return context


def step_create(request):
    if not has_role(request.user, *ANY_STAFF):
        raise PermissionDenied
    patient, appointment = _patient_and_appointment(request)
    initial = {"performed_at": timezone.localtime().replace(second=0, microsecond=0)}
    if appointment and appointment.intern_id:
        initial["performed_by"] = appointment.intern
    elif patient and patient.assigned_intern_id:
        initial["performed_by"] = patient.assigned_intern
    form = TreatmentStepForm(request.POST or None, user=request.user, patient=patient, initial=initial)
    if request.method == "POST" and form.is_valid():
        step = form.save(commit=False)
        step.patient = form.cleaned_data["patient_lookup"]
        step.appointment = appointment if appointment and appointment.patient_id == step.patient.pk else None
        if is_only_intern(request.user):
            step.performed_by = request.user
        step.created_by = request.user
        step.save()
        messages.success(request, _("Treatment step saved."))
        return redirect(reverse("patients:detail", args=[step.patient_id]) + "#steps")
    return render(
        request, "clinical/step_form.html",
        {"form": form, "title": _("Record treatment step"), "appointment": appointment},
    )


def step_detail(request, pk):
    step = get_object_or_404(
        TreatmentStep.objects.select_related("patient", "step_type", "performed_by", "verified_by", "appointment"),
        pk=pk,
    )
    get_visible_patient_or_403(request.user, step.patient_id)
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
            messages.success(request, _("Step checked."))
            return redirect("clinical:step_detail", pk=step.pk)
    return render(request, "clinical/step_detail.html", {"step": step, "review_form": form})


# ------------------------------------------------------------ lab requests
class LabListView(SearchMixin, ListView):
    template_name = "clinical/lab_list.html"
    paginate_by = 50

    def get_queryset(self):
        user = self.request.user
        if not has_role(user, *ANY_STAFF):
            raise PermissionDenied
        self.filter_form = LabFilterForm(self.request.GET or None)
        qs = LabRequest.objects.select_related("patient", "work_type", "lab", "requested_by")
        if is_only_intern(user):
            qs = qs.filter(Q(requested_by=user) | Q(patient__assigned_intern=user))
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
                qs = qs.filter(requested_by=user)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filter_form"] = self.filter_form
        return context


def lab_create(request):
    if not has_role(request.user, *CLINICAL, *FRONT_DESK):
        raise PermissionDenied
    patient, appointment = _patient_and_appointment(request)
    initial = {}
    if patient and patient.assigned_intern_id:
        initial["requested_by"] = patient.assigned_intern
    form = LabRequestForm(request.POST or None, user=request.user, patient=patient, initial=initial)
    if request.method == "POST" and form.is_valid():
        lab_request = form.save(commit=False)
        lab_request.patient = form.cleaned_data["patient_lookup"]
        lab_request.branch = branch_for_user(request.user)
        lab_request.appointment = appointment if appointment and appointment.patient_id == lab_request.patient.pk else None
        if is_only_intern(request.user):
            lab_request.requested_by = request.user
        lab_request.created_by = request.user
        lab_request.save()
        LabRequestEvent.objects.create(request=lab_request, action=LabRequestEvent.Action.CREATED, by=request.user)
        if "submit_for_review" in request.POST:
            perform_lab_action(lab_request, "submit", request.user)
            messages.success(request, _("Lab request saved and sent to the supervisor for review."))
        else:
            messages.success(request, _("Lab request saved as draft."))
        return redirect(lab_request)
    return render(request, "clinical/lab_form.html", {"form": form, "title": _("New lab request")})


def lab_edit(request, pk):
    lab_request = get_object_or_404(LabRequest, pk=pk)
    get_visible_patient_or_403(request.user, lab_request.patient_id)
    editable = lab_request.status in (LabRequest.Status.DRAFT, LabRequest.Status.PENDING_REVIEW)
    own = lab_request.requested_by_id == request.user.pk
    if not editable or not (own or has_role(request.user, *FRONT_DESK)):
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
            "patient", "work_type", "lab", "requested_by", "reviewed_by", "sent_by", "received_by"
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
            and (lab_request.requested_by_id == request.user.pk or has_role(request.user, *FRONT_DESK)),
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


@role_required(*FRONT_DESK, INTERN)
def lab_print(request, pk):
    lab_request = get_object_or_404(LabRequest.objects.select_related("patient", "work_type", "lab", "requested_by"), pk=pk)
    get_visible_patient_or_403(request.user, lab_request.patient_id)
    return render(request, "clinical/lab_print.html", {"lab_request": lab_request})
