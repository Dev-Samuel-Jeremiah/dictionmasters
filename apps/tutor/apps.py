import threading

from django.apps import AppConfig
from django.conf import settings


def _warm():
    """Open the connection to the transcriber before anyone needs it.

    The first call from a fresh worker spends over a second setting up the
    connection; every one after reuses it in well under half. A learner
    should never be the one waiting for that."""
    try:
        from apps.book.read_along import OPENAI_URL, _http

        if _http is not None:
            _http.request("GET", "https://api.openai.com/v1/models", retries=False, timeout=8)
    except Exception:
        pass       # it will simply be set up on the first reading instead


class TutorConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.tutor"
    label = "tutor"
    verbose_name = "AI Reading Tutor"

    def ready(self):
        if getattr(settings, "TESTING", False) or not getattr(settings, "OPENAI_API_KEY", ""):
            return
        threading.Thread(target=_warm, name="tutor-warm", daemon=True).start()
