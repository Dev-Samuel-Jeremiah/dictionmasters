"""Every level, and a first dialogue to show how one looks."""

from django.db import migrations
from django.utils.text import slugify

LEVELS = ["Pre-Level"] + [f"Level {i}" for i in range(1, 13)]

ANIMALS_SCRIPT = """Child: Mummy, is that a lion?
Mummy: No, that's a gorilla.
Child: Is that a tortoise?
Mummy: Yes, that's a tortoise. It walks very slowly.
Child: Look! What is that tall animal?
Mummy: That's a giraffe. It has a very long neck."""


def add(apps, schema_editor):
    Level = apps.get_model("conversational_dialogue", "DialogueLevel")
    Dialogue = apps.get_model("conversational_dialogue", "Dialogue")
    for order, name in enumerate(LEVELS):
        Level.objects.get_or_create(name=name, defaults={"slug": slugify(name), "order": order})
    pre = Level.objects.get(name="Pre-Level")
    Dialogue.objects.get_or_create(
        level=pre, slug="t1-w1-monday-animals",
        defaults={
            "term": 1, "week": 1, "day": "monday", "day_order": 0, "title": "Animals",
            "target_words": "lion, gorilla, tortoise, giraffe",
            "script": ANIMALS_SCRIPT,
            "notes": "<p>Split the class into Child and Mummy, then swap roles.</p>",
        },
    )


def remove(apps, schema_editor):
    apps.get_model("conversational_dialogue", "DialogueLevel").objects.filter(name__in=LEVELS).delete()


class Migration(migrations.Migration):
    dependencies = [("conversational_dialogue", "0001_initial")]
    operations = [migrations.RunPython(add, remove)]
