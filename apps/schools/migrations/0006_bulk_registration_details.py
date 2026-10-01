from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("schools", "0005_trial_reason"),
    ]

    operations = [
        migrations.AlterField(
            model_name="school",
            name="email",
            field=models.EmailField(blank=True, max_length=254),
        ),
        migrations.AlterField(
            model_name="school",
            name="phone",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="school",
            name="contact_person",
            field=models.CharField(blank=True, default="", max_length=255, verbose_name="Contact person"),
        ),
        migrations.AddField(
            model_name="school",
            name="relationship_status",
            field=models.CharField(blank=True, default="", max_length=30, verbose_name="Status"),
        ),
    ]
