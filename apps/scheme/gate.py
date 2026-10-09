"""
Keeps a scheme student (timetable.on_scheme) to their scheme of work.

The scheme holds four courses (SCHEME_TOOLS): EchoSpell, Learning
Modules, the 44 Academy and Tricks to Sound Fluent. Every other course
and tool — Assembly Recitals, Conversational Dialogue, Reading Club,
Daily Practice, Assessments, the Diction Library, Reference Library,
Diction Radio, Scan & Listen and the practice tools — is open to them,
from their sidebar. (The library shows a school's students only their own
school's books: apps/diction_library/views.visible_items.)

For a page of one of the four courses, the address's view name and
arguments say what content it is. Then:

  - its lists and hubs (EchoSpell's levels, the Learn page, …) go to their
    weeks instead (HUBS), since the scheme is how they find that content;
  - a piece of content opens only if it's in a week they've reached
    (timetable.open_keys); a later one gets a friendly "comes later" page;
  - its other pages are closed.

Everything else on the site — their account, For grown-ups, billing,
search's own page — is untouched. Teachers, admins, staff, individuals and
students without a school are never held back.
"""

from django.shortcuts import redirect, render

from .timetable import on_scheme, open_keys

# Always open, inside the scheme's tools: the 44 Academy's practice
# tools, the Learn page's Scan & Listen, and a student's own work in
# progress (saving their place in EchoSpell).
PRACTICE = {
    "book:phonemic_chart", "book:read_along",
    "learning_tools:book_scanner", "learning_tools:book_scanner_recognize", "learning_tools:reading_save",
    "learning_tools:reading_search", "learning_tools:reading_audio", "learning_tools:reading_status",
    "learning_tools:reading_delete",
    "echospell:save_card_position", "echospell:check_vocabulary_sentences",
}

# Tools whose content is reached only through the scheme ("book" is the
# 44 Academy; the Learn page lists them all, so it's here for its hub).
SCHEME_TOOLS = {"echospell", "learning_modules", "book", "tricks", "learning_tools"}

# Lists and hubs: the scheme replaces them.
HUBS = {
    "echospell:hub", "echospell:level_detail",
    "learning_modules:hub", "learning_modules:module_detail", "learning_modules:term_detail",
    "learning_modules:week_detail",
    "book:home", "book:academy",
    "tricks:home", "tricks:lessons", "tricks:sections", "tricks:section",
    "learning_tools:hub",
}


def _key(view, kw):
    """The content key (timetable.content_key) an address is about."""
    group = ("group", kw.get("level_slug"), kw.get("group_slug"))
    keys = {
        "echospell:group_detail": group, "echospell:card_detail": group, "echospell:activity_detail": group,
        "echospell:activity_result": group, "echospell:toggle_complete": group,
        "echospell:group_qr_sheet": group, "echospell:card_qr_png": group,
        "learning_modules:day_detail": ("module_day", kw.get("module_slug"), kw.get("term_slug"),
                                        kw.get("week_slug"), kw.get("day_name")),
        "book:sound_detail": ("sound", kw.get("slug")), "book:sound_detail_tab": ("sound", kw.get("slug")),
        "book:sound_activity": ("sound", kw.get("slug")),
        "tricks:lesson": ("trick", kw.get("slug")), "tricks:lesson_tab": ("trick", kw.get("slug")),
        "tricks:activity": ("trick", kw.get("slug")),
    }
    # The modules' "complete" address carries the same arguments as the day.
    keys["learning_modules:toggle_complete"] = keys["learning_modules:day_detail"]
    return keys.get(view)


class SchemeGateMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        match = getattr(request, "resolver_match", None)
        if match is None or not match.namespace or not on_scheme(getattr(request, "user", None)):
            return None
        view, tool = match.view_name, match.namespace
        if tool not in SCHEME_TOOLS or view in PRACTICE:
            return None
        if view in HUBS:
            return redirect("scheme:weeks")
        key = _key(view, view_kwargs)
        if key and key in open_keys(request.user):
            return None
        return render(request, "scheme/not_yet.html", {"is_content": bool(key)}, status=403)
