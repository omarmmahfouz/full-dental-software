from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class DentistsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.dentists"
    verbose_name = _("Dentists")

    def ready(self):
        from . import signals  # noqa: F401
