"""Complaints about a dentist that he has not answered in time: remind him and tell the head of CIA."""

from django.db.models import Exists, OuterRef
from django.utils import timezone
from django.utils.translation import gettext_lazy

from apps.core.models import Notification
from apps.core.notify import notify_roles, notify_users
from apps.core.roles import HEAD_CIA, OWNER

from .models import Complaint, ComplaintFollowUp


def unanswered(dentist=None):
    answered = ComplaintFollowUp.objects.filter(complaint=OuterRef("pk"), action=ComplaintFollowUp.Action.DENTIST_ANSWER)
    qs = (Complaint.objects.filter(status__in=Complaint.OPEN_STATUSES, concerned_dentist__isnull=False)
          .exclude(Exists(answered)).select_related("patient", "concerned_dentist__user"))
    return qs.filter(concerned_dentist=dentist) if dentist is not None else qs


def send_answer_alerts(today=None):
    """Once per complaint, when the answer is late. Safe to call often (e.g. when the home page opens)."""
    today = today or timezone.localdate()
    sent = 0
    for complaint in unanswered().filter(answer_alert_sent_at__isnull=True):
        if complaint.answer_due >= today:
            continue
        params = {"number": complaint.number, "dentist": complaint.concerned_dentist.full_name,
                  "patient": complaint.patient.full_name}
        if complaint.concerned_dentist.user_id:
            notify_users([complaint.concerned_dentist.user], gettext_lazy("Complaint %(number)s is waiting for your answer"),
                         gettext_lazy("%(patient)s: write your answer and what will be done."),
                         complaint.get_absolute_url(), Notification.Level.DANGER, params=params)
        notify_roles((HEAD_CIA, OWNER), gettext_lazy("No answer from %(dentist)s to complaint %(number)s"),
                     gettext_lazy("%(patient)s: the dentist has not answered in time."), complaint.get_absolute_url(),
                     Notification.Level.DANGER, params=params)
        Complaint.objects.filter(pk=complaint.pk).update(answer_alert_sent_at=timezone.now())
        sent += 1
    return sent
