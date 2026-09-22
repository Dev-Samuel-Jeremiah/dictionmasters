"""The assessment models now serve 44 Academy's sounds as well as the
tricks: renamed from Trick… to Lesson…, with nothing moved or lost."""

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("book", "0009_tricks_without_groups"),
        ("tricks", "0002_trick_activities"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveConstraint(model_name="trickprogress", name="one_progress_per_trick"),
        migrations.RenameModel("TrickProgress", "LessonProgress"),
        migrations.RenameField("lessonprogress", "trick", "lesson"),
        migrations.AddConstraint(
            model_name="lessonprogress",
            constraint=models.UniqueConstraint(fields=["user", "lesson"], name="one_progress_per_lesson"),
        ),
        migrations.RenameModel("TrickActivity", "LessonActivity"),
        migrations.AlterUniqueTogether(name="lessonactivity", unique_together=set()),
        migrations.RenameField("lessonactivity", "trick", "lesson"),
        migrations.AlterUniqueTogether(name="lessonactivity", unique_together={("lesson", "slug")}),
        migrations.RenameModel("TrickActivityItem", "LessonActivityItem"),
        migrations.RenameModel("TrickActivityAttempt", "LessonActivityAttempt"),
        migrations.RenameModel("TrickActivityResponse", "LessonActivityResponse"),
    ]
