"""The visit after a surgery, by what was done: after a sinus lift a check after 2 days, after a bone or gum graft a
check after a week, otherwise the suture removal after a week (the days are in Settings → Clinic options). The
instructions page and the surgery chart show it; the dentist asks the reception to book it (a patient on his list,
already approved) or the reception books it."""

from datetime import timedelta

from django.utils import timezone, translation
from django.utils.translation import gettext_lazy as _

from apps.core.models import ClinicSettings

SINUS = {"open_sinus", "closed_sinus"}
GRAFTS = {"gbr", "soft_tissue", "expansion", "splitting"}


def follow_up(surgery):
    """{"days", "on", "reason", "step"}: when and why the patient comes back (None without a surgery)."""
    from apps.prescriptions.services import surgery_procedures

    if surgery is None:
        return None
    options = ClinicSettings.get()
    codes = surgery_procedures(surgery)
    if codes & SINUS:
        days, reason, step = options.follow_up_sinus_days, _("Check after the sinus lift"), "Follow-up"
    elif codes & GRAFTS:
        days, reason, step = options.follow_up_graft_days, _("Check the graft and remove the sutures"), "Suture removal"
    else:
        days, reason, step = options.follow_up_days, _("Suture removal"), "Suture removal"
    return {"days": days, "on": surgery.date + timedelta(days=days), "reason": reason, "step": step}


def ask_reception(surgery, user):
    """Put the follow-up on the dentist's patient list, approved, for the reception to call and book.
    Returns (request, created)."""
    from apps.clinical.models import TreatmentStepType
    from apps.dentists.models import Dentist
    from apps.scheduling.models import PatientRequest

    visit = follow_up(surgery)
    step_type = (TreatmentStepType.objects.filter(name_en=visit["step"]).first()
                 or TreatmentStepType.objects.filter(name_en="Follow-up").first())
    dentist = Dentist.for_user(user) or surgery.operator_1
    open_request = PatientRequest.objects.filter(patient=surgery.patient, step_type=step_type,
                                                 status__in=PatientRequest.OPEN).first()
    if open_request is not None:
        return open_request, False
    teeth = ", ".join(str(site.tooth) for site in surgery.sites.all())
    with translation.override("ar"):  # read by the reception
        note = f"{surgery.number}: {visit['reason']}"
    request = PatientRequest.objects.create(
        dentist=dentist, patient=surgery.patient, step_type=step_type, teeth=teeth[:100], minutes=15,
        wanted_from=max(visit["on"], timezone.localdate()), wanted_to=visit["on"] + timedelta(days=2),
        notes=note[:255], status=PatientRequest.Status.APPROVED,
        decided_by=user, decided_at=timezone.now(), created_by=user)
    return request, True
