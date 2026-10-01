from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0007_additional_levels"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="encrypted_login_password",
            field=models.TextField(blank=True, default="", editable=False),
        ),
    ]
