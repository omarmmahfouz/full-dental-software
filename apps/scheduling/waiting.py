"""The waiting list: patients who want a place on a busy day. When an appointment is
cancelled, missed or moved, the reception is told that a place is free and who is waiting."""

from urllib.parse import urlencode

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from apps.core.mixins import role_required
from apps.core.models import Notification
from apps.core.notify import notify_users
from apps.core.roles import FRONT_DESK, SECRETARY, users_with_role
from apps.patients.models import Patient

from .forms import WaitingEntryForm
from .models import WaitingEntry


def book_url(entry):
    params = {"patient": entry.patient_id, "duration": entry.minutes, "waiting": entry.pk}
    if entry.dentist_id:
        params["dentist"] = entry.dentist_id
    if entry.procedure_id:
        params["procedure"] = entry.procedure_id
    return f"{reverse('scheduling:appointment_create')}?{urlencode(params)}"


@role_required(*FRONT_DESK)
def waiting_list(request):
    patient = None
    if request.GET.get("patient", "").isdigit():
        patient = Patient.objects.filter(pk=request.GET["patient"]).first()
    initial = {"wanted_from": timezone.localdate()}
    if request.GET.get("dentist", "").isdigit():
        initial["dentist"] = int(request.GET["dentist"])
    form = WaitingEntryForm(request.POST or None, patient=patient, initial=initial)
    if request.method == "POST" and form.is_valid():
        entry = form.save(commit=False)
        entry.patient, entry.created_by = form.cleaned_data["patient_lookup"], request.user
        entry.save()
        messages.success(request, _("%(name)s added to the waiting list.") % {"name": entry.patient.full_name})
        return redirect("scheduling:waiting_list")
    entries = WaitingEntry.objects.filter(status=WaitingEntry.Status.WAITING).select_related(
        "patient", "dentist", "procedure")
    day = request.GET.get("day", "")
    if day:
        from .views import _parse_day

        chosen = _parse_day(day)
        entries = WaitingEntry.for_place(chosen, request.GET.get("for_dentist") or None)
    rows = [{"entry": e, "book_url": book_url(e)} for e in entries]
    return render(request, "scheduling/waiting_list.html", {"form": form, "rows": rows, "day": day})


@role_required(*FRONT_DESK)
@require_POST
def waiting_remove(request, pk):
    entry = get_object_or_404(WaitingEntry, pk=pk, status=WaitingEntry.Status.WAITING)
    entry.status = WaitingEntry.Status.REMOVED
    entry.save(update_fields=["status", "updated_at"])
    messages.success(request, _("Removed from the waiting list."))
    return redirect("scheduling:waiting_list")


def place_freed(appointment, request):
    """A place is free (cancelled, missed, came late or moved): tell the reception who is waiting."""
    day = timezone.localtime(appointment.scheduled_at).date()
    if day < timezone.localdate():
        return 0
    waiting = list(WaitingEntry.for_place(day, appointment.dentist_id))
    if not waiting:
        return 0
    when = timezone.localtime(appointment.scheduled_at).strftime("%d/%m/%Y %I:%M %p")
    url = f"{reverse('scheduling:waiting_list')}?day={day:%Y-%m-%d}&for_dentist={appointment.dentist_id or ''}"
    notify_users(users_with_role(SECRETARY), gettext_lazy("A place is free on %(when)s"),
                 gettext_lazy("%(n)s patients are on the waiting list for this day."), url,
                 Notification.Level.WARNING, params={"when": when, "n": len(waiting)})
    messages.info(request, _("A place is free: %(n)s patients are waiting for this day. Open the waiting list to "
                             "call them.") % {"n": len(waiting)})
    return len(waiting)


def link_waiting(request, appointment):
    """Booked from the waiting list (?waiting=<pk>)."""
    pk = request.GET.get("waiting", "")
    if pk.isdigit():
        WaitingEntry.objects.filter(pk=pk, patient=appointment.patient, status=WaitingEntry.Status.WAITING).update(
            status=WaitingEntry.Status.BOOKED, appointment=appointment, updated_at=timezone.now())
