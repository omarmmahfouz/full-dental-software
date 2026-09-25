from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.academy.models import Candidate

from .models import Dentist


@receiver(post_save, sender=Candidate)
def sync_candidate_dentist(sender, instance, created, raw=False, **kwargs):
    """Every course candidate gets a dentist record so they can be chosen as operator."""
    if raw:
        return
    dentist = Dentist.objects.filter(candidate=instance).first()
    if dentist is None:
        Dentist.objects.create(
            candidate=instance, kind=Dentist.Kind.CANDIDATE, full_name=instance.full_name,
            phone=instance.phone_primary, created_by=instance.created_by,
        )
    elif dentist.full_name != instance.full_name or dentist.phone != instance.phone_primary:
        dentist.full_name, dentist.phone = instance.full_name, instance.phone_primary
        dentist.save(update_fields=["full_name", "phone", "updated_at"])
