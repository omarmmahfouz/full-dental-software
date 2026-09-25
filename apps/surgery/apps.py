from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class SurgeryConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.surgery"
    verbose_name = _("Implant surgery")
