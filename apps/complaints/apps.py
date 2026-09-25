from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class ComplaintsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.complaints"
    verbose_name = _("Complaints")
