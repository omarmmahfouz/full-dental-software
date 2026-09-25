from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


def _user_display_name(user):
    return user.get_full_name() or user.username


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"
    verbose_name = _("Core")

    def ready(self):
        from django.contrib.auth import get_user_model

        # Show staff by their real name everywhere (drop-downs, lists, admin).
        get_user_model().__str__ = _user_display_name
        from . import signals  # noqa: F401
