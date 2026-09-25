"""The CIA dentist's list of patients for his days (instead of filling the calendar himself):

1. the dentist adds the patients he wants, the step, the time needed and the order (main list
   by priority, and a backup list);
2. the supervisor (head of CIA / team head) approves each one and may change the time given;
3. the reception calls them in order and books them; when a main patient cannot come, the
   next patient of the backup list is called.
"""

from datetime import timedelta
from urllib.parse import urlencode

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from apps.core.mixins import role_required
from apps.core.models import Notification
from apps.core.notify import notify_users
from apps.core.roles import FRONT_DESK, HEAD_CIA, OWNER, SUPERVISOR, TEAM_HEAD, users_with_role
from apps.dentists.models import Dentist

from .forms import PatientRequestForm, duration_choices
from .models import PatientRequest, RoomShift

APPROVERS = (OWNER, HEAD_CIA, TEAM_HEAD, SUPERVISOR)


def _notify_once(users, title, url, level=Notification.Level.INFO, params=None):
    """One unread notification per person for the same list is enough."""
    users = [u for u in users if not u.notifications.filter(url=url, read_at__isnull=True).exists()]
    notify_users(users, title, "", url, level, params=params)


def _me(request):
    dentist = Dentist.for_user(request.user)
    if dentist is None:
        raise PermissionDenied(_("Only dentists with a login have a patient list."))
    return dentist


def my_requests(request):
    """The dentist's own list: add patients, see what the supervisor and the reception did."""
    dentist = _me(request)
    form = PatientRequestForm(request.POST or None, initial={
        "wanted_from": timezone.localdate() + timedelta(days=1)})
    if request.method == "POST" and form.is_valid():
        item = form.save(commit=False)
        item.dentist, item.patient, item.created_by = dentist, form.cleaned_data["patient_lookup"], request.user
        item.save()
        _notify_once(users_with_role(*APPROVERS), gettext_lazy("Dentists' patient lists to approve"),
                     reverse("scheduling:requests_approve"), Notification.Level.WARNING)
        messages.success(request, _("%(patient)s added. The supervisor will approve the list.")
                         % {"patient": item.patient.full_name})
        return redirect("scheduling:requests_mine")
    items = dentist.patient_requests.select_related("patient", "step_type", "appointment")
    recent = timezone.now() - timedelta(days=30)
    return render(request, "scheduling/requests_mine.html", {
        "form": form, "dentist": dentist,
        "open_items": [i for i in items if i.status in PatientRequest.OPEN],
        "done_items": [i for i in items.exclude(status__in=PatientRequest.OPEN).filter(updated_at__gte=recent)],
        "shifts": RoomShift.objects.filter(dentist=dentist, date__gte=timezone.localdate())
        .select_related("room").order_by("date", "start_time")[:14],
    })


@require_POST
def request_cancel(request, pk):
    item = get_object_or_404(PatientRequest, pk=pk, dentist=_me(request), status__in=PatientRequest.OPEN)
    item.status = PatientRequest.Status.CANCELLED
    item.save(update_fields=["status", "updated_at"])
    messages.success(request, _("Removed from your list."))
    return redirect("scheduling:requests_mine")


@role_required(*APPROVERS)
def approve_requests(request):
    """The supervisor approves each dentist's list and the time given to each patient."""
    if request.method == "POST":
        ids = request.POST.getlist("item")
        action = request.POST.get("action")
        items = PatientRequest.objects.filter(pk__in=ids, status=PatientRequest.Status.PROPOSED).select_related(
            "dentist__user", "patient")
        approved = 0
        for item in items:
            if action == "reject" and len(ids) == 1:
                item.status = PatientRequest.Status.REJECTED
            elif action == "approve":
                minutes = request.POST.get(f"minutes_{item.pk}", "")
                item.approved_minutes = int(minutes) if minutes.isdigit() else item.minutes
                item.status = PatientRequest.Status.APPROVED
                approved += 1
            else:
                continue
            item.decision_note = request.POST.get(f"note_{item.pk}", "").strip()[:255]
            item.decided_by, item.decided_at = request.user, timezone.now()
            item.save()
            if item.dentist.user_id:
                notify_users([item.dentist.user],
                             gettext_lazy("Approved: %(patient)s") if item.status == PatientRequest.Status.APPROVED
                             else gettext_lazy("Not approved: %(patient)s"),
                             item.decision_note.replace("%", "%%"), reverse("scheduling:requests_mine"),
                             params={"patient": item.patient.full_name})
        if approved:
            _notify_once(users_with_role(*FRONT_DESK), gettext_lazy("Patients to call for the dentists"),
                         reverse("scheduling:requests_reception"))
            messages.success(request, _("%(n)s patients approved and sent to the reception.") % {"n": approved})
        elif action == "reject":
            messages.success(request, _("Not approved. The dentist was told."))
        return redirect("scheduling:requests_approve")
    waiting = PatientRequest.objects.filter(status=PatientRequest.Status.PROPOSED).select_related(
        "dentist", "patient", "step_type").order_by("dentist__full_name", "-kind", "priority", "created_at")
    groups = {}
    for item in waiting:
        groups.setdefault(item.dentist, []).append(item)
    return render(request, "scheduling/requests_approve.html", {
        "groups": groups.items(), "durations": duration_choices(60),
        "decided": PatientRequest.objects.exclude(status=PatientRequest.Status.PROPOSED).filter(
            decided_at__isnull=False).select_related("dentist", "patient", "step_type").order_by("-decided_at")[:20],
    })


@role_required(*FRONT_DESK)
def reception_requests(request):
    """The reception calls the approved patients of each dentist in order, main list first."""
    today = timezone.localdate()
    items = PatientRequest.objects.filter(status=PatientRequest.Status.APPROVED).select_related(
        "dentist", "patient", "step_type").order_by("dentist__full_name", "-kind", "priority", "created_at")
    groups = {}
    for item in items:
        group = groups.setdefault(item.dentist, {"main": [], "backup": [], "cannot": []})
        group["main" if item.kind == PatientRequest.Kind.MAIN else "backup"].append(item)
    week_ago = timezone.now() - timedelta(days=7)
    for item in PatientRequest.objects.filter(status=PatientRequest.Status.CANNOT_COME, updated_at__gte=week_ago)\
            .select_related("dentist", "patient", "step_type"):
        groups.setdefault(item.dentist, {"main": [], "backup": [], "cannot": []})["cannot"].append(item)
    for dentist, group in groups.items():
        group["shifts"] = RoomShift.objects.filter(dentist=dentist, date__gte=today).select_related("room")\
            .order_by("date", "start_time")[:10]
        group["call_backup"] = bool(group["cannot"]) and bool(group["backup"])
        for item in group["main"] + group["backup"]:
            item.book_url = reverse("scheduling:appointment_create") + "?" + urlencode({
                "patient": item.patient_id, "dentist": item.dentist_id, "duration": item.time_given,
                "purpose": f"{item.step_type} {item.teeth}".strip(), "request": item.pk,
            })
    return render(request, "scheduling/requests_reception.html", {"groups": groups.items()})


@role_required(*FRONT_DESK)
@require_POST
def request_cannot_come(request, pk):
    item = get_object_or_404(PatientRequest.objects.select_related("dentist__user", "patient"), pk=pk,
                             status=PatientRequest.Status.APPROVED)
    item.status = PatientRequest.Status.CANNOT_COME
    item.reception_note = request.POST.get("note", "").strip()[:255]
    item.save(update_fields=["status", "reception_note", "updated_at"])
    if item.dentist.user_id:
        notify_users([item.dentist.user], gettext_lazy("%(patient)s cannot come"),
                     gettext_lazy("The reception will call the next patient of your backup list."),
                     reverse("scheduling:requests_mine"), Notification.Level.WARNING,
                     params={"patient": item.patient.full_name})
    messages.success(request, _("Saved. Call the next patient of the backup list."))
    return redirect("scheduling:requests_reception")


def link_booking(request, appointment):
    """Called when the reception books from the list (?request=<pk>): the request becomes booked."""
    pk = request.GET.get("request", "")
    if not pk.isdigit():
        return None
    item = PatientRequest.objects.filter(pk=pk, patient=appointment.patient,
                                         status=PatientRequest.Status.APPROVED).first()
    if item is not None:
        item.status, item.appointment = PatientRequest.Status.BOOKED, appointment
        item.save(update_fields=["status", "appointment", "updated_at"])
    return item
