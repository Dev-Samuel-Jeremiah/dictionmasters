"""Activities now belong to a group rather than to a level.

The level is reached through the group, so the two can no longer
disagree. Every existing activity already had a group set, so the
nullable-to-required change needs no data fixing.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("echospell", "0010_activity_activityattempt_activityitem_and_more"),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name="activity",
            unique_together=set(),
        ),
        migrations.AlterField(
            model_name="activity",
            name="group",
            field=models.ForeignKey(
                help_text="The group this exercise belongs to.",
                on_delete=django.db.models.deletion.CASCADE,
                related_name="activities",
                to="echospell.group",
            ),
        ),
        migrations.RemoveField(
            model_name="activity",
            name="level",
        ),
        migrations.AlterModelOptions(
            name="activity",
            options={"ordering": ["group", "order", "id"], "verbose_name_plural": "Activities"},
        ),
        migrations.AlterUniqueTogether(
            name="activity",
            unique_together={("group", "slug")},
        ),
    ]
