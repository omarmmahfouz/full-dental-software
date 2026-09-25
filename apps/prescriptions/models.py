from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import LookupModel, TimeStampedModel

PROCEDURE_HELP = _(
    "Surgery procedures this fits, comma separated: extraction, flap, simple_implant, immediate_implant, "
    "guided, expansion, splitting, closed_sinus, open_sinus, gbr, soft_tissue. Empty = every surgery."
)


class DrugGroup(LookupModel):
    """Interchangeable drugs: one active ingredient and strength, several brands."""

    class Kind(models.TextChoices):
        ANTIBIOTIC = "antibiotic", _("Antibiotic")
        PAINKILLER = "painkiller", _("Painkiller / anti-inflammatory")
        MOUTHWASH = "mouthwash", _("Mouthwash / local")
        OTHER = "other", _("Other")

    kind = models.CharField(_("type"), max_length=20, choices=Kind.choices, default=Kind.OTHER)
    dose = models.CharField(_("how to take it (for the patient)"), max_length=255,
                            help_text=_("Printed on the prescription, usually in Arabic."))

    class Meta(LookupModel.Meta):
        verbose_name = _("drug group (interchangeable drugs)")
        verbose_name_plural = _("drug groups (interchangeable drugs)")


class Drug(models.Model):
    group = models.ForeignKey(DrugGroup, verbose_name=_("group"), on_delete=models.CASCADE, related_name="drugs")
    name = models.CharField(_("brand name and strength"), max_length=120)
    preferred = models.BooleanField(_("chosen first"), default=False)
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        ordering = ["group__sort_order", "-preferred", "name"]
        verbose_name = _("drug")
        verbose_name_plural = _("drugs")

    def __str__(self):
        return self.name


class PrescriptionTemplate(LookupModel):
    """A ready prescription, e.g. "After implant surgery"."""

    procedures = models.CharField(_("fits these procedures"), max_length=255, blank=True, help_text=PROCEDURE_HELP)
    for_penicillin_allergy = models.BooleanField(_("for patients allergic to penicillin"), default=False)

    class Meta(LookupModel.Meta):
        verbose_name = _("prescription template")
        verbose_name_plural = _("prescription templates")

    def procedure_set(self):
        return {p.strip() for p in self.procedures.split(",") if p.strip()}


class PrescriptionTemplateLine(models.Model):
    template = models.ForeignKey(PrescriptionTemplate, on_delete=models.CASCADE, related_name="lines")
    group = models.ForeignKey(DrugGroup, verbose_name=_("drug group"), on_delete=models.PROTECT)
    dose = models.CharField(_("how to take it"), max_length=255, blank=True,
                            help_text=_("Leave empty to use the group's usual dose."))
    sort_order = models.PositiveIntegerField(_("sort order"), default=0)

    class Meta:
        ordering = ["sort_order", "pk"]
        verbose_name = _("template line")
        verbose_name_plural = _("template lines")


class Prescription(TimeStampedModel):
    patient = models.ForeignKey("patients.Patient", verbose_name=_("patient"), on_delete=models.PROTECT,
                                related_name="prescriptions")
    surgery = models.ForeignKey("surgery.Surgery", verbose_name=_("surgery"), null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="prescriptions")
    prescribed_on = models.DateField(_("date"), default=timezone.localdate)
    dentist = models.ForeignKey("dentists.Dentist", verbose_name=_("dentist"), null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="prescriptions")
    notes = models.CharField(_("notes for the patient"), max_length=255, blank=True)

    class Meta:
        ordering = ["-prescribed_on", "-pk"]
        verbose_name = _("prescription")
        verbose_name_plural = _("prescriptions")

    def __str__(self):
        return f"{self.patient} {self.prescribed_on}"

    def get_absolute_url(self):
        return reverse("prescriptions:print", args=[self.pk])


class PrescriptionLine(models.Model):
    prescription = models.ForeignKey(Prescription, on_delete=models.CASCADE, related_name="lines")
    drug = models.ForeignKey(Drug, verbose_name=_("drug"), on_delete=models.PROTECT)
    dose = models.CharField(_("how to take it"), max_length=255)

    class Meta:
        ordering = ["pk"]
        verbose_name = _("prescription line")
        verbose_name_plural = _("prescription lines")


class InstructionSheet(LookupModel):
    """Post-operative instructions printed for the patient with their name and surgery."""

    procedures = models.CharField(_("fits these procedures"), max_length=255, blank=True, help_text=PROCEDURE_HELP)
    body_ar = models.TextField(_("instructions (Arabic)"), help_text=_("One instruction per line."))
    body_en = models.TextField(_("instructions (English)"), blank=True, help_text=_("One instruction per line."))

    class Meta(LookupModel.Meta):
        verbose_name = _("post-operative instruction sheet")
        verbose_name_plural = _("post-operative instruction sheets")

    def procedure_set(self):
        return {p.strip() for p in self.procedures.split(",") if p.strip()}

    def lines(self, language="ar"):
        body = self.body_en if language == "en" and self.body_en else self.body_ar
        return [line.strip() for line in body.splitlines() if line.strip()]
