# Generated for the Quick Words ZIP audio importer.
import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("quick_words", "0004_quickword_synonyms"),
    ]

    operations = [
        migrations.CreateModel(
            name="QuickWordAudioImportJob",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("archive", models.FileField(upload_to="quick-words/import-zips/%Y/%m/")),
                ("status", models.CharField(choices=[("queued", "Queued"), ("running", "Running"), ("complete", "Complete"), ("failed", "Failed")], default="queued", max_length=10)),
                ("total_files", models.PositiveIntegerField(default=0)),
                ("completed_files", models.PositiveIntegerField(default=0)),
                ("created_words", models.PositiveIntegerField(default=0)),
                ("updated_words", models.PositiveIntegerField(default=0)),
                ("skipped_files", models.PositiveIntegerField(default=0)),
                ("failed_files", models.PositiveIntegerField(default=0)),
                ("results", models.JSONField(blank=True, default=list)),
                ("error", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("uploaded_by", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="quick_word_audio_imports", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"]},
        ),
    ]
