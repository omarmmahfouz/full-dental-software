"""Lab request workflow: every status change goes through ``perform_lab_action``
so permissions, timestamps, history and notifications stay consistent."""

from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import Notification
from apps.core.notify import notify_roles, notify_users
from apps.core.roles import (
    DENTISTS,
    FRONT_DESK,
    HEAD_CIA,
    MANAGEMENT,
    OWNER,
    SECRETARY,
    SUPERVISOR,
    has_role,
    is_only_dentist,
)

from .models import LabRequest, LabRequestEvent

S = LabRequest.Status
A = LabRequestEvent.Action

# action -> (allowed "from" statuses, "to" status, roles allowed, needs work check, needs notes)
TRANSITIONS = {
    "submit": ((S.DRAFT,), S.PENDING_REVIEW, FRONT_DESK + DENTISTS, False, False),
    "approve": ((S.PENDING_REVIEW,), S.APPROVED, MANAGEMENT, False, False),
    "return": ((S.PENDING_REVIEW, S.APPROVED), S.DRAFT, MANAGEMENT, False, True),
    "collect": ((S.APPROVED,), S.COLLECTED, FRONT_DESK, False, False),
    "send": ((S.APPROVED, S.COLLECTED), S.SENT, FRONT_DESK, True, False),
    "receive": ((S.SENT,), S.RECEIVED, FRONT_DESK, True, False),
    "remake": ((S.RECEIVED,), S.SENT, FRONT_DESK + DENTISTS, False, True),
    "deliver": ((S.RECEIVED,), S.DELIVERED, FRONT_DESK + DENTISTS, False, False),
    "cancel": ((S.DRAFT, S.PENDING_REVIEW, S.APPROVED, S.COLLECTED), S.CANCELLED, MANAGEMENT + DENTISTS, False, True),
}

EVENT_FOR_ACTION = {
    "submit": A.SUBMITTED, "approve": A.APPROVED, "return": A.RETURNED, "collect": A.COLLECTED, "send": A.SENT,
    "receive": A.RECEIVED, "remake": A.REMAKE, "deliver": A.DELIVERED, "cancel": A.CANCELLED,
}

ACTION_LABELS = {
    "submit": _("Send for review"),
    "approve": _("Approve (reviewed)"),
    "return": _("Return to doctor for changes"),
    "collect": _("Taken from the dentist"),
    "send": _("Mark as sent to lab"),
    "receive": _("Mark as received from lab"),
    "remake": _("Return to lab for remake"),
    "deliver": _("Delivered / fitted to patient"),
    "cancel": _("Cancel request"),
}


def available_actions(lab_request, user):
    """Actions the user may run now, in display order."""
    actions = []
    for action, (sources, _target, roles, _check, _notes) in TRANSITIONS.items():
        if lab_request.status in sources and _may(user, lab_request, action, roles):
            actions.append(action)
    return actions


def _may(user, lab_request, action, roles):
    if not has_role(user, *roles):
        return False
    physical = lab_request.work_form == LabRequest.WorkForm.PHYSICAL
    if action == "collect" and not physical:
        return False  # a digital scan is not taken by hand
    if action == "send" and physical and lab_request.status == S.APPROVED:
        return False  # the reception first takes the impression / model from the dentist
    if is_only_dentist(user) and action == "cancel" and lab_request.status != S.DRAFT:
        return False  # CIA dentists may cancel only drafts
    return True


@transaction.atomic
def perform_lab_action(lab_request, action, user, notes="", checked=False):
    if action not in TRANSITIONS:
        raise ValidationError(_("Unknown action."))
    sources, target, roles, needs_check, needs_notes = TRANSITIONS[action]
    if not _may(user, lab_request, action, roles):
        raise PermissionDenied
    if lab_request.status not in sources:
        raise ValidationError(_("This action is not possible in the current status."))
    if needs_check and not checked:
        raise ValidationError(_("Confirm that you checked the work against the lab request."))
    if needs_notes and not notes.strip():
        raise ValidationError(_("Please write the reason."))

    now = timezone.now()
    if action == "submit" and lab_request.supervisor_id:
        # The supervisor's name was chosen: it counts as reviewed, ready for the secretary.
        target = S.APPROVED
        lab_request.reviewed_by, lab_request.reviewed_at = user, now
    lab_request.status = target
    if action == "approve":
        lab_request.reviewed_by, lab_request.reviewed_at = user, now
    elif action == "return":
        lab_request.reviewed_by, lab_request.reviewed_at = None, None
    elif action == "collect":
        lab_request.collected_by, lab_request.collected_at = user, now
    elif action == "send":
        lab_request.sent_by, lab_request.sent_at = user, now
        days = lab_request.work_type.default_days
        if not lab_request.due_date and days:  # the usual time for this work (Settings → Lab work types)
            lab_request.due_date = timezone.localdate() + timedelta(days=days)
    elif action == "receive":
        lab_request.received_by, lab_request.received_at = user, now
    elif action == "remake":
        lab_request.remake_count += 1
        lab_request.sent_by, lab_request.sent_at = user, now
        lab_request.received_by, lab_request.received_at = None, None
    elif action == "deliver":
        lab_request.delivered_at = now
    lab_request.save()
    LabRequestEvent.objects.create(
        request=lab_request, action=EVENT_FOR_ACTION[action], by=user, at=now,
        checked_against_request=bool(checked and needs_check), notes=notes,
    )
    if action == "submit" and target == S.APPROVED:
        LabRequestEvent.objects.create(request=lab_request, action=A.APPROVED, by=user, at=now,
                                       notes=str(lab_request.supervisor))
        action = "approve"
    _notify(lab_request, action, user, notes)
    return lab_request


def _requesters(lab_request):
    """The dentist of the request (when they log in) and whoever wrote it."""
    return [lab_request.dentist.user if lab_request.dentist_id else None, lab_request.created_by]


def _notify(lab_request, action, user, notes):
    url = lab_request.get_absolute_url()
    params = {"number": lab_request.number, "patient": lab_request.patient.full_name, "notes": notes}
    if action == "submit":
        notify_roles(
            (HEAD_CIA, SUPERVISOR), _("Lab request %(number)s needs your review"),
            _("Patient: %(patient)s"), url, Notification.Level.WARNING, exclude=user, params=params,
        )
    elif action == "approve":
        notify_roles(
            (SECRETARY,), _("Lab request %(number)s is reviewed - send it to the lab"),
            _("Patient: %(patient)s"), url, exclude=user, params=params,
        )
        notify_users(_requesters(lab_request), _("Your lab request %(number)s was approved"), "", url,
                     Notification.Level.SUCCESS, exclude=user, params=params)
    elif action == "return":
        notify_users(_requesters(lab_request), _("Lab request %(number)s was returned for changes"),
                     "%(notes)s", url, Notification.Level.WARNING, exclude=user, params=params)
    elif action == "receive":
        notify_users(_requesters(lab_request), _("Lab work %(number)s arrived from the lab"),
                     _("Patient: %(patient)s"), url, Notification.Level.SUCCESS, exclude=user, params=params)
        notify_roles((SECRETARY,), _("Lab work %(number)s is ready: book the patient for the fitting"),
                     _("Patient: %(patient)s"), url, Notification.Level.INFO, exclude=user, params=params)
    elif action == "remake":
        notify_roles((HEAD_CIA, SUPERVISOR, OWNER), _("Lab work %(number)s returned to the lab for remake"),
                     "%(notes)s", url, Notification.Level.WARNING, exclude=user, params=params)
