"""Track IPA source and review state on saved Quick Words."""

import django.utils.timezone
from django.db import migrations, models


def mark_existing_pronunciations_unverified(apps, schema_editor):
    QuickWord = apps.get_model("quick_words", "QuickWord")
    QuickWord.objects.exclude(ipa="").update(
        ipa_source="database",
        ipa_confidence="unknown",
        ipa_review_required=True,
    )
    QuickWord.objects.filter(ipa="").update(ipa_review_required=True)


class Migration(migrations.Migration):
    dependencies = [
        ("quick_words", "0005_quickwordaudioimportjob"),
    ]

    operations = [
        migrations.AlterField(
            model_name="quickword",
            name="ipa",
            field=models.CharField(
                blank=True,
                help_text='British English phonemic transcription, e.g. "/əˈtʃiːv/"',
                max_length=500,
                verbose_name="transcription",
            ),
        ),
        migrations.AddField(
            model_name="quickword",
            name="ipa_accent",
            field=models.CharField(db_index=True, default="en-GB", max_length=20),
        ),
        migrations.AddField(
            model_name="quickword",
            name="ipa_confidence",
            field=models.CharField(
                blank=True,
                choices=[
                    ("", "Not recorded"),
                    ("dictionary", "Dictionary"),
                    ("verified", "Manually verified"),
                    ("ai", "AI generated"),
                    ("unknown", "Unknown / legacy"),
                ],
                help_text="AI-generated IPA must remain marked for review.",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="quickword",
            name="ipa_review_required",
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.AddField(
            model_name="quickword",
            name="ipa_source",
            field=models.CharField(
                blank=True,
                choices=[
                    ("", "Not recorded"),
                    ("britfone", "Britfone"),
                    ("ipa_dict", "IPA-Dict UK"),
                    ("database", "Database / manually entered"),
                    ("openai", "OpenAI generated"),
                ],
                help_text="Source for the saved pronunciation.",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="quickword",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="quickword",
            name="updated_at",
            field=models.DateTimeField(auto_now=True, default=django.utils.timezone.now),
            preserve_default=False,
        ),
        migrations.RunPython(mark_existing_pronunciations_unverified, migrations.RunPython.noop),
    ]
