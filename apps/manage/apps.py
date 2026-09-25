from django.apps import AppConfig


class ManageConfig(AppConfig):
    """The Diction Masters control room: a plain-English admin area for
    the people who run the platform, separate from the Django admin."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.manage"
    label = "manage"
    verbose_name = "Control room"

    def ready(self):
        # Use the shared editor for learner-facing Django Admin text fields.
        # Structured fields remain plain through the widget's field allow-list.
        from django.contrib.admin.options import FORMFIELD_FOR_DBFIELD_DEFAULTS
        from django.db import models

        from apps.manage.rich_text import RichTextWidget

        FORMFIELD_FOR_DBFIELD_DEFAULTS.setdefault(models.TextField, {})["widget"] = RichTextWidget
