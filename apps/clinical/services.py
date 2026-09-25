"""Lab request workflow: every status change goes through ``perform_lab_action``
so permissions, timestamps, history and notifications stay consistent."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import Notification
from apps.core.notify import notify_roles, notify_users
from apps.core.roles import DENTIST, FRONT_DESK, MANAGEMENT, OWNER, SECRETARY, SUPERVISOR, has_role

from .models import LabRequest, LabRequestEvent

S = LabRequest.Status
A = LabRequestEvent.Action

# action -> (allowed "from" statuses, "to" status, roles allowed, needs work check, needs notes)
TRANSITIONS = {
    "submit": ((S.DRAFT,), S.PENDING_REVIEW, FRONT_DESK + (DENTIST,), False, False),
    "approve": ((S.PENDING_REVIEW,), S.APPROVED, MANAGEMENT, False, False),
    "return": ((S.PENDING_REVIEW, S.APPROVED), S.DRAFT, MANAGEMENT, False, True),
    "send": ((S.APPROVED,), S.SENT, FRONT_DESK, True, False),
    "receive": ((S.SENT,), S.RECEIVED, FRONT_DESK, True, False),
    "remake": ((S.RECEIVED,), S.SENT, FRONT_DESK + (DENTIST,), False, True),
    "deliver": ((S.RECEIVED,), S.DELIVERED, FRONT_DESK + (DENTIST,), False, False),
    "cancel": ((S.DRAFT, S.PENDING_REVIEW, S.APPROVED), S.CANCELLED, MANAGEMENT + (DENTIST,), False, True),
}

EVENT_FOR_ACTION = {
    "submit": A.SUBMITTED, "approve": A.APPROVED, "return": A.RETURNED, "send": A.SENT,
    "receive": A.RECEIVED, "remake": A.REMAKE, "deliver": A.DELIVERED, "cancel": A.CANCELLED,
}

ACTION_LABELS = {
    "submit": _("Send for supervisor review"),
    "approve": _("Approve (reviewed)"),
    "return": _("Return to doctor for changes"),
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
    only_dentist = has_role(user, DENTIST) and not has_role(user, *FRONT_DESK)
    if only_dentist:
        # Dentists act only on their own requests; they may cancel only drafts.
        if lab_request.dentist_id is None or lab_request.dentist.user_id != user.pk:
            return False
        if action == "cancel" and lab_request.status != S.DRAFT:
            return False
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
    lab_request.status = target
    if action == "approve":
        lab_request.reviewed_by, lab_request.reviewed_at = user, now
    elif action == "return":
        lab_request.reviewed_by, lab_request.reviewed_at = None, None
    elif action == "send":
        lab_request.sent_by, lab_request.sent_at = user, now
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
    _notify(lab_request, action, user, notes)
    return lab_request


def _requester(lab_request):
    return lab_request.dentist.user if lab_request.dentist_id else None


def _notify(lab_request, action, user, notes):
    url = lab_request.get_absolute_url()
    params = {"number": lab_request.number, "patient": lab_request.patient.full_name, "notes": notes}
    if action == "submit":
        notify_roles(
            (SUPERVISOR,), _("Lab request %(number)s needs your review"),
            _("Patient: %(patient)s"), url, Notification.Level.WARNING, exclude=user, params=params,
        )
    elif action == "approve":
        notify_roles(
            (SECRETARY,), _("Lab request %(number)s is reviewed - send it to the lab"),
            _("Patient: %(patient)s"), url, exclude=user, params=params,
        )
        notify_users([_requester(lab_request)], _("Your lab request %(number)s was approved"), "", url,
                     Notification.Level.SUCCESS, exclude=user, params=params)
    elif action == "return":
        notify_users([_requester(lab_request)], _("Lab request %(number)s was returned for changes"),
                     "%(notes)s", url, Notification.Level.WARNING, exclude=user, params=params)
    elif action == "receive":
        notify_users([_requester(lab_request)], _("Lab work %(number)s arrived from the lab"),
                     _("Patient: %(patient)s"), url, Notification.Level.SUCCESS, exclude=user, params=params)
    elif action == "remake":
        notify_roles((SUPERVISOR, OWNER), _("Lab work %(number)s returned to the lab for remake"),
                     "%(notes)s", url, Notification.Level.WARNING, exclude=user, params=params)
