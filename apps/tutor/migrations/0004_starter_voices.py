"""The voices a learner can choose from to begin with. An admin can add
more, rename them or turn them off in the control room."""

from django.db import migrations

STARTERS = [
    ("Yela", "female", "yela", "Warm and steady — the voice of Diction Masters.", True, 1),
    ("Ada", "female", "ada", "Bright and clear, a little quicker.", False, 2),
    ("Nia", "female", "nia", "Gentle and patient, good for a first reading.", False, 3),
    ("Kayode", "male", "kayode", "Calm and even, with a low warmth.", False, 4),
    ("Tobi", "male", "tobi", "Friendly and encouraging.", False, 5),
]


def add_voices(apps, schema_editor):
    TutorVoice = apps.get_model("tutor", "TutorVoice")
    if TutorVoice.objects.exists():
        return
    for name, gender, avatar, description, default, order in STARTERS:
        TutorVoice.objects.create(
            name=name, gender=gender, avatar=avatar, description=description,
            # Blank means the site's own ElevenLabs voice. An admin pastes
            # a voice id here to give each one a voice of its own.
            voice_id="", is_default=default, order=order,
        )


def remove_voices(apps, schema_editor):
    apps.get_model("tutor", "TutorVoice").objects.filter(name__in=[s[0] for s in STARTERS]).delete()


class Migration(migrations.Migration):

    dependencies = [("tutor", "0003_voices_and_faces")]

    operations = [migrations.RunPython(add_voices, remove_voices)]
