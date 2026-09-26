from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class BillingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.billing"
    verbose_name = _("Patient payments")

    def ready(self):
        from django.db.models.signals import post_save

        from apps.academy.models import Payment

        from .fawry import sync
        from .models import PatientPayment

        def keep_fawry_in_step(sender, instance, raw=False, **kwargs):
            if not raw:
                sync(instance)

        # A purchase is synced by its form, once its items (and so its total) are saved.
        post_save.connect(keep_fawry_in_step, sender=PatientPayment, dispatch_uid="fawry_patient_payment")
        post_save.connect(keep_fawry_in_step, sender=Payment, dispatch_uid="fawry_academy_payment")
