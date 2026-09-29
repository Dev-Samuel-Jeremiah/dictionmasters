from django.apps import AppConfig


class DictionLibraryConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.diction_library"
    label = "diction_library"
    verbose_name = "Diction Library"

    def ready(self):
        # A book or story saved: make its read-aloud (narration.py).
        from django.db.models.signals import post_save

        from . import narration
        from .models import LibraryItem

        post_save.connect(narration.when_saved, sender=LibraryItem, dispatch_uid="dm-library-narration")
