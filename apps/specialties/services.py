"""What happens around the specialists' records: telling the people concerned about a referral, and marking a
root canal on the dental chart when the tooth is obturated."""

from datetime import datetime

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy

from apps.core.models import Notification, staff_at
from apps.core.notify import notify_users
from apps.core.roles import SECRETARY

from .models import EndoCase, OrthoCase, Referral, ShadeRecord, TMJExam


def tell_about_referral(referral, user):
    """The specialist (when he logs in) and the reception of the place: a patient to see and to book."""
    # The doctors' names are written in each reader's language (the Arabic name for the reception).
    params = {"patient": referral.patient.full_name, "doctor": referral.to_dentist or referral.to_outside,
              "by": referral.from_dentist or user}
    if referral.to_dentist_id and referral.to_dentist.user_id:
        notify_users([referral.to_dentist.user], gettext_lazy("A patient referred to you: %(patient)s"),
                     gettext_lazy("From %(by)s."), referral.get_absolute_url(),
                     Notification.Level.WARNING if referral.urgency == Referral.Urgency.URGENT else Notification.Level.INFO,
                     exclude=user, params=params)
    if referral.to_dentist_id:
        notify_users(staff_at(referral.branch, SECRETARY), gettext_lazy("Book a referred patient: %(patient)s"),
                     gettext_lazy("With %(doctor)s, referred by %(by)s."), referral.get_absolute_url(),
                     exclude=user, params=params)


def tell_reply(referral, user):
    doctor = referral.from_dentist
    if doctor is not None and doctor.user_id:
        notify_users([doctor.user], gettext_lazy("Answer from %(doctor)s: %(patient)s"),
                     gettext_lazy("The specialist answered your referral."), referral.get_absolute_url(),
                     Notification.Level.SUCCESS, exclude=user,
                     params={"doctor": referral.to_dentist or referral.to_outside, "patient": referral.patient.full_name})


def link_booking(request, appointment):
    """A booking made from a referral (``?referral=``) marks it booked."""
    pk = request.GET.get("referral") or request.POST.get("referral")
    if not pk or not str(pk).isdigit():
        return None
    referral = Referral.objects.filter(pk=pk, patient_id=appointment.patient_id, status__in=Referral.OPEN).first()
    if referral is not None:
        referral.appointment, referral.status = appointment, Referral.Status.BOOKED
        referral.save(update_fields=["appointment", "status", "updated_at"])
    return referral


@transaction.atomic
def finish_endo(case, user):
    """The tooth is obturated: the case is finished, a root canal treatment is written in the treatment log and the
    dental chart marks the tooth (with the plan items of the same treatment ticked)."""
    from apps.clinical.models import ChartEffect, TreatmentStep, TreatmentStepType
    from apps.clinical.views import record_treatment_on_chart

    case.status = EndoCase.Status.OBTURATED
    case.obturated_on = case.obturated_on or timezone.localdate()
    step = None
    if case.treatment_step_id is None and case.treatment != EndoCase.Treatment.PULPOTOMY:
        step_type = TreatmentStepType.objects.filter(chart_effect=ChartEffect.RCT, is_active=True).order_by(
            "sort_order", "pk").first()
        if step_type is not None:
            canals = ", ".join(f"{c.name} {c.working_length or '—'} mm {c.master_file}".strip()
                               for c in case.canals.all())
            when = timezone.now()
            if case.obturated_on != timezone.localdate():  # written later: on the day it was obturated
                when = timezone.make_aware(datetime.combine(case.obturated_on, timezone.localtime().time()))
            step = TreatmentStep.objects.create(
                patient=case.patient, step_type=step_type, teeth=str(case.tooth), operator=case.dentist,
                performed_at=when, created_by=user,
                notes=f"{case.get_treatment_display()}. {canals}".strip(),
                material=case.get_sealer_display() if case.sealer else "")
            record_treatment_on_chart(step, user)
            case.treatment_step = step
    case.save()
    return step


def records_of(patient):
    """The specialists' records of a patient, newest first, for the patient's file."""
    return {
        "referrals": list(Referral.objects.filter(patient=patient).select_related("from_dentist", "to_dentist",
                                                                                 "appointment")),
        "endo": list(EndoCase.objects.filter(patient=patient).select_related("dentist")),
        "tmj": list(TMJExam.objects.filter(patient=patient).select_related("dentist")),
        "ortho": list(OrthoCase.objects.filter(patient=patient).select_related("dentist")),
        "shades": list(ShadeRecord.objects.filter(patient=patient).select_related("dentist")),
    }
