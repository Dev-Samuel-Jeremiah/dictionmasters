"""The 44 Academy is for Primary 3 and up (content Level 3 to Level 12):
Pre-School, Primary 1 and Primary 2 pupils don't see it. A school that
already set the 44 Academy's levels in the control room keeps its choice.
Staff change it any time under What students see."""

from django.db import migrations

FROM_PRIMARY_3 = "," + ",".join(f"Level {n}" for n in range(3, 13)) + ","


def forwards(apps, schema_editor):
    ToolLevels = apps.get_model("learning_tools", "ToolLevels")
    ToolLevels.objects.get_or_create(tool="book:home", defaults={"levels": FROM_PRIMARY_3})


def backwards(apps, schema_editor):
    ToolLevels = apps.get_model("learning_tools", "ToolLevels")
    ToolLevels.objects.filter(tool="book:home", levels=FROM_PRIMARY_3).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("learning_tools", "0002_toollevels"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
