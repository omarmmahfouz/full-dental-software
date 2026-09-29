from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class SpecialtiesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.specialties"
    verbose_name = _("Specialists: referrals, endodontics, TMJ, orthodontics, shades")
