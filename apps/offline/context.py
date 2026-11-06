"""What every page tells the app about offline lessons (templates/base.html)."""


def offline(request):
    """`offline_levels`: for someone who can open every level, the levels
    their app keeps when none are ticked (apps/offline/catalog.py,
    worked_in). When it changes, static/js/offline_sync.js downloads them
    straight away instead of at its next twice-daily refresh. Nothing for
    everyone else: their level decides."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    from apps.accounts.access import accessible_levels

    if accessible_levels(user) is not None:
        return {}
    from .catalog import worked_in

    return {"offline_levels": ",".join(worked_in(user)) or "-"}
