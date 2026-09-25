"""Existing records: the file-opening and first-call dates come from when they were typed in,
and governorates written as text (Arabic or English) become the governorate codes; text that is
not a governorate moves to "city / area"."""

from django.db import migrations
from django.utils import timezone, translation


def forwards(apps, schema_editor):
    from apps.core.utils import EGYPT_GOVERNORATES

    Patient = apps.get_model("patients", "Patient")
    Lead = apps.get_model("patients", "Lead")
    names = {}
    for code, label in EGYPT_GOVERNORATES.items():
        for language in ("en", "ar"):
            with translation.override(language):
                names[str(label).strip().lower()] = code
    names["born abroad"] = names["مولود بالخارج"] = "88"
    for patient in Patient.objects.all().only("pk", "created_at", "governorate", "city"):
        values = {"registered_on": timezone.localtime(patient.created_at).date()}
        if patient.governorate and patient.governorate not in EGYPT_GOVERNORATES:
            code = names.get(patient.governorate.strip().lower(), "")
            values["governorate"] = code
            if not code:  # keep what was written
                values["city"] = f"{patient.governorate} {patient.city}".strip()[:100]
        Patient.objects.filter(pk=patient.pk).update(**values)
    for lead in Lead.objects.all().only("pk", "created_at"):
        Lead.objects.filter(pk=lead.pk).update(first_call_on=timezone.localtime(lead.created_at).date())


class Migration(migrations.Migration):
    dependencies = [("patients", "0005_out_dates_governorates_documents")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
