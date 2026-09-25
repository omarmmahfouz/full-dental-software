"""Create dentist records for existing candidates, interns and supervisors, then
point patients, shifts, visits, treatments, lab requests and complaints at them."""

from django.db import migrations


def forwards(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    User = apps.get_model("auth", "User")
    Candidate = apps.get_model("academy", "Candidate")
    Dentist = apps.get_model("dentists", "Dentist")

    # The login role "intern" is now called "dentist".
    old = Group.objects.filter(name="intern").first()
    if old and not Group.objects.filter(name="dentist").exists():
        old.name = "dentist"
        old.save()

    def display(user):
        return f"{user.first_name} {user.last_name}".strip() or user.username

    for candidate in Candidate.objects.all():
        Dentist.objects.get_or_create(
            candidate=candidate,
            defaults={"kind": "candidate", "full_name": candidate.full_name, "phone": candidate.phone_primary,
                      "user_id": candidate.user_id},
        )
    for user in User.objects.filter(groups__name__in=["dentist", "intern"]).distinct():
        if not Dentist.objects.filter(user=user).exists():
            Dentist.objects.create(user=user, kind="training", full_name=display(user))
    for user in User.objects.filter(groups__name="supervisor").distinct():
        if not Dentist.objects.filter(user=user).exists():
            Dentist.objects.create(user=user, kind="supervisor", full_name=display(user))

    by_user = dict(Dentist.objects.exclude(user=None).values_list("user_id", "id"))

    def remap(model_name, app_label, old_field, new_field):
        Model = apps.get_model(app_label, model_name)
        for obj in Model.objects.exclude(**{f"{old_field}_id": None}).only("id", f"{old_field}_id"):
            dentist_id = by_user.get(getattr(obj, f"{old_field}_id"))
            if dentist_id:
                Model.objects.filter(pk=obj.pk).update(**{f"{new_field}_id": dentist_id})

    remap("Patient", "patients", "assigned_intern", "assigned_dentist")
    remap("RoomShift", "scheduling", "intern", "dentist")
    remap("RoomShift", "scheduling", "supervisor", "supervisor_dentist")
    remap("Appointment", "scheduling", "intern", "dentist")
    remap("TreatmentStep", "clinical", "performed_by", "operator")
    remap("TreatmentStep", "clinical", "supervised_by", "supervisor")
    remap("LabRequest", "clinical", "requested_by", "dentist")
    remap("Complaint", "complaints", "concerned_staff", "concerned_dentist")


class Migration(migrations.Migration):
    dependencies = [
        ("dentists", "0001_initial"),
        ("academy", "0002_candidate_birth_date_candidate_certificate_name_and_more"),
        ("patients", "0002_patient_assigned_dentist_patient_governorate_and_more"),
        ("scheduling", "0002_appointment_dentist_roomshift_day_type_and_more"),
        ("clinical", "0002_labrequest_dentist_treatmentstep_assistant_and_more"),
        ("complaints", "0002_complaint_concerned_dentist_and_more"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
