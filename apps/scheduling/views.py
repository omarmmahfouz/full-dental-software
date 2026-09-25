from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST
from django.views.generic import ListView

from apps.clinical.models import LabRequest
from apps.core.mixins import SearchMixin, role_required
from apps.core.models import branch_for_user
from apps.core.roles import FRONT_DESK, INTERN, has_role, is_only_intern
from apps.patients.access import get_visible_patient_or_403
from apps.patients.models import Patient

from .forms import AppointmentFilterForm, AppointmentForm, CancelForm, RoomShiftForm, WalkInForm
from .models import Appointment, Room, RoomShift, day_bounds


def _parse_day(value, default=None):
    parsed = parse_date(value) if value else None
    return parsed or default or timezone.localdate()


def _safe_next(request, fallback):
    target = request.POST.get("next") or request.GET.get("next")
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
        return target
    return fallback


def week_start(day):
    """Weeks start on Saturday (Egyptian working week)."""
    return day - timedelta(days=(day.weekday() - 5) % 7)


# ------------------------------------------------------------ reception board
@role_required(*FRONT_DESK)
def today_board(request):
    day = _parse_day(request.GET.get("day"))
    start, end = day_bounds(day)
    branch = branch_for_user(request.user)
    appointments = (
        Appointment.objects.filter(branch=branch, scheduled_at__gte=start, scheduled_at__lt=end)
        .select_related("patient", "room", "intern")
        .prefetch_related("patient__medical_conditions")
        .annotate(
            open_labs=Count(
                "patient__lab_requests",
                filter=Q(patient__lab_requests__status__in=LabRequest.OPEN_STATUSES),
                distinct=True,
            )
        )
        .order_by("scheduled_at")
    )
    rooms = Room.objects.filter(branch=branch, is_active=True).prefetch_related(
        Prefetch("shifts", queryset=RoomShift.objects.filter(date=day).select_related("intern", "supervisor"),
                 to_attr="day_shifts")
    )
    return render(
        request,
        "scheduling/today.html",
        {
            "day": day,
            "is_today": day == timezone.localdate(),
            "prev_day": day - timedelta(days=1),
            "next_day": day + timedelta(days=1),
            "appointments": appointments,
            "rooms": rooms,
            "walk_in_form": WalkInForm(),
            "late_threshold": settings.CLINIC["LATE_THRESHOLD_MINUTES"],
        },
    )


@role_required(*FRONT_DESK)
@require_POST
def walk_in(request):
    form = WalkInForm(request.POST)
    if not form.is_valid():
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
        return redirect("scheduling:today")
    patient = form.cleaned_data["patient_lookup"]
    now = timezone.now()
    appointment = Appointment(
        branch=branch_for_user(request.user),
        patient=patient,
        scheduled_at=now,
        duration_minutes=settings.CLINIC["DEFAULT_APPOINTMENT_MINUTES"],
        intern=form.cleaned_data.get("intern") or patient.assigned_intern,
        purpose=form.cleaned_data.get("purpose", ""),
        is_walk_in=True,
        created_by=request.user,
    )
    shift = appointment.find_shift()
    appointment.room = shift.room if shift else None
    appointment.mark_arrived(now)
    appointment.save()
    messages.success(request, _("%(name)s registered as arrived (walk-in).") % {"name": patient.full_name})
    return redirect("scheduling:today")


APPOINTMENT_ACTIONS = {
    "confirm": gettext_lazy("confirmed"),
    "arrive": gettext_lazy("arrived"),
    "enter": gettext_lazy("entered the room"),
    "leave": gettext_lazy("left"),
    "no_show": gettext_lazy("did not come"),
    "cancel": gettext_lazy("cancelled"),
    "undo": gettext_lazy("last step undone"),
}


@role_required(*FRONT_DESK)
@require_POST
def appointment_action(request, pk):
    appointment = get_object_or_404(Appointment.objects.select_related("patient"), pk=pk)
    action = request.POST.get("action")
    now = timezone.now()
    if action == "confirm":
        appointment.status = Appointment.Status.CONFIRMED
    elif action == "arrive":
        appointment.mark_arrived(now)
    elif action == "enter":
        room_id = request.POST.get("room")
        if room_id and room_id.isdigit():
            appointment.room = Room.objects.filter(pk=room_id).first() or appointment.room
        appointment.mark_entered_room(now)
    elif action == "leave":
        appointment.mark_left(now)
    elif action in ("no_show", "cancel"):
        form = CancelForm(request.POST)
        form.is_valid()
        appointment.status = Appointment.Status.NO_SHOW if action == "no_show" else Appointment.Status.CANCELLED
        appointment.cancel_reason = form.cleaned_data.get("reason", "")
    elif action == "undo":
        appointment.undo_last_step()
    else:
        messages.error(request, _("Unknown action."))
        return redirect(_safe_next(request, reverse("scheduling:today")))
    appointment.save()
    messages.success(
        request, _("%(name)s: %(action)s.") % {"name": appointment.patient.full_name, "action": APPOINTMENT_ACTIONS[action]}
    )
    return redirect(_safe_next(request, reverse("scheduling:today")))


# ------------------------------------------------------------ appointments
class AppointmentListView(SearchMixin, ListView):
    template_name = "scheduling/appointment_list.html"
    paginate_by = 50

    def get_queryset(self):
        self.filter_form = AppointmentFilterForm(self.request.GET or None)
        qs = Appointment.objects.select_related("patient", "room", "intern")
        if is_only_intern(self.request.user):
            qs = qs.filter(intern=self.request.user)
        elif not has_role(self.request.user, *FRONT_DESK):
            raise PermissionDenied
        today = timezone.localdate()
        date_from, date_to = today, today + timedelta(days=7)
        if self.filter_form.is_valid():
            data = self.filter_form.cleaned_data
            date_from = data.get("date_from") or date_from
            date_to = data.get("date_to") or date_to
            if data.get("intern"):
                qs = qs.filter(intern=data["intern"])
            if data.get("room"):
                qs = qs.filter(room=data["room"])
            if data.get("status"):
                qs = qs.filter(status=data["status"])
        self.date_from, self.date_to = date_from, date_to
        start, _end = day_bounds(date_from)
        _start, end = day_bounds(date_to)
        return qs.filter(scheduled_at__gte=start, scheduled_at__lt=end).order_by("scheduled_at")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({"filter_form": self.filter_form, "date_from": self.date_from, "date_to": self.date_to})
        return context


@role_required(*FRONT_DESK)
def appointment_create(request):
    branch = branch_for_user(request.user)
    patient = None
    patient_id = request.GET.get("patient")
    if patient_id and patient_id.isdigit():
        patient = Patient.objects.filter(pk=patient_id).first()
    initial = {}
    if request.GET.get("at"):
        initial["scheduled_at"] = request.GET["at"]
    form = AppointmentForm(request.POST or None, branch=branch, patient=patient, initial=initial)
    if request.method == "POST" and form.is_valid():
        appointment = form.save(commit=False)
        appointment.branch = branch
        appointment.created_by = request.user
        appointment.save()
        messages.success(request, _("Appointment booked."))
        return redirect(appointment)
    return render(
        request, "includes/form_page.html",
        {"form": form, "title": _("Book appointment"), "cancel_url": reverse("scheduling:appointment_list")},
    )


@role_required(*FRONT_DESK)
def appointment_update(request, pk):
    appointment = get_object_or_404(Appointment, pk=pk)
    form = AppointmentForm(request.POST or None, instance=appointment, branch=appointment.branch)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Appointment updated."))
        return redirect(appointment)
    return render(
        request, "includes/form_page.html",
        {"form": form, "title": _("Edit appointment"), "cancel_url": appointment.get_absolute_url()},
    )


def appointment_detail(request, pk):
    appointment = get_object_or_404(Appointment.objects.select_related("patient", "room", "intern"), pk=pk)
    get_visible_patient_or_403(request.user, appointment.patient_id)
    return render(
        request,
        "scheduling/appointment_detail.html",
        {
            "appointment": appointment,
            "steps": appointment.treatment_steps.select_related("step_type", "performed_by"),
            "lab_requests": appointment.lab_requests.select_related("work_type"),
            "rooms": Room.objects.filter(branch=appointment.branch, is_active=True),
        },
    )


# ------------------------------------------------------------ room schedule
def room_schedule(request):
    if not has_role(request.user, *FRONT_DESK, INTERN):
        raise PermissionDenied
    start = week_start(_parse_day(request.GET.get("week")))
    days = [start + timedelta(days=i) for i in range(7)]
    branch = branch_for_user(request.user)
    rooms = list(Room.objects.filter(branch=branch, is_active=True))
    shifts = RoomShift.objects.filter(room__in=rooms, date__range=(days[0], days[-1])).select_related(
        "intern", "supervisor", "room"
    )
    only_mine = request.GET.get("mine") == "1"
    if only_mine:
        shifts = shifts.filter(intern=request.user)
    grid = {(s.room_id, s.date): [] for s in shifts}
    for shift in shifts:
        grid[(shift.room_id, shift.date)].append(shift)
    rows = [(room, [(day, grid.get((room.pk, day), [])) for day in days]) for room in rooms]
    return render(
        request,
        "scheduling/room_schedule.html",
        {
            "days": days,
            "rows": rows,
            "week": start,
            "prev_week": start - timedelta(days=7),
            "next_week": start + timedelta(days=7),
            "today": timezone.localdate(),
            "can_edit": has_role(request.user, *FRONT_DESK),
            "only_mine": only_mine,
        },
    )


@role_required(*FRONT_DESK)
def shift_edit(request, pk=None):
    shift = get_object_or_404(RoomShift, pk=pk) if pk else None
    branch = branch_for_user(request.user)
    initial = {}
    if shift is None:
        if request.GET.get("room", "").isdigit():
            initial["room"] = int(request.GET["room"])
        if request.GET.get("date"):
            initial["date"] = _parse_day(request.GET["date"])
        initial.setdefault("start_time", "09:00")
        initial.setdefault("end_time", "15:00")
    form = RoomShiftForm(request.POST or None, instance=shift, branch=branch, initial=initial)
    if request.method == "POST" and form.is_valid():
        shift = form.save(commit=False)
        if not shift.pk:
            shift.created_by = request.user
        shift.save()
        messages.success(request, _("Room schedule saved."))
        return redirect(f"{reverse('scheduling:room_schedule')}?week={week_start(shift.date).isoformat()}")
    return render(
        request, "includes/form_page.html",
        {"form": form, "title": _("Edit shift") if shift else _("Add room shift"),
         "cancel_url": reverse("scheduling:room_schedule")},
    )


@role_required(*FRONT_DESK)
@require_POST
def shift_delete(request, pk):
    shift = get_object_or_404(RoomShift, pk=pk)
    week = week_start(shift.date)
    shift.delete()
    messages.success(request, _("Shift deleted."))
    return redirect(f"{reverse('scheduling:room_schedule')}?week={week.isoformat()}")


@role_required(*FRONT_DESK)
@require_POST
def copy_previous_week(request):
    target = week_start(_parse_day(request.POST.get("week")))
    source = target - timedelta(days=7)
    branch = branch_for_user(request.user)
    copied = skipped = 0
    with transaction.atomic():
        for shift in RoomShift.objects.filter(room__branch=branch, date__range=(source, source + timedelta(days=6))):
            new = RoomShift(
                room=shift.room, date=shift.date + timedelta(days=7), start_time=shift.start_time,
                end_time=shift.end_time, intern=shift.intern, supervisor=shift.supervisor,
                notes=shift.notes, created_by=request.user,
            )
            try:
                new.full_clean()
            except ValidationError:
                skipped += 1
                continue
            new.save()
            copied += 1
    messages.success(
        request, _("%(copied)s shifts copied from last week (%(skipped)s skipped because of clashes).")
        % {"copied": copied, "skipped": skipped},
    )
    return redirect(f"{reverse('scheduling:room_schedule')}?week={target.isoformat()}")

