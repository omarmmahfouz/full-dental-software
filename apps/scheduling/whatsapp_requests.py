"""The dentists' tablets have no WhatsApp: a dentist who wants a prescription, the instructions or a bill sent to a
patient asks the reception. The request waits at the top of the reception's WhatsApp list (and on its home page)
until a secretary sends it and ticks it."""

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from apps.core.mixins import role_required
from apps.core.models import Notification, staff_at
from apps.core.notify import notify_users
from apps.core.roles import FRONT_DESK, PATIENT_VIEWERS, SECRETARY, has_role
from apps.patients.access import get_visible_patient_or_403

from .models import WhatsAppRequest


def pending_requests(branch):
    return WhatsAppRequest.objects.filter(branch=branch, sent_at__isnull=True).select_related(
        "patient", "requested_by").order_by("requested_at")


@require_POST
def whatsapp_ask(request):
    if not has_role(request.user, *PATIENT_VIEWERS):
        raise PermissionDenied
    patient = get_visible_patient_or_403(request.user, request.POST.get("patient") or 0)
    path = (request.POST.get("path") or "").strip()
    if not path.startswith("/") or path.startswith("//"):  # a page of this system only
        path = patient.get_absolute_url()
    kind = request.POST.get("kind") if request.POST.get("kind") in WhatsAppRequest.Kind.values else "other"
    asked, created = WhatsAppRequest.objects.get_or_create(
        patient=patient, path=path[:300], sent_at__isnull=True,
        defaults={"branch": patient.branch, "kind": kind, "requested_by": request.user,
                  "note": (request.POST.get("note") or "").strip()[:200]})
    if created:
        notify_users(staff_at(patient.branch, SECRETARY),
                     gettext_lazy("Send on WhatsApp: %(what)s"), gettext_lazy("%(patient)s — asked by %(who)s"),
                     "/schedule/whatsapp/#asked", Notification.Level.INFO, exclude=request.user,
                     params={"what": asked.get_kind_display(), "patient": patient.full_name,
                             "who": request.user.get_full_name() or request.user.get_username()})
        messages.success(request, _("Sent to the reception: they will send it to the patient on WhatsApp."))
    else:
        messages.info(request, _("The reception was already asked to send this; it is waiting in their list."))
    return redirect(path)


@role_required(*FRONT_DESK)
@require_POST
def whatsapp_request_done(request):
    asked = get_object_or_404(WhatsAppRequest, pk=request.POST.get("request") if str(
        request.POST.get("request", "")).isdigit() else 0)
    get_visible_patient_or_403(request.user, asked.patient_id)
    if asked.sent_at is None:
        asked.sent_at, asked.sent_by = timezone.now(), request.user
        asked.save(update_fields=["sent_at", "sent_by"])
        if asked.requested_by_id and asked.requested_by.is_active and asked.requested_by != request.user:
            notify_users([asked.requested_by], gettext_lazy("Sent on WhatsApp: %(what)s"),
                         gettext_lazy("%(patient)s"), asked.patient.get_absolute_url(), Notification.Level.SUCCESS,
                         params={"what": asked.get_kind_display(), "patient": asked.patient.full_name})
    messages.success(request, _("Ticked as sent."))
    return redirect(request.POST.get("next") if str(request.POST.get("next", "")).startswith("/schedule/")
                    else "/schedule/whatsapp/#asked")
