import mimetypes

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
from apps.complaints.models import Complaint
from apps.patients.models import Lead, Patient
from apps.scheduling.models import Appointment, RoomShift, day_bounds

from .models import Notification, branch_for_user
from .roles import FRONT_DESK, INTERN, MANAGEMENT, OWNER, SECRETARY, SUPERVISOR, has_role


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

    if has_role(user, SECRETARY, OWNER):
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

    if has_role(user, INTERN):
        context["my_shifts"] = RoomShift.objects.filter(intern=user, date=today).select_related("room")
        context["my_appointments"] = (
            Appointment.objects.filter(intern=user, scheduled_at__gte=start, scheduled_at__lt=end)
            .select_related("patient", "room")
            .order_by("scheduled_at")
        )
        context["my_patient_count"] = Patient.objects.filter(
            assigned_intern=user, status=Patient.Status.ACTIVE
        ).count()
        context["my_open_labs"] = LabRequest.objects.filter(
            requested_by=user, status__in=LabRequest.OPEN_STATUSES
        ).count()
    context["show_supervisor_cards"] = has_role(user, SUPERVISOR, OWNER)
    return render(request, "core/dashboard.html", context)


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
    "patients": FRONT_DESK + (INTERN,),
    "candidates": (OWNER, SUPERVISOR, SECRETARY),
    "purchases": (OWNER, SECRETARY),
}


def protected_media(request, path):
    """Serve uploaded files only to logged-in staff allowed to see them."""
    folder = path.split("/", 1)[0]
    allowed = MEDIA_FOLDER_ROLES.get(folder)
    if allowed is None or not has_role(request.user, *allowed):
        raise PermissionDenied
    if folder == "patients" and not has_role(request.user, *FRONT_DESK):
        # Interns may only open documents of their own patients.
        patient_id = path.split("/")[1] if path.count("/") >= 2 else ""
        if not Patient.objects.filter(pk=patient_id if patient_id.isdigit() else 0, assigned_intern=request.user).exists():
            raise PermissionDenied
    try:
        full_path = default_storage.path(path)
    except SuspiciousFileOperation:
        raise Http404
    if not default_storage.exists(path):
        raise Http404
    content_type, _encoding = mimetypes.guess_type(full_path)
    return FileResponse(open(full_path, "rb"), content_type=content_type or "application/octet-stream")
