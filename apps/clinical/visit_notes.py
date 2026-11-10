"""Every visit needs its notes in the dentist's file: a treatment, an examination or a surgery
chart on that day. The dentist sees the visits still empty on every page; an hour after the
patient left he gets a reminder, and after a day the supervisors are told."""

from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import Notification, staff_at
from apps.core.notify import make_notifications
from apps.core.roles import CLINICAL, HEAD_CIA, MODERATOR, OWNER, TEAM_HEAD, has_role, users_with_role
from apps.scheduling.models import Appointment

REMIND_AFTER = timedelta(hours=1)
ESCALATE_AFTER = timedelta(hours=24)
LOOK_BACK_DAYS = 30
# A visit closed later than this after its day is not looked for (it keeps the look-up within the last months).
LATE_CLOSING = timedelta(days=60)
MAX_ALERTS = 200  # in one run


def _empty_visit_ids(dentist, since, not_alerted=False):
    """The finished visits since ``since`` with nothing written in the patient's file on their day (no treatment
    linked to the visit; no treatment, examination or surgery chart of that day): their pks, the last to leave
    first. Read lightly and by index (the dentist and the day): this runs on every page a dentist opens."""
    from apps.charting.models import Examination
    from apps.clinical.models import TreatmentStep
    from apps.surgery.models import Surgery

    visits = Appointment.objects.filter(left_at__gte=since, scheduled_at__gte=since - LATE_CLOSING)
    if not_alerted:
        visits = visits.filter(Q(notes_reminded_at__isnull=True) | Q(notes_escalated_at__isnull=True))
    fields = ("pk", "patient_id", "scheduled_at", "left_at", "status")
    if dentist is None:
        rows = list(visits.filter(dentist__isnull=False, status=Appointment.Status.COMPLETED).values_list(*fields))
    else:  # two look-ups, each by its own index (one with "or" read every finished visit of the clinic)
        rows = list(visits.filter(dentist=dentist).values_list(*fields))
        rows += list(visits.filter(second_dentist=dentist, dentist__isnull=False).exclude(dentist=dentist)
                     .values_list(*fields))
    rows = [row for row in rows if row[4] == Appointment.Status.COMPLETED]
    if not rows:
        return []
    with_step = set()
    for chunk in _chunks([row[0] for row in rows]):
        with_step.update(TreatmentStep.objects.filter(appointment_id__in=chunk).values_list("appointment_id", flat=True))
    rows = [row for row in rows if row[0] not in with_step]
    patients = {row[1] for row in rows}
    written = set()
    for chunk in _chunks(sorted(patients)):
        written |= {(p, timezone.localtime(when).date()) for p, when in
                    TreatmentStep.objects.filter(patient_id__in=chunk, performed_at__gte=since)
                    .values_list("patient_id", "performed_at")}
        written |= set(Examination.objects.filter(patient_id__in=chunk, exam_date__gte=since.date())
                       .values_list("patient_id", "exam_date"))
        written |= set(Surgery.objects.filter(patient_id__in=chunk, date__gte=since.date())
                       .values_list("patient_id", "date"))
    rows = [row for row in rows if (row[1], timezone.localtime(row[2]).date()) not in written]
    return [row[0] for row in sorted(rows, key=lambda row: row[3], reverse=True)]


def _chunks(ids, size=500):
    for start in range(0, len(ids), size):
        yield ids[start:start + size]


def count_without_notes(dentist, days=LOOK_BACK_DAYS):
    """How many of the dentist's visits wait for their notes: the number beside his menu, on every page."""
    return len(_empty_visit_ids(dentist, timezone.now() - timedelta(days=days)))


def visits_without_notes(dentist=None, days=LOOK_BACK_DAYS, not_alerted=False):
    """Finished visits (with a dentist) that have nothing written in the patient's file that day.
    ``not_alerted``: only those whose reminder or warning has not gone out yet."""
    ids = _empty_visit_ids(dentist, timezone.now() - timedelta(days=days), not_alerted)
    visits = []
    for chunk in _chunks(ids):
        visits += Appointment.objects.filter(pk__in=chunk).select_related("patient", "dentist__user", "procedure",
                                                                         "branch")
    return sorted(visits, key=lambda visit: visit.left_at, reverse=True)


def followers_at(place):
    """Who is told about the visits of ``place`` left without notes: its heads (the head of CIA, the head of the
    dentists team, the clinic's manager) who work there and open the patients' files. The head of CIA was told about
    El Khadem's visits, which she cannot open. Nobody at the place: the owner."""
    heads = [user for user in staff_at(place, HEAD_CIA, TEAM_HEAD, MODERATOR) if has_role(user, *CLINICAL)]
    return heads or list(users_with_role(OWNER))


def send_notes_alerts(now=None, limit=MAX_ALERTS):
    """Remind the dentist once, then tell the heads of the visit's place once. Returns the number of alerts.
    Written together at the end (it was one save per visit, inside the page of whoever opened the home page first:
    16 seconds after a busy week), and at most ``limit`` in one go; the rest go out at the next run."""
    now = now or timezone.now()
    rows, reminded, escalated, followers, languages, opens, sent = [], [], [], {}, {}, {}, 0
    for visit in visits_without_notes(not_alerted=True):
        if sent >= limit:
            break
        params = {"patient": visit.patient.full_name, "day": timezone.localtime(visit.scheduled_at).strftime("%d/%m/%Y"),
                  "dentist": visit.dentist}
        url = f"/schedule/visit/{visit.pk}/"
        user = visit.dentist.user if visit.dentist.user_id else None
        if visit.notes_reminded_at is None and visit.left_at <= now - REMIND_AFTER:
            if user is not None and user.pk not in opens:
                opens[user.pk] = has_role(user, *CLINICAL)  # a supervisor who only grades does not open the visits
            if user is not None and opens[user.pk]:
                rows += make_notifications(
                    [user], _("Write the visit notes: %(patient)s"),
                    _("The visit of %(day)s has nothing in the patient's file yet."), url,
                    Notification.Level.WARNING, params=params, languages=languages)
                reminded.append(visit.pk)
                sent += 1
            elif visit.left_at <= now - ESCALATE_AFTER:
                reminded.append(visit.pk)  # nobody to remind: the visit leaves the list once the heads are told
        if visit.notes_escalated_at is None and visit.left_at <= now - ESCALATE_AFTER:
            if visit.branch_id not in followers:
                followers[visit.branch_id] = followers_at(visit.branch)
            rows += make_notifications(
                followers[visit.branch_id], _("Visit notes missing: %(dentist)s"),
                _("%(patient)s, visit of %(day)s: nothing written in the file after a day."), url,
                Notification.Level.DANGER, exclude=user, params=params, languages=languages)
            escalated.append(visit.pk)
            sent += 1
    if reminded or escalated:
        with transaction.atomic():
            Notification.objects.bulk_create(rows, batch_size=500)
            Appointment.objects.filter(pk__in=reminded).update(notes_reminded_at=now)
            Appointment.objects.filter(pk__in=escalated).update(notes_escalated_at=now)
    return sent
