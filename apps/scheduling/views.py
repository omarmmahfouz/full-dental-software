from datetime import datetime, timedelta

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST
from django.views.generic import ListView

from apps.clinical.models import LabRequest
from apps.core.approvals import needs_approval, pending_for, request_change
from apps.core.mixins import SearchMixin, role_required
from apps.core.notify import notify_users
from apps.core.models import ChangeRequest, ClinicSettings, branch_for_user
from apps.core.access import area_levels
from apps.core.roles import FRONT_DESK, HEAD_CIA, OWNER, PATIENT_VIEWERS, SECRETARY, has_role, is_only_dentist
from apps.core.utils import normalize_digits
from apps.dentists.models import Dentist
from apps.patients.access import get_visible_patient_or_403
from apps.patients.models import Patient

from .daygrid import day_grid, week_outline
from .forms import (
    AppointmentFilterForm, AppointmentForm, CancelForm, RescheduleForm, RoomShiftForm, VisitTimesForm, WalkInForm,
)
from .models import Appointment, MessageTemplate, Room, RoomShift, day_bounds
from .patient_requests import link_booking
from .whatsapp import record, whatsapp_number


def _parse_day(value, default=None):
    parsed = None
    if value:
        value = normalize_digits(value).strip()
        try:
            parsed = parse_date(value) or datetime.strptime(value, "%d/%m/%Y").date()
        except ValueError:
            parsed = None
    return parsed or default or timezone.localdate()


def _safe_next(request, fallback):
    target = request.POST.get("next") or request.GET.get("next")
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
        return target
    return fallback


def tell_dentists(appointment, title, request, *others):
    """Tell the dentist of the appointment (and the dentist it was taken from) what changed."""
    dentists = {d for d in (appointment.dentist, *others) if d is not None and d.user_id}
    when = timezone.localtime(appointment.scheduled_at).strftime("%d/%m/%Y %I:%M %p")
    notify_users([d.user for d in dentists], title, gettext_lazy("%(patient)s — %(when)s"),
                 appointment.get_absolute_url(), exclude=request.user,
                 params={"patient": appointment.patient.full_name, "when": when})


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
        .select_related("patient", "room", "dentist")
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
        Prefetch("shifts", queryset=RoomShift.objects.filter(date=day).select_related("dentist", "supervisor"),
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
            "late_threshold": ClinicSettings.get().late_threshold_minutes,
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
        duration_minutes=ClinicSettings.get().default_appointment_minutes,
        dentist=form.cleaned_data.get("dentist") or patient.assigned_dentist,
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
    if action == "cancel":
        tell_dentists(appointment, gettext_lazy("Appointment cancelled"), request)
    elif action == "no_show":
        tell_dentists(appointment, gettext_lazy("Your patient did not come"), request)
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
        qs = Appointment.objects.select_related("patient", "room", "dentist")
        if not has_role(self.request.user, *PATIENT_VIEWERS):
            raise PermissionDenied
        if is_only_dentist(self.request.user):
            qs = qs.filter(dentist=Dentist.for_user(self.request.user))
        today = timezone.localdate()
        date_from, date_to = today, today + timedelta(days=7)
        if self.filter_form.is_valid():
            data = self.filter_form.cleaned_data
            date_from = data.get("date_from") or date_from
            date_to = data.get("date_to") or date_to
            if data.get("dentist"):
                qs = qs.filter(dentist=data["dentist"])
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
    at = parse_datetime(request.GET.get("at") or "")
    if at is not None:
        initial["scheduled_at"] = timezone.make_aware(at) if timezone.is_naive(at) else at
    for name in ("room", "dentist"):
        if request.GET.get(name, "").isdigit():
            initial[name] = int(request.GET[name])
    if request.GET.get("duration", "").isdigit():  # booking from a dentist's patient list
        initial["duration_minutes"] = int(request.GET["duration"])
    if request.GET.get("purpose"):
        initial["purpose"] = request.GET["purpose"][:200]
    form = AppointmentForm(request.POST or None, branch=branch, patient=patient, initial=initial)
    if request.method == "POST" and form.is_valid():
        appointment = form.save(commit=False)
        appointment.branch = branch
        appointment.created_by = request.user
        appointment.save()
        link_booking(request, appointment)
        tell_dentists(appointment, gettext_lazy("New appointment with you"), request)
        messages.success(request, _("Appointment booked. Send the confirmation on WhatsApp."))
        return redirect(appointment)
    return render(
        request, "scheduling/appointment_form.html",
        {"form": form, "title": _("Book appointment"), "cancel_url": reverse("scheduling:day_planner")},
    )


@role_required(*FRONT_DESK)
def appointment_update(request, pk):
    appointment = get_object_or_404(Appointment, pk=pk)
    before = Appointment.objects.select_related("dentist").get(pk=pk)
    form = AppointmentForm(request.POST or None, instance=appointment, branch=appointment.branch)
    if request.method == "POST" and form.is_valid():
        form.save()
        if {"scheduled_at", "dentist", "room", "duration_minutes"} & set(form.changed_data):
            tell_dentists(appointment, gettext_lazy("Your appointment was changed"), request, before.dentist)
        messages.success(request, _("Appointment updated."))
        return redirect(appointment)
    return render(
        request, "scheduling/appointment_form.html",
        {"form": form, "title": _("Edit appointment"), "cancel_url": appointment.get_absolute_url()},
    )


def appointment_detail(request, pk):
    appointment = get_object_or_404(Appointment.objects.select_related("patient", "room", "dentist"), pk=pk)
    get_visible_patient_or_403(request.user, appointment.patient_id)
    return render(
        request,
        "scheduling/appointment_detail.html",
        {
            "appointment": appointment,
            "times_form": VisitTimesForm(instance=appointment) if has_role(request.user, *FRONT_DESK) else None,
            "times_need_approval": needs_approval(request.user),
            "pending_changes": pending_for(appointment),
            "steps": appointment.treatment_steps.select_related("step_type", "operator"),
            "lab_requests": appointment.lab_requests.select_related("work_type"),
            "rooms": Room.objects.filter(branch=appointment.branch, is_active=True),
            "sent_messages": appointment.messages.select_related("sent_by"),
        },
    )


@role_required(*FRONT_DESK)
def appointment_reschedule(request, pk):
    """Move an appointment: new day and time (and dentist or room if needed), with the reason.
    The dentist is told, and the patient gets the new time on WhatsApp."""
    appointment = get_object_or_404(Appointment.objects.select_related("patient", "dentist"), pk=pk)
    before = Appointment.objects.select_related("dentist").get(pk=pk)
    form = RescheduleForm(request.POST or None, instance=appointment, branch=appointment.branch)
    if request.method == "POST" and form.is_valid():
        moved = form.save(commit=False)
        moved.rescheduled_from, moved.rescheduled_at = before.scheduled_at, timezone.now()
        moved.reschedule_reason = form.cleaned_data["reason"]
        if moved.status in (Appointment.Status.NO_SHOW, Appointment.Status.CANCELLED):
            moved.status, moved.cancel_reason = Appointment.Status.SCHEDULED, ""
        moved.save()
        tell_dentists(moved, gettext_lazy("Your appointment was moved"), request, before.dentist)
        messages.success(request, _("Appointment moved. Send the new time on WhatsApp."))
        return redirect(moved)
    return render(request, "scheduling/appointment_form.html", {
        "form": form, "cancel_url": appointment.get_absolute_url(),
        "title": _("Move the appointment of %(name)s (now %(when)s)") % {
            "name": appointment.patient.full_name,
            "when": timezone.localtime(appointment.scheduled_at).strftime("%d/%m/%Y %I:%M %p")},
    })


@role_required(*FRONT_DESK)
@require_POST
def appointment_times(request, pk):
    """Correct the arrival / room / leaving times. From the reception it waits for the head of CIA."""
    appointment = get_object_or_404(Appointment, pk=pk)
    original = Appointment.objects.get(pk=pk)
    form = VisitTimesForm(request.POST, instance=appointment)
    if not form.is_valid():
        for error in form.non_field_errors() or [e for errors in form.errors.values() for e in errors]:
            messages.error(request, error)
        return redirect(appointment)
    values = {name: form.cleaned_data[name] for name in form.changed_data if name in form._meta.fields}
    if not values:
        messages.info(request, _("Nothing was changed."))
    elif needs_approval(request.user):
        request_change(ChangeRequest.Kind.VISIT_TIMES, original, values, request.user, form.cleaned_data["reason"])
        messages.warning(request, _("Sent to the head of CIA for approval. The times change once it is approved."))
    else:
        appointment.set_status_from_times()
        appointment.save()
        messages.success(request, _("Times corrected."))
    return redirect(appointment)


# ------------------------------------------------------------ day planner
@role_required(*FRONT_DESK)
def day_planner(request):
    """The day's appointments room by room in 15-minute steps; click a free place to book it."""
    day = _parse_day(request.GET.get("day"))
    branch = branch_for_user(request.user)
    context = day_grid(branch, day)
    if request.GET.get("fragment"):
        return render(request, "scheduling/_day_grid.html", {**context, "in_form": True})
    start = week_start(day)
    context.update({
        "prev_day": day - timedelta(days=1), "next_day": day + timedelta(days=1),
        "is_today": day == timezone.localdate(),
        "week": week_outline(branch, [start + timedelta(days=i) for i in range(7)]),
        "prev_week": start - timedelta(days=7), "next_week": start + timedelta(days=7),
    })
    return render(request, "scheduling/day_planner.html", context)


# ------------------------------------------------------------ room schedule
def room_schedule(request):
    if not has_role(request.user, *PATIENT_VIEWERS):
        raise PermissionDenied
    start = week_start(_parse_day(request.GET.get("week")))
    days = [start + timedelta(days=i) for i in range(7)]
    branch = branch_for_user(request.user)
    rooms = list(Room.objects.filter(branch=branch, is_active=True))
    shifts = RoomShift.objects.filter(room__in=rooms, date__range=(days[0], days[-1])).select_related(
        "dentist", "supervisor", "room"
    )
    opened = set(shifts.values_list("room_id", flat=True))
    extra_rooms = [room for room in rooms if room.is_extra and room.pk not in opened]
    rooms = [room for room in rooms if not room.is_extra or room.pk in opened]  # extra rooms only when opened
    # CIA dentists see only their own shifts.
    only_mine = request.GET.get("mine") == "1" or is_only_dentist(request.user)
    if only_mine:
        shifts = shifts.filter(dentist=Dentist.for_user(request.user))
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
            "extra_rooms": extra_rooms,
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
        options = ClinicSettings.get()
        initial.setdefault("start_time", options.day_start)
        initial.setdefault("end_time", options.day_end)
        if "date" in initial and initial["date"].weekday() in options.surgery_weekdays:
            initial["day_type"] = RoomShift.DayType.SURGERY
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
                end_time=shift.end_time, dentist=shift.dentist, supervisor=shift.supervisor, day_type=shift.day_type,
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


# ------------------------------------------------------------ WhatsApp
@role_required(*FRONT_DESK)
@require_POST
def whatsapp_send(request, pk, kind):
    """Keep the message on the appointment, then open WhatsApp with it ready to send."""
    appointment = get_object_or_404(Appointment.objects.select_related("patient", "dentist", "branch"), pk=pk)
    if kind not in MessageTemplate.Kind.values:
        raise Http404
    if not whatsapp_number(appointment.patient.preferred_number):
        messages.error(request, _("This patient has no mobile number for WhatsApp."))
        return redirect(appointment)
    return redirect(record(kind, appointment, request.user))


@role_required(*FRONT_DESK)
def whatsapp_list(request):
    """What the reception should send: confirmations of new bookings, reminders, missed appointments."""
    options = ClinicSettings.get()
    today = timezone.localdate()
    day = _parse_day(request.GET.get("day"), today + timedelta(days=options.reminder_days_before))
    start, end = day_bounds(day)

    def with_sent(qs, kind):
        rows = []
        for appointment in qs.select_related("patient", "dentist", "room").prefetch_related("messages"):
            sent = [m for m in appointment.messages.all() if m.kind == kind]
            rows.append((appointment, sent[0] if sent else None))
        return rows

    waiting = Appointment.objects.filter(status__in=Appointment.WAITING_STATUSES)
    new_bookings = waiting.filter(created_at__gte=timezone.now() - timedelta(days=3),
                                  scheduled_at__gte=timezone.now()).order_by("scheduled_at")
    reminders = waiting.filter(scheduled_at__gte=start, scheduled_at__lt=end).order_by("scheduled_at")
    missed = Appointment.objects.filter(status=Appointment.Status.NO_SHOW,
                                        scheduled_at__gte=day_bounds(today - timedelta(days=7))[0]).order_by("-scheduled_at")
    moved = waiting.filter(rescheduled_at__gte=timezone.now() - timedelta(days=3),
                           scheduled_at__gte=timezone.now()).order_by("scheduled_at")
    installments = None
    if has_role(request.user, OWNER, HEAD_CIA, SECRETARY) and area_levels(request.user).get("academy") != "hidden":
        from apps.academy.reminders import reminders_due

        installments = reminders_due()
    return render(request, "scheduling/whatsapp.html", {
        "day": day, "prev_day": day - timedelta(days=1), "next_day": day + timedelta(days=1),
        "new_bookings": with_sent(new_bookings, MessageTemplate.Kind.CONFIRMATION),
        "reminders": with_sent(reminders, MessageTemplate.Kind.REMINDER),
        "missed": with_sent(missed, MessageTemplate.Kind.NO_SHOW),
        "moved": with_sent(moved, MessageTemplate.Kind.RESCHEDULED),
        "installments": installments,
    })
