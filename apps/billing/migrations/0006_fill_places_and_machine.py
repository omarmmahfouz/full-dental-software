from django.db import migrations
from django.db.models import OuterRef, Subquery


def fill(apps, schema_editor):
    """Bills, services given and payments made before places were recorded were at the patient's place.
    Moves through Fawry made before there were two machines were on the first one."""
    Patient = apps.get_model("patients", "Patient")
    patient_branch = Subquery(Patient.objects.filter(pk=OuterRef("patient_id")).values("branch_id")[:1])
    for name in ("Bill", "Charge", "PatientPayment"):
        apps.get_model("billing", name).objects.filter(branch__isnull=True).update(branch_id=patient_branch)
    Charge = apps.get_model("billing", "Charge")
    Bill = apps.get_model("billing", "Bill")
    bill_dentist = Subquery(Bill.objects.filter(pk=OuterRef("bill_id")).values("dentist_id")[:1])
    Charge.objects.filter(dentist__isnull=True, bill__isnull=False).update(dentist_id=bill_dentist)

    FawryMove = apps.get_model("billing", "FawryMove")
    PatientPayment = apps.get_model("billing", "PatientPayment")
    Payment = apps.get_model("academy", "Payment")
    if FawryMove.objects.exists():
        FawryMachine = apps.get_model("billing", "FawryMachine")
        first = FawryMachine.objects.order_by("sort_order", "pk").first() or FawryMachine.objects.create(
            name="Fawry 1", sort_order=1)
        FawryMove.objects.filter(machine__isnull=True).update(machine=first)
        PatientPayment.objects.filter(method="fawry", fawry_machine__isnull=True).update(fawry_machine=first)
        Payment.objects.filter(method="fawry", fawry_machine__isnull=True).update(fawry_machine=first)


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0005_places_and_machines"),
        ("academy", "0006_places_and_machines"),
        ("patients", "0006_fill_dates_and_governorate_codes"),
    ]
    operations = [migrations.RunPython(fill, migrations.RunPython.noop)]
