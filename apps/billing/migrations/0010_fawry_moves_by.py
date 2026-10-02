"""Round 13: each person sees the Fawry moves they did. The moves written by themselves from a payment or a
purchase take the person who recorded that payment or purchase."""

from django.db import migrations


def fill(apps, schema_editor):
    FawryMove = apps.get_model("billing", "FawryMove")
    for move in FawryMove.objects.filter(created_by__isnull=True).select_related(
            "patient_payment", "academy_payment", "purchase"):
        source = move.patient_payment or move.academy_payment or move.purchase
        if source is not None and source.created_by_id:
            FawryMove.objects.filter(pk=move.pk).update(created_by_id=source.created_by_id)


class Migration(migrations.Migration):
    dependencies = [("billing", "0009_speed_indexes"), ("academy", "0006_places_and_machines"),
                    ("purchasing", "0005_purchase_returns")]

    operations = [migrations.RunPython(fill, migrations.RunPython.noop)]
