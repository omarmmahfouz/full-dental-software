"""Keep the reception's view of a patient in step with the dentist's: the missing teeth
follow the dental chart, and the medical history follows the last examination."""

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import ToothState
from .teeth import LOWER, UPPER, chart_order, format_teeth

# A jaw counts as fully missing when every tooth but the wisdom teeth is gone.
_UPPER_CORE = set(UPPER) - {18, 28}
_LOWER_CORE = set(LOWER) - {38, 48}


def missing_teeth(patient):
    return chart_order(patient.tooth_states.filter(status=ToothState.Status.MISSING).values_list("tooth", flat=True))


def missing_category(teeth):
    from apps.patients.models import MissingTeeth

    teeth = set(teeth)
    upper, lower = _UPPER_CORE <= teeth, _LOWER_CORE <= teeth
    if upper and lower:
        return MissingTeeth.BOTH_ARCHES
    if upper or lower:
        return MissingTeeth.FULL_ARCH
    return MissingTeeth.MULTIPLE if len(teeth) > 1 else MissingTeeth.SINGLE


def sync_missing_teeth(patient):
    """Once the chart shows missing teeth, the patient file shows the same (category and tooth numbers)."""
    from apps.patients.models import Patient

    teeth = missing_teeth(patient)
    if teeth:
        Patient.objects.filter(pk=patient.pk).update(missing_teeth=missing_category(teeth),
                                                     missing_teeth_notes=format_teeth(teeth))


def sync_medical_history(exam):
    """The dentist's examination is the reference: its diseases become the patient file's list."""
    exam.patient.medical_conditions.set(exam.conditions.all())


@receiver(post_save, sender=ToothState)
@receiver(post_delete, sender=ToothState)
def _tooth_changed(sender, instance, raw=False, **kwargs):
    if not raw:  # a backup being restored already holds the patient's missing teeth
        sync_missing_teeth(instance.patient)
