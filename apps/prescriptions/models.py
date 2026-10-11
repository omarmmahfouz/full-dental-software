from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import LookupModel, TimeStampedModel

PROCEDURE_HELP = _(
    "Surgery procedures this fits, comma separated: extraction, flap, simple_implant, immediate_implant, "
    "guided, expansion, splitting, closed_sinus, open_sinus, gbr, soft_tissue; delivery = the day the teeth on the "
    "implants are delivered. Empty = every surgery."
)


class DrugGroup(LookupModel):
    """Interchangeable drugs: one active ingredient and strength, several brands."""

    class Kind(models.TextChoices):
        ANTIBIOTIC = "antibiotic", _("Antibiotic")
        PAINKILLER = "painkiller", _("Painkiller / anti-inflammatory")
        MOUTHWASH = "mouthwash", _("Mouthwash / local")
        INJECTION = "injection", _("Injection (IM / IV)")
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
    # Round 16 (El Khadem): each specialty has its own prescriptions (after a root canal, for the TMJ muscles...).
    specialty = models.CharField(_("for the specialty"), max_length=20, blank=True,
                                 choices=[("", _("Any doctor"))] + [
                                     ("endodontist", _("Endodontist")), ("tmj", _("TMJ specialist (oral surgeon)")),
                                     ("orthodontist", _("Orthodontist")), ("oral_surgeon", _("Oral surgeon")),
                                     ("prosthodontist", _("Prosthodontist")), ("periodontist", _("Periodontist")),
                                     ("pedodontist", _("Paediatric dentist"))],
                                 help_text=_("Offered first to the doctors of this specialty."))

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


class SickLeave(TimeStampedModel):
    """A professional sick leave (round 16): the dentist certifies that the patient was treated and needs rest from
    work or school for some days. Printed on the place's paper with the doctor's signature."""

    class Purpose(models.TextChoices):
        WORK = "work", _("For his work")
        SCHOOL = "school", _("For his school or university")
        ANY = "any", _("To whom it may concern")

    patient = models.ForeignKey("patients.Patient", verbose_name=_("patient"), on_delete=models.PROTECT,
                                related_name="sick_leaves")
    branch = models.ForeignKey("core.Branch", verbose_name=_("place"), on_delete=models.PROTECT, related_name="+")
    dentist = models.ForeignKey("dentists.Dentist", verbose_name=_("doctor"), null=True, on_delete=models.SET_NULL,
                                related_name="sick_leaves")
    seen_on = models.DateField(_("seen on"), default=timezone.localdate)
    diagnosis = models.CharField(_("diagnosis"), max_length=255)
    treatment = models.CharField(_("treatment done"), max_length=255, blank=True)
    days = models.PositiveSmallIntegerField(_("days of rest"), default=1)
    starts_on = models.DateField(_("from"), default=timezone.localdate)
    purpose = models.CharField(_("for"), max_length=8, choices=Purpose.choices, default=Purpose.ANY)
    advice = models.CharField(_("advice"), max_length=255, blank=True,
                              help_text=_("e.g. rest at home, no hard effort, soft food."))

    class Meta:
        ordering = ["-seen_on", "-pk"]
        verbose_name = _("sick leave")
        verbose_name_plural = _("sick leaves")

    def __str__(self):
        return f"{self.number} — {self.patient.full_name}"

    @property
    def number(self):
        return f"SL-{self.pk:05d}" if self.pk else ""

    @property
    def ends_on(self):
        from datetime import timedelta

        return self.starts_on + timedelta(days=max(self.days, 1) - 1)

    def get_absolute_url(self):
        return reverse("prescriptions:sick_leave", args=[self.pk])


class ConsentTemplate(LookupModel):
    """A consent form (round 16): what the procedure is, its risks and the other options, in Arabic and English. The
    owner and the head of CIA edit them in Settings → Consent forms."""

    procedures = models.CharField(_("fits these procedures"), max_length=255, blank=True,
                                  help_text=_("Words of the treatments it fits, comma separated (implant, extraction, "
                                              "root canal, orthodontic...). Empty = every treatment."))
    body_ar = models.TextField(_("the consent (Arabic)"), help_text=_("One point per line."))
    body_en = models.TextField(_("the consent (English)"), blank=True, help_text=_("One point per line."))

    class Meta(LookupModel.Meta):
        verbose_name = _("consent form")
        verbose_name_plural = _("consent forms")

    def lines(self, language="ar"):
        body = self.body_en if language == "en" and self.body_en else self.body_ar
        return [line.strip() for line in body.splitlines() if line.strip()]


def consent_paper_path(instance, filename):
    import os
    import uuid

    ext = os.path.splitext(filename)[1].lower()[:10]
    return f"patients/{instance.patient_id}/consents/{uuid.uuid4().hex}{ext}"


class PatientConsent(TimeStampedModel):
    """A consent the patient signed (round 16): the form, the procedure and teeth, his signature drawn on the tablet
    (or the paper signed and photographed), the doctor and a witness."""

    patient = models.ForeignKey("patients.Patient", verbose_name=_("patient"), on_delete=models.PROTECT,
                                related_name="consents")
    branch = models.ForeignKey("core.Branch", verbose_name=_("place"), on_delete=models.PROTECT, related_name="+")
    template = models.ForeignKey(ConsentTemplate, verbose_name=_("consent form"), on_delete=models.PROTECT,
                                 related_name="signed")
    dentist = models.ForeignKey("dentists.Dentist", verbose_name=_("doctor"), null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="consents")
    procedure = models.CharField(_("the procedure"), max_length=255)
    teeth = models.CharField(_("teeth"), max_length=100, blank=True)
    language = models.CharField(_("language"), max_length=2, choices=[("ar", "العربية"), ("en", "English")],
                                default="ar")
    signed_by = models.CharField(_("signed by"), max_length=150, blank=True,
                                 help_text=_("Empty = the patient. For a child or a patient who cannot sign: the "
                                             "guardian's name and relation."))
    witness = models.CharField(_("witness"), max_length=150, blank=True)
    signature = models.TextField(_("the patient's signature"), blank=True, editable=False)
    signed_at = models.DateTimeField(_("signed at"), null=True, blank=True)
    paper = models.FileField(_("photo of the signed paper"), upload_to=consent_paper_path, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("patient consent")
        verbose_name_plural = _("patient consents")

    def __str__(self):
        return f"{self.template} — {self.patient.full_name}"

    def get_absolute_url(self):
        return reverse("prescriptions:consent", args=[self.pk])

    @property
    def is_signed(self):
        return bool(self.signature or self.paper)
