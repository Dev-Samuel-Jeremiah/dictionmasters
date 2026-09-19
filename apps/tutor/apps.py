from django.apps import AppConfig


class TutorConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.tutor"
    label = "tutor"
    verbose_name = "AI Reading Tutor"
