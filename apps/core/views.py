import mimetypes
import os
import posixpath
from datetime import timedelta
from urllib.parse import quote

from django.conf import settings
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_not_required

from django.contrib import messages
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, SuspiciousFileOperation
from django.core.files.storage import default_storage
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import FileResponse, Http404, HttpResponse, HttpResponseNotModified, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import http_date, url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.academy.models import Enrollment
from apps.clinical.models import LabRequest, TreatmentStep
from apps.dentists.models import Dentist
from apps.clinical.visit_notes import send_notes_alerts
from apps.complaints.alerts import send_answer_alerts, unanswered
from apps.complaints.models import Complaint
from apps.patients.models import CallList, CallListEntry, Lead, Patient
from apps.scheduling.models import Appointment, RoomShift, day_bounds

from . import previews
from .access import area_levels
from .models import (
    AreaAccess, Branch, ClinicSettings, Notification, UserProfile, branch_for_user, switch_places, working_places,
)
from .roles import (
    CLINIC_MANAGERS,
    CLINICAL,
    FRONT_DESK,
    HEAD_CIA,
    LAB_STAFF,
    MANAGEMENT,
    MODERATOR,
    OWNER,
    PATIENT_VIEWERS,
    PURCHASE_ROLES,
    SECRETARY,
    STOCK,
    STOCK_ROLES,
    SUPERVISOR,
    TEAM_HEAD,
    has_role,
)


ALERTS_EVERY_SECONDS = 180


def dashboard(request):
    user = request.user
    today = timezone.localdate()
    start, end = day_bounds(today)
    branch = branch_for_user(user)
    context = {"today": today}
    hour = timezone.localtime().hour
    name = user.get_full_name() or user.username
    if hour < 12:
        context["greeting"], context["greeting_icon"] = _("Good morning, %(name)s") % {"name": name}, "bi-sunrise"
    elif hour < 17:
        context["greeting"], context["greeting_icon"] = _("Good afternoon, %(name)s") % {"name": name}, "bi-sun"
    else:
        context["greeting"], context["greeting_icon"] = _("Good evening, %(name)s") % {"name": name}, "bi-moon-stars"
    if cache.add("dashboard-alerts", True, ALERTS_EVERY_SECONDS):  # at most every few minutes, not on each page
        send_answer_alerts(today)  # complaints a dentist has not answered in time
        send_notes_alerts()  # visits left without notes in the patient's file
    if has_role(user, OWNER):
        from .backup import backup_status

        context["backup"] = backup_status()
    if has_role(user, *PATIENT_VIEWERS):
        counts = dict(Patient.objects.here().values_list("status").annotate(n=Count("id")))
        context["patient_totals"] = {
            "total": sum(counts.values()), "active": counts.get(Patient.Status.ACTIVE, 0),
            "finished": counts.get(Patient.Status.FINISHED, 0), "out": counts.get(Patient.Status.OUT, 0),
            "new_this_month": Patient.objects.here().filter(registered_on__gte=today.replace(day=1)).count(),
        }

    todays = Appointment.objects.filter(scheduled_at__gte=start, scheduled_at__lt=end)
    if branch:
        todays = todays.filter(branch=branch)

    if has_role(user, *FRONT_DESK):
        counts = dict(todays.values_list("status").annotate(n=Count("id")))
        context["appointment_counts"] = {
            "total": sum(counts.values()),
            "waiting": counts.get(Appointment.Status.SCHEDULED, 0) + counts.get(Appointment.Status.CONFIRMED, 0),
            "arrived": counts.get(Appointment.Status.ARRIVED, 0),
            "in_room": counts.get(Appointment.Status.IN_ROOM, 0),
            "completed": counts.get(Appointment.Status.COMPLETED, 0),
            "no_show": counts.get(Appointment.Status.NO_SHOW, 0),
        }
        context["calls_due"] = (
            Lead.objects.filter(status__in=(Lead.Status.NEW, Lead.Status.FOLLOW_UP), branch=branch)
            .order_by("first_call_on", "created_at")[:8]
        )
        from apps.billing.models import Bill, bill_totals

        since = today - timedelta(days=30)
        doctor_bills = list(Bill.objects.filter(branch=branch, source=Bill.Source.DENTIST, billed_on__gte=since)
                            .select_related("patient", "dentist").order_by("-billed_on", "-pk")[:200])
        left = bill_totals(doctor_bills)
        context["doctor_bills"] = [{"bill": b, "left": left[b.pk]["left"]} for b in doctor_bills
                                   if left[b.pk]["left"] > 0][:8]
        context["doctor_bills_from"] = since
        labs = LabRequest.objects.filter(patient__branch=branch)
        context["lab_to_send"] = labs.filter(status=LabRequest.Status.APPROVED).count()
        context["lab_overdue"] = labs.filter(status=LabRequest.Status.SENT, due_date__lt=today).count()
        context["lab_received"] = labs.filter(status=LabRequest.Status.RECEIVED).count()
        context["open_complaints"] = Complaint.objects.filter(status__in=Complaint.OPEN_STATUSES, branch=branch).count()
        options = ClinicSettings.get()
        remind_day = today + timedelta(days=options.reminder_days_before)
        remind_start, remind_end = day_bounds(remind_day)
        context["whatsapp_to_send"] = (
            Appointment.objects.filter(status__in=Appointment.WAITING_STATUSES, scheduled_at__gte=remind_start,
                                       scheduled_at__lt=remind_end, branch=branch)
            .exclude(messages__kind="reminder").count()
            + Appointment.objects.filter(status__in=Appointment.WAITING_STATUSES, scheduled_at__gte=timezone.now(),
                                         created_at__gte=timezone.now() - timedelta(days=3), branch=branch)
            .exclude(messages__kind="confirmation").count()
        )
        from apps.scheduling.models import WhatsAppRequest

        context["whatsapp_asked"] = WhatsAppRequest.objects.filter(branch=branch, sent_at__isnull=True).count()
        context["whatsapp_to_send"] += context["whatsapp_asked"]
        context["coming_next"] = (
            todays.filter(status__in=Appointment.WAITING_STATUSES, scheduled_at__gte=timezone.now() - timedelta(hours=1))
            .select_related("patient", "dentist", "room").order_by("scheduled_at")[:6]
        )
        context["here_now"] = todays.filter(status=Appointment.Status.ARRIVED).select_related("patient", "dentist")\
            .order_by("arrived_at")[:6]
        context["call_lists"] = (
            CallList.objects.filter(branch=branch, entries__outcome=CallListEntry.Outcome.PENDING)
            .annotate(pending=Count("entries", filter=Q(entries__outcome=CallListEntry.Outcome.PENDING)))
            .order_by("-created_at")[:6]
        )

    if has_role(user, SECRETARY, OWNER, HEAD_CIA) and area_levels(user).get("academy") != AreaAccess.Level.HIDDEN:
        overdue = []
        for enrollment in Enrollment.objects.filter(status=Enrollment.Status.ACTIVE).select_related(
            "candidate", "course"
        ):
            amount = enrollment.overdue_amount(today)
            if amount > 0:
                overdue.append((enrollment, amount))
        context["overdue_installments"] = sorted(overdue, key=lambda row: -row[1])[:8]

    if has_role(user, *MANAGEMENT):
        context["lab_pending_review"] = LabRequest.objects.filter(status=LabRequest.Status.PENDING_REVIEW,
                                                                  patient__branch=branch).count()
        context["steps_to_check"] = TreatmentStep.objects.filter(verified_at__isnull=True,
                                                                 patient__branch=branch).count()
        context["overdue_complaints"] = (
            Complaint.objects.filter(status__in=Complaint.OPEN_STATUSES, follow_up_due__lt=today, branch=branch)
            .select_related("patient")
            .order_by("follow_up_due")[:8]
        )

    dentist = Dentist.for_user(user)
    if dentist is not None:
        context["dentist"] = dentist
        week = [today + timedelta(days=i) for i in range(7)]
        days = {day: {"day": day, "shifts": [], "appointments": []} for day in week}
        my_places = set(working_places(user).values_list("pk", flat=True))
        for shift in RoomShift.objects.filter(dentist=dentist, date__range=(week[0], week[-1])).select_related("room"):
            days[shift.date]["shifts"].append(shift)
        for appointment in (Appointment.objects.filter(dentist=dentist, scheduled_at__gte=start,
                                                       scheduled_at__lt=day_bounds(week[-1])[1])
                            .exclude(status=Appointment.Status.CANCELLED).select_related("patient", "room", "branch")
                            .order_by("scheduled_at")):
            # A visit at another place: shown without the patient's name; it opens only where the person works.
            appointment.other_place = branch is not None and appointment.branch_id != branch.pk
            appointment.can_open = not appointment.other_place or appointment.branch_id in my_places
            days[timezone.localtime(appointment.scheduled_at).date()]["appointments"].append(appointment)
        context["my_week"] = list(days.values())
        context["my_complaints"] = unanswered(dentist)
        context["my_updates"] = user.notifications.filter(url__startswith="/schedule/appointments/")[:6]
        context["my_patient_count"] = Patient.objects.here().filter(
            assigned_dentist=dentist, status=Patient.Status.ACTIVE
        ).count()
        context["my_open_labs"] = LabRequest.objects.filter(
            dentist=dentist, status__in=LabRequest.OPEN_STATUSES
        ).count()
    pending = Appointment.objects.filter(status=Appointment.Status.PENDING, scheduled_at__gte=start).select_related(
        "patient", "dentist").order_by("scheduled_at")
    if has_role(user, OWNER, HEAD_CIA, TEAM_HEAD, SUPERVISOR, MODERATOR):
        context["bookings_to_approve"] = list(pending.filter(branch=branch)[:10])
    elif dentist is not None:
        context["bookings_to_approve"] = list(pending.filter(dentist=dentist, branch=branch)[:10])
    context["show_supervisor_cards"] = has_role(user, *MANAGEMENT)
    if has_role(user, *STOCK_ROLES):
        from apps.stock.views import expiring_soon, low_stock

        context["low_stock"] = low_stock().select_related("category")[:12]
        context["expiring"] = expiring_soon()[:8]
    if has_role(user, *CLINIC_MANAGERS):
        context["clinic_cards"] = clinic_cards(user, today)
    if has_role(user, *LAB_STAFF):
        at_lab = branch is not None and branch.kind == Branch.Kind.LAB
        if at_lab or not has_role(user, OWNER, *PATIENT_VIEWERS, STOCK, MODERATOR):
            from apps.lab.views import lab_home_context

            context.update(lab_home_context(user))  # the lab's own home page
        else:
            from apps.lab.views import my_worker, open_cases

            me = my_worker(user)  # e.g. a CIA doctor who designs: only the cases with him
            if me is not None:
                context["lab_with_me"] = list(open_cases().filter(worker=me).order_by("due_date", "pk")[:8])
    return render(request, "core/dashboard.html", context)


def clinic_cards(user, today):
    """This month at each place that pays its doctors by rules: visits, money in, the doctors' shares."""
    from apps.clinics.models import FeeRule
    from apps.clinics.shares import summary

    cards = []
    with_rules = set(FeeRule.objects.values_list("branch_id", flat=True))
    for place in working_places(user):
        if place.pk not in with_rules:
            continue
        rows, totals = summary(place, today.replace(day=1), today)
        cards.append({"place": place, "rows": rows, **{k: totals.get(k, 0) for k in
                                                        ("collected", "share", "owed", "visit_count", "chair_minutes")}})
    return cards


# ------------------------------------------------------------ the place of this device, the login page
DEVICE_PLACE_COOKIE = "device_place"


def login_places():
    """The places offered on the login page (CIA, CIC, El Khadem, the lab): the reception chooses hers."""
    places = Branch.objects.filter(is_active=True).order_by("sort_order", "pk")
    return sorted(places, key=lambda place: place.kind == Branch.Kind.LAB)  # the lab last


def login_place(request):
    """The place whose look the login page takes: the one chosen on the page (``?place=EK``), else the place this
    device was last used for (a cookie kept for a year)."""
    code = (request.POST.get("place") or request.GET.get("place") or request.COOKIES.get(DEVICE_PLACE_COOKIE)
            or "").strip()
    if not code or len(code) > 10:
        return None
    return Branch.objects.filter(is_active=True).filter(Q(code__iexact=code) | Q(file_prefix__iexact=code)).first()


def remember_device_place(response, place):
    if place is not None:
        response.set_cookie(DEVICE_PLACE_COOKIE, place.code, max_age=365 * 24 * 3600, samesite="Lax")
    return response


class PlaceLoginView(auth_views.LoginView):
    """One login page for every place: the person taps her place (CIA, CIC, El Khadem or the lab), the page takes its
    look, and after logging in that place is open. The device remembers the last place chosen."""

    def get_form_class(self):
        from .forms import LoginForm

        return LoginForm

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["login_place"] = login_place(self.request)
        context["login_places"] = login_places()
        return context

    def get(self, request, *args, **kwargs):
        response = super().get(request, *args, **kwargs)
        if request.GET.get("place"):
            remember_device_place(response, login_place(request))
        return response

    def form_valid(self, form):
        response = super().form_valid(form)
        place, user = login_place(self.request), form.get_user()
        mine = switch_places(user)
        if place is not None and place in mine:
            self.request.session["place"] = place.pk
        elif place is not None and mine:
            own = branch_for_user(user)
            opened = own if own in mine else mine[0]
            self.request.session["place"] = opened.pk
            messages.info(self.request, _("You do not work at %(chosen)s: %(place)s is open.")
                          % {"chosen": place.name, "place": opened.name})
            place = None  # this device keeps the place chosen on it
        elif len(mine) == 1:
            place = mine[0]
        return remember_device_place(response, place)


@login_not_required
def place_logo(request, code):
    """A place's logo, shown on the login page too: it opens without logging in (it is not patient data)."""
    place = get_object_or_404(Branch, code=code)
    if not place.logo:
        raise Http404
    return send_file(request, place.logo.name)


@login_not_required
@require_POST
def switch_language(request):
    """Save the chosen interface language on the user's profile (and in a cookie
    for the login page), then go back to the page the user was on."""
    language = request.POST.get("language")
    target = request.POST.get("next") or "/"
    if not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
        target = "/"
    response = redirect(target)
    if language in dict(settings.LANGUAGES):
        if request.user.is_authenticated:
            profile, _created = UserProfile.objects.get_or_create(user=request.user)
            profile.language = language
            profile.save(update_fields=["language"])
        response.set_cookie(settings.LANGUAGE_COOKIE_NAME, language, max_age=365 * 24 * 3600, samesite="Lax")
    return response


@require_POST
def switch_place(request):
    """The switch in the top bar: work at another place (CIA, CIC...) from now on, then go on."""
    place = next((p for p in switch_places(request.user) if p.code == request.POST.get("place", "")), None)
    if place is None:
        raise PermissionDenied
    request.session["place"] = place.pk
    messages.info(request, _("You are working at %(place)s now.") % {"place": place.name})
    target = request.POST.get("next") or "/"
    if not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
        target = "/"
    return redirect(target)


@require_POST
def toggle_hints(request):
    """User menu: switch the page hints off, or on again (hints closed one by one come back too)."""
    profile, _created = UserProfile.objects.get_or_create(user=request.user)
    profile.show_hints = not profile.show_hints
    profile.save(update_fields=["show_hints"])
    if profile.show_hints:
        request.session["hints_reset"] = True
        messages.success(request, _("Hints are on: a short tip shows at the top of the main pages."))
    else:
        messages.info(request, _("Hints are off. Switch them on again from the menu under your name."))
    target = request.POST.get("next") or "/"
    if not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
        target = "/"
    return redirect(target)


def notification_list(request):
    notifications = request.user.notifications.all()
    page = Paginator(notifications, 30).get_page(request.GET.get("page"))
    return render(request, "core/notifications.html", {"page_obj": page})


def notification_open(request, pk):
    notification = get_object_or_404(Notification, pk=pk, recipient=request.user)
    if not notification.read_at:
        notification.read_at = timezone.now()
        notification.save(update_fields=["read_at"])
    if notification.url and url_has_allowed_host_and_scheme(notification.url, allowed_hosts={request.get_host()}):
        return redirect(notification.url)
    return redirect("core:notifications")


def notification_poll(request):
    """New notifications since the last one the page knows (for the pop-up and the sound)."""
    since = int(request.GET["since"]) if request.GET.get("since", "").isdigit() else 0
    unread = request.user.notifications.filter(read_at__isnull=True)
    fresh = unread.filter(pk__gt=since).order_by("pk")[:5]
    return JsonResponse({
        "unread": unread.count(),
        "last": request.user.notifications.order_by("-pk").values_list("pk", flat=True).first() or 0,
        "new": [{"id": n.pk, "title": n.title, "message": n.message, "level": n.level,
                 "url": reverse("core:notification_open", args=[n.pk])} for n in fresh],
    })


@require_POST
def notification_mark_all_read(request):
    request.user.notifications.filter(read_at__isnull=True).update(read_at=timezone.now())
    messages.success(request, _("All notifications marked as read."))
    return redirect("core:notifications")


# Which roles may download files stored under each media folder.
MEDIA_FOLDER_ROLES = {
    "patients": PATIENT_VIEWERS,
    "Patient photos": CLINICAL,  # clinical photos, in readable folders (apps.charting.photo_files)
    "candidates": (OWNER, HEAD_CIA, SUPERVISOR, SECRETARY),
    "purchases": PURCHASE_ROLES,
    "problems": (OWNER, HEAD_CIA),
}


def check_media_access(user, path):
    """Raise PermissionDenied unless ``user`` may open the uploaded file at ``path``."""
    folder = path.split("/", 1)[0]
    allowed = MEDIA_FOLDER_ROLES.get(folder)
    if allowed is None or not has_role(user, *allowed):
        raise PermissionDenied
    if folder in ("patients", "Patient photos") and not has_role(user, *FRONT_DESK):
        # Only files of patients this user may see ("patients/<id>/…" or "Patient photos/<file number> <name>/…").
        part = path.split("/")[1] if path.count("/") >= 2 else ""
        from apps.patients.access import visible_patients

        patients = visible_patients(user)
        if folder == "patients":
            patients = patients.filter(pk=part if part.isdigit() else 0)
        else:
            patients = patients.filter(file_number=part.split(" ", 1)[0])
        if not patients.exists():
            raise PermissionDenied


def protected_media(request, path):
    """Serve uploaded files only to logged-in staff allowed to see them. A preview (a small copy of a
    picture, see ``apps.core.previews``) is allowed to whoever may open the picture, and made when missing."""
    if posixpath.normpath(path) != path or path.startswith(("/", "..")) or "\\" in path:
        raise Http404  # "a/../b" would be checked as "a" and then open "b"
    preview = previews.split(path)
    check_media_access(request.user, preview[1] if preview else path)
    try:
        default_storage.path(path)
    except SuspiciousFileOperation:
        raise Http404
    if preview:
        size, original = preview
        if not default_storage.exists(original):
            raise Http404
        path = previews.make_preview(original, size) or original  # a picture that cannot be read: the original
    elif not default_storage.exists(path):
        raise Http404
    return send_file(request, path)


def send_file(request, path):
    """Send a stored file. The browser keeps it and asks again only whether it changed (no download when it
    did not). Behind nginx (MEDIA_SENDFILE=nginx) the file itself is sent by nginx, not by Python."""
    full_path = default_storage.path(path)
    info = os.stat(full_path)
    etag = f'"{info.st_mtime_ns:x}-{info.st_size:x}"'
    headers = {"ETag": etag, "Last-Modified": http_date(info.st_mtime), "Cache-Control": "private, no-cache"}
    if etag in request.headers.get("If-None-Match", ""):
        response = HttpResponseNotModified()
    else:
        content_type = mimetypes.guess_type(full_path)[0] or "application/octet-stream"
        if settings.MEDIA_SENDFILE == "nginx":
            response = HttpResponse(content_type=content_type)
            response["X-Accel-Redirect"] = settings.MEDIA_SENDFILE_PREFIX + quote(path)
        elif settings.MEDIA_SENDFILE == "x-sendfile":
            response = HttpResponse(content_type=content_type)
            response["X-Sendfile"] = full_path
        else:
            response = FileResponse(open(full_path, "rb"), content_type=content_type)
    for key, value in headers.items():
        response[key] = value
    return response