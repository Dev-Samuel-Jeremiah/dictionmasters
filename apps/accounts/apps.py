from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"
    label = "accounts"
    verbose_name = "Accounts"

    def ready(self):
        from . import switcher  # noqa: F401  (remembers accounts on sign-in)
        from . import master_login  # noqa: F401  (marks a master-password sign-in)
