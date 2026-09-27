from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class ClinicsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.clinics"
    verbose_name = _("Clinics: doctors' shares")
