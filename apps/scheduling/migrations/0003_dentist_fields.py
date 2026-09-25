from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("scheduling", "0002_appointment_dentist_roomshift_day_type_and_more"),
        ("dentists", "0002_move_people_to_dentists"),
    ]

    operations = [
        migrations.RemoveField(model_name="roomshift", name="intern"),
        migrations.RemoveField(model_name="roomshift", name="supervisor"),
        migrations.RenameField(model_name="roomshift", old_name="supervisor_dentist", new_name="supervisor"),
        migrations.RemoveField(model_name="appointment", name="intern"),
    ]
