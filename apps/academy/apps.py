from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class AcademyConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.academy"
    verbose_name = _("Academy")
