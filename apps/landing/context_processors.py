from django.utils.functional import SimpleLazyObject


def branding(request):
    """`branding` in every template: the uploaded logo and favicon.
    Looked up only on pages that actually use it."""

    def load():
        from .models import SiteBranding
        return SiteBranding.load()

    return {"branding": SimpleLazyObject(load)}
