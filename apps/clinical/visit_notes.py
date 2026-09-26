"""Every visit needs its notes in the dentist's file: a treatment, an examination or a surgery
chart on that day. The dentist sees the visits still empty on every page; an hour after the
patient left he gets a reminder, and after a day the supervisors are told."""

from datetime import timedelta

from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import Notification
from apps.core.notify import notify_roles, notify_users
from apps.core.roles import HEAD_CIA, TEAM_HEAD
from apps.scheduling.models import Appointment

REMIND_AFTER = timedelta(hours=1)
ESCALATE_AFTER = timedelta(hours=24)
LOOK_BACK_DAYS = 30


def visits_without_notes(dentist=None, days=LOOK_BACK_DAYS):
    """Finished visits (with a dentist) that have nothing written in the patient's file that day."""
    from apps.charting.models import Examination
    from apps.clinical.models import TreatmentStep
    from apps.surgery.models import Surgery

    since = timezone.now() - timedelta(days=days)
    visits = Appointment.objects.filter(status=Appointment.Status.COMPLETED, left_at__gte=since, dentist__isnull=False)
    if dentist is not None:
        visits = visits.filter(Q(dentist=dentist) | Q(second_dentist=dentist))
    visits = list(visits.select_related("patient", "dentist__user", "procedure").order_by("-left_at"))
    if not visits:
        return []
    patients = {v.patient_id for v in visits}
    written = {(p, timezone.localtime(when).date()) for p, when in
               TreatmentStep.objects.filter(patient_id__in=patients, performed_at__gte=since)
               .values_list("patient_id", "performed_at")}
    written |= set(Examination.objects.filter(patient_id__in=patients, exam_date__gte=since.date())
                   .values_list("patient_id", "exam_date"))
    written |= set(Surgery.objects.filter(patient_id__in=patients, date__gte=since.date())
                   .values_list("patient_id", "date"))
    linked = set(TreatmentStep.objects.filter(appointment__in=visits).values_list("appointment_id", flat=True))
    return [v for v in visits if v.pk not in linked
            and (v.patient_id, timezone.localtime(v.scheduled_at).date()) not in written]


def send_notes_alerts(now=None):
    """Remind the dentist once, then tell the supervisors once. Returns the number of alerts."""
    now = now or timezone.now()
    sent = 0
    for visit in visits_without_notes():
        params = {"patient": visit.patient.full_name, "day": timezone.localtime(visit.scheduled_at).strftime("%d/%m/%Y"),
                  "dentist": visit.dentist}
        url = f"/schedule/visit/{visit.pk}/"
        if visit.notes_reminded_at is None and visit.left_at <= now - REMIND_AFTER and visit.dentist.user_id:
            notify_users([visit.dentist.user], _("Write the visit notes: %(patient)s"),
                         _("The visit of %(day)s has nothing in the patient's file yet."), url,
                         Notification.Level.WARNING, params=params)
            Appointment.objects.filter(pk=visit.pk).update(notes_reminded_at=now)
            sent += 1
        if visit.notes_escalated_at is None and visit.left_at <= now - ESCALATE_AFTER:
            notify_roles((HEAD_CIA, TEAM_HEAD), _("Visit notes missing: %(dentist)s"),
                         _("%(patient)s, visit of %(day)s: nothing written in the file after a day."), url,
                         Notification.Level.DANGER, params=params)
            Appointment.objects.filter(pk=visit.pk).update(notes_escalated_at=now)
            sent += 1
    return sent
