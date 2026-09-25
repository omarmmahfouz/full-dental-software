from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class PrescriptionsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.prescriptions"
    verbose_name = _("Prescriptions and instructions")
