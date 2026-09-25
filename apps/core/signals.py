from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import UserProfile


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def ensure_profile(sender, instance, created, raw=False, **kwargs):
    if created and not raw:  # a backup being restored brings its own profiles
        UserProfile.objects.get_or_create(user=instance)
