from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class ClinicalConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.clinical"
    verbose_name = _("Clinical")

    def ready(self):
        from . import grading  # noqa: F401  (the supervisor is told of the work that names him, round 16)
