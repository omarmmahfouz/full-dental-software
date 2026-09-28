"""Moving a patient to another of our places (rare).

Each place keeps its own patients: a place never sees the names of another place's patients. When a patient
moves, the file at the old place is closed ("out", with the new file number), and the patient gets a file of
the new place with a new number. Only the person's details and medical conditions go with them; visits,
charts, bills and photos stay in the old file. A patient who comes back to a place gets their old file there
opened again."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from .models import OutReason, Patient

# The person's details that go with them to the new file.
COPIED = ["full_name", "id_type", "national_id", "birth_date", "gender", "marital_status", "phone_primary",
          "phone_secondary", "preferred_phone", "address", "city", "governorate", "occupation", "missing_teeth",
          "missing_teeth_notes", "medical_notes", "referral_source"]
MOVED_REASON = "Moved to another of our places (new file)"


def moved_reason():
    reason = OutReason.objects.filter(name_en=MOVED_REASON).first()
    return reason or OutReason.objects.create(name_ar="انتقل لمكان آخر من أماكننا (ملف جديد)", name_en=MOVED_REASON)


def transfer(patient, place, user):
    """Move ``patient`` to ``place``. Returns (the file at the new place, how many visits at the old place were
    cancelled)."""
    from apps.scheduling.models import Appointment

    if place.pk == patient.branch_id:
        raise ValidationError(_("The patient is already at %(place)s.") % {"place": place.code})
    today = timezone.localdate()
    with transaction.atomic():
        new = Patient.objects.filter(branch=place, national_id=patient.national_id).first()
        if new is not None:  # came back: the old file of that place is opened again
            new.status, new.out_reason, new.out_notes = Patient.Status.ACTIVE, None, ""
            new.notes = "\n".join(filter(None, [new.notes, _("Came back from %(file)s on %(day)s.") % {
                "file": patient.file_number, "day": today.strftime("%d/%m/%Y")}]))
            new.save()
        else:
            taken = Patient.objects.filter(branch=place, phone_primary=patient.phone_primary).first()
            if taken is not None:
                raise ValidationError(_("The mobile %(phone)s belongs to another patient at %(place)s. Change the "
                                        "patient's first mobile, then move the file.")
                                      % {"phone": patient.phone_primary, "place": place.code})
            new = Patient(branch=place, registered_on=today, created_by=user,
                          notes=_("Moved from %(file)s on %(day)s.") % {"file": patient.file_number,
                                                                        "day": today.strftime("%d/%m/%Y")})
            for name in COPIED:
                setattr(new, name, getattr(patient, name))
            new.save()
        new.medical_conditions.add(*patient.medical_conditions.all())
        patient.status, patient.out_reason = Patient.Status.OUT, moved_reason()
        patient.out_notes = f"→ {place.code} {new.file_number}"
        patient.transferred_to = new
        patient.save(update_fields=["status", "out_reason", "out_notes", "transferred_to", "updated_at"])
        cancelled = Appointment.objects.filter(
            patient=patient, status__in=Appointment.WAITING_STATUSES, scheduled_at__gte=timezone.now()).update(
            status=Appointment.Status.CANCELLED, cancel_reason=_("The patient moved to %(place)s.") % {"place": place.code})
    return new, cancelled
