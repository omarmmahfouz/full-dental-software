from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST
from django.views.generic import ListView

from apps.core.mixins import RoleRequiredMixin, role_required
from apps.core.models import Notification, branch_for_user
from apps.core.notify import notify_roles, notify_users
from apps.core.roles import FRONT_DESK, HEAD_CIA, OWNER, PATIENT_VIEWERS, SUPERVISOR, has_role
from apps.patients.models import Patient

from .forms import ComplaintFilterForm, ComplaintForm, DentistAnswerForm, FollowUpForm
from .models import Complaint, ComplaintFollowUp


class ComplaintListView(RoleRequiredMixin, ListView):
    allowed_roles = PATIENT_VIEWERS  # CIA dentists may read the complaints
    template_name = "complaints/complaint_list.html"
    paginate_by = 40

    def get_queryset(self):
        self.filter_form = ComplaintFilterForm(self.request.GET or {"status": "open"})
        qs = Complaint.objects.select_related("patient", "assigned_to", "concerned_staff", "concerned_dentist")
        if self.filter_form.is_valid():
            data = self.filter_form.cleaned_data
            if data.get("status") == "open":
                qs = qs.filter(status__in=Complaint.OPEN_STATUSES)
            elif data.get("status"):
                qs = qs.filter(status=data["status"])
            if data.get("category"):
                qs = qs.filter(category=data["category"])
            if data.get("overdue"):
                qs = qs.filter(status__in=Complaint.OPEN_STATUSES, follow_up_due__lt=timezone.localdate())
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filter_form"] = self.filter_form
        return context


@role_required(*FRONT_DESK)
def complaint_create(request):
    patient = None
    if request.GET.get("patient", "").isdigit():
        patient = Patient.objects.filter(pk=request.GET["patient"]).first()
    form = ComplaintForm(request.POST or None, patient=patient)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            complaint = form.save(commit=False)
            complaint.patient = form.cleaned_data["patient_lookup"]
            complaint.branch = branch_for_user(request.user)
            complaint.created_by = request.user
            complaint.save()
        level = Notification.Level.DANGER if complaint.severity == Complaint.Severity.HIGH else Notification.Level.WARNING
        params = {
            "number": complaint.number,
            "patient": complaint.patient.full_name,
            "category": complaint.get_category_display(),
            "text": complaint.description[:300],
        }
        notify_roles(
            (HEAD_CIA, SUPERVISOR, OWNER), gettext_lazy("New patient complaint %(number)s: %(patient)s"),
            "%(category)s — %(text)s", complaint.get_absolute_url(), level, exclude=request.user, params=params,
        )
        dentist = complaint.concerned_dentist
        if dentist is not None and dentist.user_id:
            notify_users([dentist.user], gettext_lazy("Complaint %(number)s about your patient: please answer"),
                         "%(category)s — %(text)s", complaint.get_absolute_url(), level, params=params)
        messages.success(request, _("Complaint %(number)s recorded and the supervisors were notified.") % {"number": complaint.number})
        return redirect(complaint)
    return render(request, "includes/form_page.html", {"form": form, "title": _("Record patient complaint")})


@role_required(*FRONT_DESK)
def complaint_update(request, pk):
    complaint = get_object_or_404(Complaint, pk=pk)
    form = ComplaintForm(request.POST or None, instance=complaint)
    if request.method == "POST" and form.is_valid():
        complaint = form.save(commit=False)
        complaint.patient = form.cleaned_data["patient_lookup"]
        complaint.save()
        messages.success(request, _("Complaint updated."))
        return redirect(complaint)
    return render(
        request, "includes/form_page.html",
        {"form": form, "title": _("Edit complaint"), "cancel_url": complaint.get_absolute_url()},
    )


@role_required(*PATIENT_VIEWERS)
def complaint_detail(request, pk):
    complaint = get_object_or_404(
        Complaint.objects.select_related("patient", "assigned_to", "concerned_staff", "concerned_dentist", "resolved_by"), pk=pk
    )
    return render(
        request,
        "complaints/complaint_detail.html",
        {
            "complaint": complaint,
            "follow_ups": complaint.follow_ups.select_related("created_by"),
            "form": FollowUpForm(complaint=complaint),
            "answer_form": DentistAnswerForm() if _can_answer(request.user, complaint) else None,
        },
    )


def _can_answer(user, complaint):
    dentist = complaint.concerned_dentist
    return complaint.is_open and ((dentist is not None and dentist.user_id == user.pk) or has_role(user, OWNER, HEAD_CIA))


@require_POST
def complaint_answer(request, pk):
    """The concerned dentist writes his answer and what will be done to solve the complaint."""
    complaint = get_object_or_404(Complaint.objects.select_related("concerned_dentist"), pk=pk)
    if not _can_answer(request.user, complaint):
        raise PermissionDenied
    form = DentistAnswerForm(request.POST)
    if not form.is_valid():
        messages.error(request, _("Write your answer."))
        return redirect(complaint)
    with transaction.atomic():
        ComplaintFollowUp.objects.create(
            complaint=complaint, action=ComplaintFollowUp.Action.DENTIST_ANSWER, note=form.cleaned_data["note"],
            new_status=Complaint.Status.IN_PROGRESS, next_follow_up=form.cleaned_data["next_follow_up"],
            created_by=request.user,
        )
        complaint.status = Complaint.Status.IN_PROGRESS
        complaint.follow_up_due = form.cleaned_data["next_follow_up"] or complaint.follow_up_due
        complaint.save()
    params = {"number": complaint.number, "who": request.user, "note": form.cleaned_data["note"][:300]}
    notify_users([complaint.created_by, complaint.assigned_to], gettext_lazy("%(who)s answered complaint %(number)s"),
                 "%(note)s", complaint.get_absolute_url(), exclude=request.user, params=params)
    notify_roles((HEAD_CIA,), gettext_lazy("%(who)s answered complaint %(number)s"), "%(note)s",
                 complaint.get_absolute_url(), exclude=request.user, params=params)
    messages.success(request, _("Your answer was saved and the reception and the head of CIA were told."))
    return redirect(complaint)


@role_required(*FRONT_DESK)
@require_POST
def complaint_follow_up(request, pk):
    complaint = get_object_or_404(Complaint, pk=pk)
    form = FollowUpForm(request.POST, complaint=complaint)
    if not form.is_valid():
        return render(
            request, "complaints/complaint_detail.html",
            {"complaint": complaint, "follow_ups": complaint.follow_ups.select_related("created_by"), "form": form},
        )
    with transaction.atomic():
        follow_up = form.save(commit=False)
        follow_up.complaint = complaint
        follow_up.created_by = request.user
        follow_up.save()
        complaint.status = follow_up.new_status
        complaint.follow_up_due = follow_up.next_follow_up
        if complaint.assigned_to_id is None:
            complaint.assigned_to = request.user
        if follow_up.new_status in (Complaint.Status.RESOLVED, Complaint.Status.CLOSED) and not complaint.resolved_at:
            complaint.resolved_at = timezone.now()
            complaint.resolved_by = request.user
            complaint.resolution = complaint.resolution or follow_up.note
        complaint.save()
    notify_users(
        [complaint.created_by, complaint.assigned_to],
        gettext_lazy("Complaint %(number)s updated: %(status)s"), "%(note)s", complaint.get_absolute_url(),
        exclude=request.user,
        params={"number": complaint.number, "status": complaint.get_status_display(), "note": follow_up.note[:300]},
    )
    messages.success(request, _("Follow-up saved."))
    return redirect(complaint)
