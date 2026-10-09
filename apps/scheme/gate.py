"""
Keeps a scheme student (timetable.on_scheme) to their scheme of work.

For each page they open, the address's view name and arguments say what
content it is. Then:

  - the practice tools and the Diction Library stay open to everyone
    (PRACTICE) — the library shows a school's students only their own
    school's books, plus any on their scheme in a week they've reached
    (apps/diction_library/views.visible_items / openable_items);
  - a tool's own lists and hubs (EchoSpell's levels, the Learn page, …)
    go to their weeks instead (HUBS), since the scheme is how they find
    content;
  - a piece of content opens only if it's in a week they've reached
    (timetable.open_keys); a later one gets a friendly "comes later" page;
  - every other page of a scheme tool (a library, the radio) is closed.

Everything else on the site — their account, For grown-ups, billing,
search's own page — is untouched. Teachers, admins, staff, individuals and
students without a school are never held back.
"""

from django.shortcuts import redirect, render

from .timetable import on_scheme, open_keys

# Always open: practice tools, and the parts of a scheme tool that are a
# student's own work in progress (their attempts, saving their place).
PRACTICE = {
    "clash", "quick_words", "tutor", "diction_library",
    "book:phonemic_chart", "book:read_along",
    "echospell:save_card_position", "echospell:check_vocabulary_sentences",
    "assessments:take", "assessments:save_answer", "assessments:check_answer", "assessments:result",
    "assessments:my_results",
}

# Tools whose content is reached only through the scheme.
SCHEME_TOOLS = {
    "echospell", "learning_modules", "conversational_dialogue", "book", "tricks", "reading_club",
    "assembly_recitals", "daily_practice", "assessments", "learning_tools",
    "reference_library", "diction_radio",
}

# Lists and hubs: the scheme replaces them.
HUBS = {
    "echospell:hub", "echospell:level_detail",
    "learning_modules:hub", "learning_modules:module_detail", "learning_modules:term_detail",
    "learning_modules:week_detail",
    "conversational_dialogue:hub", "conversational_dialogue:level",
    "book:home", "book:academy",
    "tricks:home", "tricks:lessons", "tricks:sections", "tricks:section",
    "reading_club:hub", "reading_club:book_detail", "reading_club:term_detail",
    "assembly_recitals:hub", "assembly_recitals:section",
    "assessments:hub", "assessments:kind_list",
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
        "conversational_dialogue:dialogue": ("dialogue", kw.get("level_slug"), kw.get("slug")),
        "conversational_dialogue:toggle_done": ("dialogue", kw.get("level_slug"), kw.get("slug")),
        "book:sound_detail": ("sound", kw.get("slug")), "book:sound_detail_tab": ("sound", kw.get("slug")),
        "book:sound_activity": ("sound", kw.get("slug")),
        "tricks:lesson": ("trick", kw.get("slug")), "tricks:lesson_tab": ("trick", kw.get("slug")),
        "tricks:activity": ("trick", kw.get("slug")),
        "reading_club:chapter_detail": ("chapter", kw.get("book_slug"), kw.get("term_slug"), kw.get("chapter_slug")),
        "reading_club:toggle_complete": ("chapter", kw.get("book_slug"), kw.get("term_slug"), kw.get("chapter_slug")),
        "assembly_recitals:recital": ("recital", kw.get("section_slug"), kw.get("recital_slug")),
        "diction_library:detail": ("library", kw.get("slug")), "diction_library:file": ("library", kw.get("slug")),
        "assessments:detail": ("assessment", kw.get("slug")), "assessments:start": ("assessment", kw.get("slug")),
        "daily_practice:home": ("daily_practice",),
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
        if tool not in SCHEME_TOOLS or tool in PRACTICE or view in PRACTICE:
            return None
        if view in HUBS:
            return redirect("scheme:weeks")
        key = _key(view, view_kwargs)
        if key and key in open_keys(request.user):
            return None
        return render(request, "scheme/not_yet.html", {"is_content": bool(key)}, status=403)
