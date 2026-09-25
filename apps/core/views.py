import mimetypes

from django.conf import settings
from django.contrib.auth.decorators import login_not_required

from django.contrib import messages
from django.core.exceptions import PermissionDenied, SuspiciousFileOperation
from django.core.files.storage import default_storage
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.academy.models import Enrollment
from apps.clinical.models import LabRequest, TreatmentStep
from apps.dentists.models import Dentist
from apps.complaints.models import Complaint
from apps.patients.models import CallList, CallListEntry, Lead, Patient
from apps.scheduling.models import Appointment, RoomShift, day_bounds

from .models import Notification, UserProfile, branch_for_user
from .roles import (
    FRONT_DESK,
    HEAD_CIA,
    MANAGEMENT,
    OWNER,
    PATIENT_VIEWERS,
    PURCHASE_ROLES,
    SECRETARY,
    STOCK_ROLES,
    SUPERVISOR,
    has_role,
)


def dashboard(request):
    user = request.user
    today = timezone.localdate()
    start, end = day_bounds(today)
    branch = branch_for_user(user)
    context = {"today": today}

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
            Lead.objects.filter(status__in=Lead.OPEN_STATUSES)
            .filter(Q(next_call_at__lt=end) | Q(next_call_at__isnull=True, status=Lead.Status.NEW))
            .order_by("next_call_at", "created_at")[:8]
        )
        context["lab_to_send"] = LabRequest.objects.filter(status=LabRequest.Status.APPROVED).count()
        context["lab_overdue"] = LabRequest.objects.filter(
            status=LabRequest.Status.SENT, due_date__lt=today
        ).count()
        context["lab_received"] = LabRequest.objects.filter(status=LabRequest.Status.RECEIVED).count()
        context["open_complaints"] = Complaint.objects.filter(status__in=Complaint.OPEN_STATUSES).count()
        context["call_lists"] = (
            CallList.objects.filter(entries__outcome=CallListEntry.Outcome.PENDING)
            .annotate(pending=Count("entries", filter=Q(entries__outcome=CallListEntry.Outcome.PENDING)))
            .order_by("-created_at")[:6]
        )

    if has_role(user, SECRETARY, OWNER, HEAD_CIA):
        overdue = []
        for enrollment in Enrollment.objects.filter(status=Enrollment.Status.ACTIVE).select_related(
            "candidate", "course"
        ):
            amount = enrollment.overdue_amount(today)
            if amount > 0:
                overdue.append((enrollment, amount))
        context["overdue_installments"] = sorted(overdue, key=lambda row: -row[1])[:8]

    if has_role(user, *MANAGEMENT):
        context["lab_pending_review"] = LabRequest.objects.filter(status=LabRequest.Status.PENDING_REVIEW).count()
        context["steps_to_check"] = TreatmentStep.objects.filter(verified_at__isnull=True).count()
        context["overdue_complaints"] = (
            Complaint.objects.filter(status__in=Complaint.OPEN_STATUSES, follow_up_due__lt=today)
            .select_related("patient")
            .order_by("follow_up_due")[:8]
        )

    dentist = Dentist.for_user(user)
    if dentist is not None:
        context["dentist"] = dentist
        context["my_shifts"] = RoomShift.objects.filter(dentist=dentist, date=today).select_related("room", "supervisor")
        context["my_appointments"] = (
            Appointment.objects.filter(dentist=dentist, scheduled_at__gte=start, scheduled_at__lt=end)
            .select_related("patient", "room")
            .order_by("scheduled_at")
        )
        context["my_patient_count"] = Patient.objects.filter(
            assigned_dentist=dentist, status=Patient.Status.ACTIVE
        ).count()
        context["my_open_labs"] = LabRequest.objects.filter(
            dentist=dentist, status__in=LabRequest.OPEN_STATUSES
        ).count()
    context["show_supervisor_cards"] = has_role(user, *MANAGEMENT)
    if has_role(user, *STOCK_ROLES):
        from apps.stock.views import expiring_soon, low_stock

        context["low_stock"] = low_stock().select_related("category")[:12]
        context["expiring"] = expiring_soon()[:8]
    return render(request, "core/dashboard.html", context)


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


@require_POST
def notification_mark_all_read(request):
    request.user.notifications.filter(read_at__isnull=True).update(read_at=timezone.now())
    messages.success(request, _("All notifications marked as read."))
    return redirect("core:notifications")


# Which roles may download files stored under each media folder.
MEDIA_FOLDER_ROLES = {
    "patients": PATIENT_VIEWERS,
    "candidates": (OWNER, HEAD_CIA, SUPERVISOR, SECRETARY),
    "purchases": PURCHASE_ROLES,
}


def protected_media(request, path):
    """Serve uploaded files only to logged-in staff allowed to see them."""
    folder = path.split("/", 1)[0]
    allowed = MEDIA_FOLDER_ROLES.get(folder)
    if allowed is None or not has_role(request.user, *allowed):
        raise PermissionDenied
    if folder == "patients" and not has_role(request.user, *FRONT_DESK):
        # Only files of patients this user may see.
        patient_id = path.split("/")[1] if path.count("/") >= 2 else ""
        from apps.patients.access import visible_patients

        if not visible_patients(request.user).filter(pk=patient_id if patient_id.isdigit() else 0).exists():
            raise PermissionDenied
    try:
        full_path = default_storage.path(path)
    except SuspiciousFileOperation:
        raise Http404
    if not default_storage.exists(path):
        raise Http404
    content_type, _encoding = mimetypes.guess_type(full_path)
    return FileResponse(open(full_path, "rb"), content_type=content_type or "application/octet-stream")
