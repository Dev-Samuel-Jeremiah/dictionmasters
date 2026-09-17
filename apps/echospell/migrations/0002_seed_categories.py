from django.db import migrations

CATEGORIES = [
    dict(name="Spelling", slug="spelling", kind="words", icon="✍️", color="#14213D", order=1,
         description="Hear the word, see its transcription, then spell it."),
    dict(name="Passage Reading", slug="passage-reading", kind="passage", icon="📖", color="#B8863B", order=2,
         description="A passage built from this group's words — read along with the audio."),
    dict(name="Dialogue", slug="dialogue", kind="dialogue", icon="💬", color="#7A2438", order=3,
         description="A conversation using this group's words, line by line."),
    dict(name="Vocabulary", slug="vocabulary", kind="words", icon="🧠", color="#24473E", order=4,
         description="The meaning of each word, with an example sentence."),
    dict(name="Transcription", slug="transcription", kind="words", icon="🔤", color="#7C3AED", order=5,
         description="See and hear the phonemic transcription for each word."),
    dict(name="Missing Letter", slug="missing-letter", kind="words", icon="🔍", color="#C2410C", order=6,
         description="Spot the missing letters in each word."),
    dict(name="Listen and Circle", slug="listen-and-circle", kind="words", icon="🎯", color="#0B5E5E", order=7,
         description="Listen, then pick the word you heard."),
    dict(name="Look, Listen & Echo", slug="look-listen-echo", kind="words", icon="🗣️", color="#1F6F8B", order=8,
         description="Look at the word, listen, then say it back."),
    dict(name="Listen and Number", slug="listen-and-number", kind="words", icon="🧮", color="#374151", order=9,
         description="Listen to the words in order and number them."),
    dict(name="Puzzle", slug="puzzle", kind="words", icon="🧩", color="#8E44AD", order=10,
         description="Unscramble each word."),
]


def seed_categories(apps, schema_editor):
    Category = apps.get_model("echospell", "Category")
    for fields in CATEGORIES:
        Category.objects.get_or_create(slug=fields["slug"], defaults=fields)


def remove_categories(apps, schema_editor):
    Category = apps.get_model("echospell", "Category")
    Category.objects.filter(slug__in=[c["slug"] for c in CATEGORIES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("echospell", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_categories, remove_categories),
    ]
