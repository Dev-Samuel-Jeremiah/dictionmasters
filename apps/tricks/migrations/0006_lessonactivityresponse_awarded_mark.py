from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tricks", "0005_lessonactivityattempt_teacher_audio_feedback"),
    ]

    operations = [
        migrations.AddField(
            model_name="lessonactivityresponse",
            name="awarded_mark",
            field=models.PositiveSmallIntegerField(
                blank=True,
                choices=[(0, "0"), (1, "1"), (2, "2"), (3, "3"), (4, "4"), (5, "5")],
                help_text="Teacher-awarded mark for a recording, from 0 to 5.",
                null=True,
            ),
        ),
    ]
