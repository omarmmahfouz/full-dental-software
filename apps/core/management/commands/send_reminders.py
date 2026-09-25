"""Daily reminders (schedule it every morning with cron / Windows Task Scheduler).

- complaints whose follow-up date has passed  -> assigned supervisor (or all supervisors)
- lab work late at the lab                    -> secretaries
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.clinical.models import LabRequest
from apps.complaints.models import Complaint
from apps.core.models import Notification
from apps.core.notify import notify_roles, notify_users
from apps.core.roles import HEAD_CIA, OWNER, SECRETARY, SUPERVISOR


class Command(BaseCommand):
    help = "Create reminder notifications for overdue complaints and late lab work."

    def handle(self, *args, **options):
        today = timezone.localdate()
        sent = 0
        overdue = Complaint.objects.filter(status__in=Complaint.OPEN_STATUSES, follow_up_due__lt=today).select_related(
            "patient", "assigned_to"
        )
        for complaint in overdue:
            params = {"number": complaint.number, "patient": complaint.patient.full_name}
            title = _("Complaint %(number)s needs follow-up (overdue)")
            message = _("Patient: %(patient)s")
            if complaint.assigned_to:
                sent += notify_users([complaint.assigned_to], title, message, complaint.get_absolute_url(),
                                     Notification.Level.DANGER, params=params)
            else:
                sent += notify_roles((HEAD_CIA, SUPERVISOR, OWNER), title, message, complaint.get_absolute_url(),
                                     Notification.Level.DANGER, params=params)

        late_labs = LabRequest.objects.filter(status=LabRequest.Status.SENT, due_date__lt=today).select_related(
            "patient", "lab"
        )
        for lab_request in late_labs:
            sent += notify_roles(
                (SECRETARY,), _("Lab work %(number)s is late at %(lab)s"), _("Patient: %(patient)s"),
                lab_request.get_absolute_url(), Notification.Level.WARNING,
                params={"number": lab_request.number, "lab": lab_request.lab.name, "patient": lab_request.patient.full_name},
            )
        self.stdout.write(self.style.SUCCESS(f"{sent} reminder notifications created."))
