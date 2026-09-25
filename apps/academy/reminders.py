"""Installments to remind candidates about on WhatsApp."""

from datetime import timedelta

from django.utils import timezone

from apps.scheduling.models import MessageTemplate, SentMessage

from .models import Enrollment


def installment_rows(enrollments, keep, today=None):
    """Installment lines (with what is paid and left) of these enrollments that ``keep`` accepts,
    each with the last WhatsApp reminder sent for it."""
    today = today or timezone.localdate()
    rows = []
    for enrollment in enrollments:
        for row in enrollment.installment_schedule(today):
            if keep(row):
                rows.append({**row, "enrollment": enrollment})
    sent = {}
    for message in SentMessage.objects.filter(installment__in=[r["installment"] for r in rows],
                                              kind=MessageTemplate.Kind.INSTALLMENT).order_by("sent_at"):
        sent[message.installment_id] = message
    for row in rows:
        row["sent"] = sent.get(row["installment"].pk)
    return sorted(rows, key=lambda r: (r["installment"].due_date, r["enrollment"].candidate.full_name))


def reminders_due(days_ahead=3, today=None):
    """Unpaid installments due within ``days_ahead`` days, and the overdue ones."""
    today = today or timezone.localdate()
    limit = today + timedelta(days=days_ahead)
    enrollments = Enrollment.objects.filter(status=Enrollment.Status.ACTIVE).select_related("candidate", "course")
    return installment_rows(enrollments, lambda row: row["remaining"] > 0 and row["installment"].due_date <= limit,
                            today)
