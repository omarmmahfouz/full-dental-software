from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class SurgeryConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.surgery"
    verbose_name = _("Implant surgery")

    def ready(self):
        from django.db.models.signals import pre_delete

        from apps.stock.implants import give_back

        from .models import SurgerySite

        def implant_back_to_stock(sender, instance, **kwargs):
            give_back(instance)

        pre_delete.connect(implant_back_to_stock, sender=SurgerySite, dispatch_uid="implant_back_to_stock")
