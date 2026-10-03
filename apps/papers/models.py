"""Old paper files (round 13): they are read by the separate Paper Reader program (``reader/``, on a PC with the
internet), checked and approved there, and come back here as a package that is imported: every value is checked
again with the system's own forms before it is saved into a patient's file. The system itself never uses the
internet for this. Each package and each file in it is kept with what became of it."""

import uuid

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from apps.core.models import Branch, TimeStampedModel


def package_path(instance, filename):
    return f"papers/{instance.branch.code}/imports/{uuid.uuid4().hex}.zip"


# Used by the first migration only (the reading was done inside the system before it moved to the Paper Reader).
def new_token():
    return uuid.uuid4().hex


def original_path(instance, filename):
    return f"papers/{instance.branch.code}/{instance.token}/original"


def page_path(instance, filename):
    return f"papers/{instance.file.branch.code}/{instance.file.token}/page.jpg"


class PaperImport(TimeStampedModel):
    """A package from the Paper Reader, brought in at a place."""

    class Status(models.TextChoices):
        CHECKED = "checked", _("Looked at, not imported yet")
        DONE = "done", _("Imported")

    branch = models.ForeignKey(Branch, verbose_name=_("place"), on_delete=models.PROTECT, related_name="paper_imports")
    name = models.CharField(_("file name"), max_length=255)
    package = models.FileField(_("package"), upload_to=package_path, blank=True,
                               help_text="Kept until it is imported; the documents then live in the patients' files.")
    manifest = models.JSONField(_("contents"), default=dict)
    status = models.CharField(_("status"), max_length=10, choices=Status.choices, default=Status.CHECKED)
    imported_at = models.DateTimeField(_("imported at"), null=True, blank=True)
    imported_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_("imported by"), null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-created_at", "-pk"]
        verbose_name = _("paper files package")
        verbose_name_plural = _("paper files packages")

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("papers:import_detail", args=[self.pk])

    @property
    def files(self):
        return self.manifest.get("files", [])

    def drop_package(self):
        if self.package:
            name = self.package.name
            self.package = ""
            type(self).objects.filter(pk=self.pk).update(package="")
            if name and self.package.storage.exists(name):
                self.package.storage.delete(name)


class ImportedFile(models.Model):
    """One paper file of a package, and what became of it. A file is imported once only (by its token)."""

    class Status(models.TextChoices):
        IMPORTED = "imported", _("Saved into the patient's file")
        FAILED = "failed", _("Not imported")
        SKIPPED = "skipped", _("Already imported before")

    paper_import = models.ForeignKey(PaperImport, on_delete=models.CASCADE, related_name="results")
    token = models.CharField(max_length=32, db_index=True)
    name = models.CharField(_("file name"), max_length=255)
    status = models.CharField(_("status"), max_length=10, choices=Status.choices)
    patient = models.ForeignKey("patients.Patient", verbose_name=_("patient"), null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="paper_imports")
    new_patient = models.BooleanField(_("new file"), default=False)
    message = models.TextField(_("what happened"), blank=True)
    change = models.ForeignKey("core.ChangeRequest", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    at = models.DateTimeField(_("at"), auto_now_add=True)

    class Meta:
        ordering = ["paper_import", "pk"]
        verbose_name = _("imported paper file")
        verbose_name_plural = _("imported paper files")
        constraints = [models.UniqueConstraint(fields=["token"], condition=models.Q(status="imported"),
                                               name="paper_file_imported_once")]

    def __str__(self):
        return self.name
