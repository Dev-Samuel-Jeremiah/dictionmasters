from django.apps import AppConfig


class ManageConfig(AppConfig):
    """The Diction Masters control room: a plain-English admin area for
    the people who run the platform, separate from the Django admin."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.manage"
    label = "manage"
    verbose_name = "Control room"
