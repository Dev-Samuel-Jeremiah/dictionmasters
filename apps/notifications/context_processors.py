"""bell_count in every template: the bell's badge (unread updates plus
things to do), looked up only when a page shows the bell."""

from django.utils.functional import SimpleLazyObject


def bell(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {"bell_count": 0}

    def load():
        from .views import badge_count

        return badge_count(user)

    return {"bell_count": SimpleLazyObject(load)}
