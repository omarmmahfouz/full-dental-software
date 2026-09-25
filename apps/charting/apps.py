from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class ChartingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.charting"
    verbose_name = _("Dental chart")
