from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class ReadingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "reading"
    verbose_name = _("Paper Reader")
