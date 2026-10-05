from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Max, Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST
from django.views.generic import ListView

from apps.core.mixins import RoleRequiredMixin, role_required
from apps.core.models import Notification, branch_for_user
from apps.core.notify import notify_roles, notify_users
from apps.core.roles import FRONT_DESK, HEAD_CIA, OWNER, PATIENT_VIEWERS, SUPERVISOR, has_role, is_only_dentist
from apps.patients.forms import find_patient
from apps.patients.models import Patient

from .forms import ComplaintFilterForm, ComplaintForm, DentistAnswerForm, FollowUpEditForm, FollowUpForm, SituationForm
from .models import Complaint, ComplaintFollowUp


class ComplaintListView(RoleRequiredMixin, ListView):
    allowed_roles = PATIENT_VIEWERS  # CIA dentists may read the complaints
    template_name = "complaints/complaint_list.html"
    paginate_by = 40

    def get_queryset(self):
        self.filter_form = ComplaintFilterForm(self.request.GET or {"status": "open"})
        qs = Complaint.objects.visible_to(self.request.user).filter(
            branch=branch_for_user(self.request.user)).select_related(  # each place has its own complaints
            "patient", "assigned_to", "concerned_staff", "concerned_dentist"
        ).prefetch_related(Prefetch("follow_ups", queryset=ComplaintFollowUp.objects.select_related("created_by")
                                    .order_by("-created_at")))
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
        # Each patient's complaints together, under his name (round 15); the patient with the latest one first.
        self.grouped = not (self.filter_form.is_valid() and self.filter_form.cleaned_data.get("by_date"))
        if self.grouped:
            qs = qs.annotate(latest=Max("patient__complaints__created_at")).order_by(
                "-latest", "patient_id", "-created_at")
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filter_form"] = self.filter_form
        context["only_mine"] = is_only_dentist(self.request.user)
        context["grouped"] = self.grouped
        if self.grouped:
            ids = {c.patient_id for c in context["page_obj"]}
            context["per_patient"] = dict(Complaint.objects.filter(patient_id__in=ids).values_list("patient_id")
                                          .annotate(n=Count("pk")).values_list("patient_id", "n"))
        return context


@role_required(*FRONT_DESK)
def complaint_create(request):
    """A new complaint. The patient's complaints are shown first (round 15): the same reason again is written on the
    complaint he already has ("he called again"), another reason is a new complaint under his name."""
    patient = None
    wanted = request.GET.get("patient", "")
    if wanted.isdigit():
        patient = Patient.objects.here().filter(pk=wanted).first()
    elif wanted:
        patient = find_patient(wanted)  # chosen in the box: "CIA-00014 — name"
    form = ComplaintForm(request.POST or None, patient=patient)
    same = None
    if request.method == "POST" and form.is_valid():
        patient = form.cleaned_data["patient_lookup"]
        same = Complaint.objects.filter(patient=patient, category=form.cleaned_data["category"],
                                        status__in=Complaint.OPEN_STATUSES).order_by("-created_at").first()
        if same is not None and not request.POST.get("new_anyway"):
            # The same kind of complaint is still open: ask whether he called again about it.
            return render(request, "complaints/complaint_form.html", {
                "form": form, "title": _("Record patient complaint"), "patient": patient, "same": same,
                "earlier": _earlier(patient)})
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            complaint = form.save(commit=False)
            complaint.patient = form.cleaned_data["patient_lookup"]
            complaint.branch = branch_for_user(request.user)
            complaint.created_by = request.user
            complaint.save()
        notify_roles(
            (HEAD_CIA, SUPERVISOR, OWNER), gettext_lazy("New patient complaint %(number)s: %(patient)s"),
            "%(category)s — %(text)s", complaint.get_absolute_url(), _level(complaint), exclude=request.user,
            params=_params(complaint),
        )
        _tell_dentist(complaint)
        messages.success(request, _("Complaint %(number)s recorded and the supervisors were notified.") % {"number": complaint.number})
        return redirect(complaint)
    if patient is None and form.is_bound:
        patient = form.cleaned_data.get("patient_lookup")
    return render(request, "complaints/complaint_form.html", {
        "form": form, "title": _("Record patient complaint"), "patient": patient,
        "earlier": _earlier(patient) if patient is not None else []})


def _earlier(patient):
    """The patient's complaints, the open ones first."""
    complaints = list(Complaint.objects.filter(patient=patient).select_related("concerned_dentist")[:20])
    complaints.sort(key=lambda c: (not c.is_open, -c.created_at.timestamp()))
    return complaints


@role_required(*FRONT_DESK)
@require_POST
def complaint_called_again(request, pk):
    """The patient called again for the same reason: what he said is written on his complaint, the calls are counted
    and the people of the complaint are told; a closed complaint opens again (round 15)."""
    complaint = get_object_or_404(Complaint.objects.select_related("concerned_dentist", "patient"), pk=pk,
                                  branch=branch_for_user(request.user))
    note = (request.POST.get("note") or "").strip()
    if not note:
        messages.error(request, _("Write what the patient said this time."))
        return redirect(f"{reverse('complaints:create')}?patient={complaint.patient_id}")
    with transaction.atomic():
        reopened = not complaint.is_open
        complaint.calls += 1
        complaint.last_call_at = timezone.now()
        if reopened:
            complaint.status = Complaint.Status.IN_PROGRESS
        ComplaintFollowUp.objects.create(
            complaint=complaint, action=ComplaintFollowUp.Action.CALLED_AGAIN, note=note[:4000],
            new_status=complaint.status, created_by=request.user)
        complaint.save()
    dentist_user = complaint.concerned_dentist.user if complaint.concerned_dentist_id else None
    params = {"number": complaint.number, "patient": complaint.patient.full_name, "n": complaint.calls,
              "note": note[:300]}
    notify_users([complaint.created_by, complaint.assigned_to, dentist_user],
                 gettext_lazy("%(patient)s called again about complaint %(number)s (call %(n)s)"), "%(note)s",
                 complaint.get_absolute_url(), _level(complaint), exclude=request.user, params=params)
    notify_roles((HEAD_CIA, OWNER), gettext_lazy("%(patient)s called again about complaint %(number)s (call %(n)s)"),
                 "%(note)s", complaint.get_absolute_url(), _level(complaint), exclude=request.user, params=params)
    messages.success(request, _("Written on complaint %(number)s: the patient has called %(n)s times.")
                     % {"number": complaint.number, "n": complaint.calls})
    return redirect(complaint)


def _level(complaint):
    return Notification.Level.DANGER if complaint.severity == Complaint.Severity.HIGH else Notification.Level.WARNING


def _params(complaint):
    return {
        "number": complaint.number,
        "patient": complaint.patient.full_name,
        "category": complaint.get_category_display(),
        "text": complaint.description[:300],
    }


def _tell_dentist(complaint):
    """The concerned dentist is told at once and asked for his answer."""
    dentist = complaint.concerned_dentist
    if dentist is not None and dentist.user_id:
        notify_users([dentist.user], gettext_lazy("Complaint %(number)s about your patient: please answer"),
                     "%(category)s — %(text)s", complaint.get_absolute_url(), _level(complaint),
                     params=_params(complaint))


@role_required(*FRONT_DESK)
def complaint_update(request, pk):
    complaint = get_object_or_404(Complaint, pk=pk)
    dentist_before = complaint.concerned_dentist_id
    form = ComplaintForm(request.POST or None, instance=complaint)
    if request.method == "POST" and form.is_valid():
        complaint = form.save(commit=False)
        complaint.patient = form.cleaned_data["patient_lookup"]
        complaint.save()
        if complaint.concerned_dentist_id != dentist_before:
            _tell_dentist(complaint)
        messages.success(request, _("Complaint updated."))
        return redirect(complaint)
    return render(
        request, "includes/form_page.html",
        {"form": form, "title": _("Edit complaint"), "cancel_url": complaint.get_absolute_url()},
    )


@role_required(*PATIENT_VIEWERS)
def complaint_detail(request, pk):
    complaint = get_object_or_404(
        Complaint.objects.visible_to(request.user).select_related(
            "patient", "assigned_to", "concerned_staff", "concerned_dentist", "resolved_by", "situation_updated_by"
        ), pk=pk,
    )
    return render(request, "complaints/complaint_detail.html", _detail_context(request, complaint))


def _detail_context(request, complaint, **extra):
    follow_ups = list(complaint.follow_ups.select_related("created_by"))
    for follow_up in follow_ups:
        follow_up.can_edit = _can_edit_follow_up(request.user, follow_up)
    context = {
        "complaint": complaint,
        "follow_ups": follow_ups,
        "form": FollowUpForm(complaint=complaint),
        "situation_form": SituationForm(instance=complaint),
        "answer_form": DentistAnswerForm() if _can_answer(request.user, complaint) else None,
    }
    context.update(extra)
    return context


def _can_edit_follow_up(user, follow_up):
    """The one who wrote it (the dentist's answer too) or the heads may correct a follow-up."""
    return follow_up.created_by_id == user.pk or has_role(user, OWNER, HEAD_CIA)


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
        return render(request, "complaints/complaint_detail.html", _detail_context(request, complaint, form=form))
    with transaction.atomic():
        follow_up = form.save(commit=False)
        follow_up.complaint = complaint
        follow_up.created_by = request.user
        follow_up.save()
        complaint.set_situation(form.cleaned_data["current_situation"], request.user)
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


@role_required(*PATIENT_VIEWERS)
@require_POST
def complaint_comment(request, pk):
    """Round 13: a comment written on the spot (the list opens a complaint in place, or the top of its page). It is
    kept as a follow-up step that does not change the status; the people of the complaint are told."""
    from django.http import JsonResponse
    from django.template.loader import render_to_string
    from django.utils.http import url_has_allowed_host_and_scheme

    complaint = get_object_or_404(Complaint.objects.visible_to(request.user).select_related("concerned_dentist"),
                                  pk=pk)
    note = (request.POST.get("note") or "").strip()
    wants_json = request.headers.get("x-requested-with") == "fetch"
    if not note:
        if wants_json:
            return JsonResponse({"ok": False, "error": _("Write the comment first.")}, status=400)
        messages.error(request, _("Write the comment first."))
        return redirect(complaint)
    follow_up = ComplaintFollowUp.objects.create(
        complaint=complaint, action=ComplaintFollowUp.Action.NOTE, note=note[:4000], new_status=complaint.status,
        created_by=request.user)
    complaint.save(update_fields=["updated_at"])
    dentist_user = complaint.concerned_dentist.user if complaint.concerned_dentist_id else None
    notify_users([complaint.created_by, complaint.assigned_to, dentist_user],
                 gettext_lazy("%(who)s commented on complaint %(number)s"), "%(note)s", complaint.get_absolute_url(),
                 exclude=request.user, params={"number": complaint.number, "who": request.user, "note": note[:300]})
    if wants_json:
        follow_up.can_edit = _can_edit_follow_up(request.user, follow_up)
        return JsonResponse({"ok": True, "html": render_to_string("complaints/_follow_up.html", {
            "f": follow_up, "complaint": complaint}, request=request)})
    messages.success(request, _("Comment saved."))
    back = request.POST.get("next") or ""
    if back and url_has_allowed_host_and_scheme(back, allowed_hosts={request.get_host()}):
        return redirect(back)
    return redirect(complaint)


@role_required(*FRONT_DESK)
@require_POST
def complaint_situation(request, pk):
    """The reception writes where the case stands now, without adding a follow-up step."""
    complaint = get_object_or_404(Complaint, pk=pk)
    form = SituationForm(request.POST, instance=complaint)
    if form.is_valid():
        complaint.set_situation(form.cleaned_data["current_situation"], request.user)
        complaint.save(update_fields=["current_situation", "situation_updated_at", "situation_updated_by", "updated_at"])
        messages.success(request, _("Current situation saved."))
    return redirect(complaint)


@role_required(*PATIENT_VIEWERS)
def complaint_follow_up_edit(request, pk, follow_up_pk):
    complaint = get_object_or_404(Complaint.objects.visible_to(request.user), pk=pk)
    follow_up = get_object_or_404(ComplaintFollowUp, pk=follow_up_pk, complaint=complaint)
    if not _can_edit_follow_up(request.user, follow_up):
        raise PermissionDenied
    form = FollowUpEditForm(request.POST or None, instance=follow_up)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            follow_up = form.save(commit=False)
            follow_up.edited_at = timezone.now()
            follow_up.save()
            last = complaint.follow_ups.order_by("-created_at").first()
            if last is not None and last.pk == follow_up.pk and complaint.is_open:
                complaint.follow_up_due = follow_up.next_follow_up or complaint.follow_up_due
                complaint.save(update_fields=["follow_up_due", "updated_at"])
        messages.success(request, _("Follow-up corrected."))
        return redirect(complaint)
    return render(request, "includes/form_page.html", {
        "form": form, "title": _("Correct the follow-up of %(number)s") % {"number": complaint.number},
        "cancel_url": complaint.get_absolute_url(),
    })
