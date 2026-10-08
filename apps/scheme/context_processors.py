from .timetable import on_scheme


def scheme(request):
    """`on_scheme` in every template: whether the signed-in student follows
    the scheme of work, so the menus offer My weeks instead of Learn. Read
    from the account alone; no query."""
    return {"on_scheme": on_scheme(getattr(request, "user", None))}
