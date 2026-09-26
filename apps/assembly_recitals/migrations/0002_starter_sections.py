"""The four sections Assembly Recitals starts with, and the first recitals."""

from django.db import migrations

SECTIONS = [
    ("Days & Months", "days-months", "📅", "The days of the week and the months of the year, said together.", [
        ("Days of the Week", "days-of-the-week", "Seven days, said clearly and in order.",
         "Monday\nTuesday\nWednesday\nThursday\nFriday\n\nSaturday\nSunday"),
        ("Months of the Year", "months-of-the-year", "Twelve months, with every syllable heard.",
         "January\nFebruary\nMarch\n\nApril\nMay\nJune\n\nJuly\nAugust\nSeptember\n\nOctober\nNovember\nDecember"),
    ]),
    ("Numerals", "numerals", "🔢", "Counting aloud, from one to twenty and beyond.", [
        ("Numbers 1–20", "numbers-1-20", "Count from one to twenty, crisp and clear.",
         "One, two, three, four, five\nSix, seven, eight, nine, ten\n\n"
         "Eleven, twelve, thirteen, fourteen, fifteen\nSixteen, seventeen, eighteen, nineteen, twenty"),
    ]),
    ("Songs", "songs", "🎵", "Diction songs to sing together.", []),
    ("Miscellaneous", "miscellaneous", "✨", "Pledges, poems and anything else the hall says together.", []),
]


def add(apps, schema_editor):
    Section = apps.get_model("assembly_recitals", "Section")
    Recital = apps.get_model("assembly_recitals", "Recital")
    for order, (name, slug, icon, description, recitals) in enumerate(SECTIONS):
        section, _made = Section.objects.get_or_create(
            slug=slug, defaults={"name": name, "icon": icon, "description": description, "order": order},
        )
        for r_order, (title, r_slug, summary, lines) in enumerate(recitals):
            Recital.objects.get_or_create(
                section=section, slug=r_slug,
                defaults={"title": title, "summary": summary, "lines": lines, "order": r_order},
            )


def remove(apps, schema_editor):
    Section = apps.get_model("assembly_recitals", "Section")
    Section.objects.filter(slug__in=[s[1] for s in SECTIONS]).delete()


class Migration(migrations.Migration):
    dependencies = [("assembly_recitals", "0001_initial")]
    operations = [migrations.RunPython(add, remove)]
