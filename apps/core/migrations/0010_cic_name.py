from django.db import migrations

OLD = ("CIC economical clinic", "عيادة CIC الاقتصادية")
NEW = ("Cairo Implant Center", "مركز القاهرة لزراعة الأسنان")


def rename(apps, schema_editor):
    """CIC is the Cairo Implant Center: rename it where it still has the first default name."""
    Branch = apps.get_model("core", "Branch")
    Branch.objects.filter(code="CIC", name_en=OLD[0]).update(name_en=NEW[0])
    Branch.objects.filter(code="CIC", name_ar=OLD[1]).update(name_ar=NEW[1])


def back(apps, schema_editor):
    Branch = apps.get_model("core", "Branch")
    Branch.objects.filter(code="CIC", name_en=NEW[0]).update(name_en=OLD[0])
    Branch.objects.filter(code="CIC", name_ar=NEW[1]).update(name_ar=OLD[1])


class Migration(migrations.Migration):
    dependencies = [("core", "0009_places")]
    operations = [migrations.RunPython(rename, back)]
