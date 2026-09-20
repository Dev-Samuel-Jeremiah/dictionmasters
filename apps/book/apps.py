from django.apps import AppConfig


class BookConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.book"
    label = "book"
    verbose_name = "44 Academy"

    def ready(self):
        # Video thumbnails, for every model that holds a video.
        from . import signals

        signals.connect()
