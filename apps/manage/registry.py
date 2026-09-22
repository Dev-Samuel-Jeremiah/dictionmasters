"""
Every screen in the control room, in one list.

Each entry describes one kind of thing an admin works with: where it
lives, what the list shows, what can be searched, and which things belong
inside it. Add a line here and the screen exists — list, add, edit,
delete and uploads all follow from it.

    key        the name used in the address bar
    model      "app_label.ModelName"
    columns    what the list shows
    search     fields the search box looks through
    order      default sort
    form       fields on the add/edit form (None = everything editable)
    parent     (field on this model, key of its parent) so "Groups" can
               be opened inside one Level
    children   keys of the things that live inside this one
    readonly   records the site writes itself: viewable, not editable
    where      only the records matching this filter belong to the screen
               (44 Academy and Tricks to Sound Fluent share their tables)
    defaults   set on every record added here ("book.tricks_group" = the
               hidden group every trick is filed in)
    limit      {field: filter} narrows a dropdown's choices
    labels     {field: (label, help)} to word a form's fields for this screen
    name, singular   what to call the records, when the model's own words don't fit
    view             a results source ("assessment", "echospell", "lesson"): each
                     row opens that attempt in Results & marking
    kind_fields      "activity" or "item": show only the fields the activity type
                     needs (apps/manage/kind_fields.py)
"""


def lesson_screens(programme, prefix):
    """The screens for one programme's lessons: its groups, its lessons,
    and everything on a lesson's eight tabs. 44 Academy and Tricks to
    Sound Fluent each get a set, over the same tables, each seeing only
    its own records. `prefix` keeps their addresses apart."""
    lesson = {"category__programme": programme}
    inside = {"sound__category__programme": programme}

    def tab(key, model, columns, search, **extra):
        screen = {"key": prefix + key, "model": model, "columns": columns, "search": search,
                  "parent": ("sound", prefix + "sounds"), "where": inside,
                  "limit": {"sound": lesson}, **extra}
        if programme == "tricks":
            screen["labels"] = {"sound": ("Trick", "")}
        return screen

    tabs = [prefix + key for key in ("articulation", "tab-videos", "word-bank", "sentences",
                                     "book-passages", "conversations", "twisters", "minimal-pairs", "links")]
    if programme == "tricks":
        # Tricks have no groups: just Trick 1, Trick 2, … Each is filed in
        # the one group the site keeps for them, out of sight.
        first = [
            {"key": prefix + "sounds", "model": "book.Sound", "name": "Tricks", "singular": "trick",
             "columns": ["order", "name", "symbol", "is_published"], "order": ["order", "name"],
             "search": ["name", "symbol", "example_words"], "where": lesson,
             "defaults": {"category": "book.tricks_group"},
             "form": ["name", "order", "symbol", "example_words", "is_published"],
             "labels": {"name": ("Name", 'e.g. "-age Ending"'),
                        "order": ("Trick number", "Its place in the list: 1 is Trick 1. Leave at 0 to add it at the end."),
                        "symbol": ("Badge", 'Optional, e.g. "-age".'),
                        "is_published": ("Published", "Unpublished tricks are hidden from learners.")},
             "children": [*tabs, "trick-activities"]},
        ]
    else:
        first = [
            {"key": prefix + "sound-groups", "model": "book.SoundCategory",
             "columns": ["name", "order"], "search": ["name"], "children": [prefix + "sounds"],
             "where": {"programme": programme}, "defaults": {"programme": programme},
             "form": ["name", "order"]},
            {"key": prefix + "sounds", "model": "book.Sound",
             "columns": ["symbol", "name", "category", "order", "is_published"],
             "search": ["name", "symbol", "example_words"],
             "parent": ("category", prefix + "sound-groups"),
             "where": lesson, "limit": {"category": {"programme": programme}},
             "children": [*tabs, "sound-activities"]},
        ]

    return [
        *first,
        tab("tab-videos", "book.SectionVideo", ["video_caption", "section", "sound", "order"],
            ["video_caption", "sound__name"], order=["sound", "section", "order"],
            # Where it goes first, then the video itself.
            form=["sound", "section", "order", "video_caption", "video_file", "video_url",
                  "video_duration_label", "video_poster"]),
        tab("articulation", "book.Articulation", ["sound", "video_caption"], ["trap_text", "mouth_position_text"],
            name="Trick tab" if prefix else None),
        tab("word-bank", "book.WordBankEntry", ["word", "sound", "spelling_pattern", "order"], ["word"]),
        tab("sentences", "book.SentencePractice", ["sentence", "sound", "order"], ["sentence"]),
        tab("book-passages", "book.Passage", ["title", "sound", "order"], ["title", "body"]),
        tab("conversations", "book.Conversation", ["title", "sound", "order"], ["title", "script"]),
        tab("twisters", "book.TongueTwister", ["text", "sound", "order"], ["text"]),
        tab("minimal-pairs", "book.MinimalPair", ["word_a", "word_b", "sound", "order"], ["word_a", "word_b"]),
        tab("links", "book.ExternalLink", ["title", "sound", "url", "order"], ["title", "url"]),
        *(assessment_screens("tricks", "trick-sounds", "trick", "trick") if programme == "tricks"
          else assessment_screens(programme, prefix + "sounds", "sound", "sound")),
    ]


def assessment_screens(programme, lessons_key, key_prefix, lesson_word):
    """A lesson's assessment — a 44 Academy sound's or a trick's:
    activities of any EchoSpell type, each with its questions. Passing
    them all unlocks the next lesson (apps/tricks/progress.py). Each
    programme sees only its own."""
    of_programme = {"lesson__category__programme": programme}
    return [
        {"key": f"{key_prefix}-activities", "model": "tricks.LessonActivity", "name": "Assessment activities",
         "singular": "assessment activity",
         "columns": ["title", "lesson", "kind", "pass_mark", "is_published"],
         "order": ["lesson__category__order", "lesson__order", "order", "id"], "search": ["title", "lesson__name"],
         "parent": ("lesson", lessons_key), "children": [f"{key_prefix}-activity-items"],
         "where": of_programme, "limit": {"lesson": {"category__programme": programme}},
         "form": ["lesson", "kind", "title", "instructions", "buckets", "pass_mark", "order", "is_published"],
         "kind_fields": "activity",
         "labels": {"lesson": (lesson_word.capitalize(), f"The {lesson_word} this activity tests. Passing all of a "
                                                         f"{lesson_word}'s activities unlocks the next one."),
                    "kind": ("Activity type", "The same types as EchoSpell activities: what the learner does, "
                                              "and how it is marked."),
                    "pass_mark": ("Pass mark (%)", "The score needed to pass. Recorded activities count once sent.")}},
        {"key": f"{key_prefix}-activity-items", "model": "tricks.LessonActivityItem", "name": "Activity questions",
         "singular": "question",
         "columns": ["__str__", "activity", "order"], "order": ["activity", "order"],
         "search": ["prompt", "answer"], "parent": ("activity", f"{key_prefix}-activities"),
         "where": {f"activity__{k}": v for k, v in of_programme.items()},
         "limit": {"activity": of_programme},
         "form": ["activity", "order", "prompt", "answer", "options", "hint", "audio_file", "audio_url", "image"],
         "kind_fields": "item"},
        {"key": f"{key_prefix}-activity-attempts", "model": "tricks.LessonActivityAttempt", "name": "Activity results",
         "columns": ["user", "activity", "percent", "status", "created_at"],
         "search": ["user__email", "activity__title"], "readonly": True, "view": "lesson",
         "where": {f"activity__{k}": v for k, v in of_programme.items()}},
    ]


SECTIONS = [
    {
        "slug": "echospell", "name": "EchoSpell", "icon": "🔊", "tone": "#2e7d62",
        "blurb": "Levels, groups, card lessons and scored activities.",
        "screens": [
            {"key": "levels", "model": "echospell.Level",
             "columns": ["name", "age_range", "order", "is_published"],
             "search": ["name", "description"], "order": ["order", "name"],
             "children": ["groups"]},
            {"key": "groups", "model": "echospell.Group",
             "columns": ["display_name", "level", "number"],
             "search": ["title"], "order": ["level", "number"],
             "parent": ("level", "levels"),
             "children": ["card-lessons", "passages", "dialogues", "activities"]},
            {"key": "card-types", "model": "echospell.Category",
             "columns": ["name", "kind", "icon", "order"],
             "search": ["name", "description"], "order": ["order", "name"]},
            {"key": "card-lessons", "model": "echospell.CardLesson",
             "columns": ["__str__", "group", "category", "order", "is_published"],
             "search": ["title", "word"], "order": ["group", "order"],
             "parent": ("group", "groups")},
            {"key": "passages", "model": "echospell.Passage",
             "columns": ["__str__", "group"], "search": ["title", "body"],
             "parent": ("group", "groups")},
            {"key": "dialogues", "model": "echospell.Dialogue",
             "columns": ["__str__", "group"], "search": ["title"],
             "parent": ("group", "groups"), "children": ["dialogue-lines"]},
            {"key": "dialogue-lines", "model": "echospell.DialogueLine",
             "columns": ["speaker", "text", "dialogue", "order"], "search": ["speaker", "text"],
             "order": ["order"], "parent": ("dialogue", "dialogues")},
            {"key": "activities", "model": "echospell.Activity",
             "columns": ["title", "group", "kind", "pass_mark", "is_published"],
             "search": ["title", "instructions"], "order": ["group", "order"],
             "parent": ("group", "groups"), "children": ["activity-items"]},
            {"key": "activity-items", "model": "echospell.ActivityItem",
             "columns": ["__str__", "activity", "order"], "search": ["prompt", "answer"],
             "order": ["order"], "parent": ("activity", "activities")},
            {"key": "activity-attempts", "model": "echospell.ActivityAttempt",
             "columns": ["user", "activity", "percent", "status", "created_at"],
             "search": ["user__email", "activity__title"], "readonly": True, "view": "echospell"},
        ],
    },
    {
        "slug": "learning-modules", "name": "Learning Modules", "icon": "🎓", "tone": "#2f5d8a",
        "blurb": "Term-by-term courses: modules, terms, weeks, days and lessons.",
        "screens": [
            {"key": "modules", "model": "learning_modules.LearningModule",
             "columns": ["name", "icon", "order", "is_published"],
             "search": ["name", "description"], "children": ["module-terms"]},
            {"key": "module-terms", "model": "learning_modules.Term",
             "columns": ["name", "module", "order"], "search": ["name"],
             "parent": ("module", "modules"), "children": ["weeks"]},
            {"key": "weeks", "model": "learning_modules.Week",
             "columns": ["display_name", "term", "number"], "search": ["title"],
             "parent": ("term", "module-terms"), "children": ["days"]},
            {"key": "days", "model": "learning_modules.Day",
             "columns": ["__str__", "week", "day_name", "is_published"], "search": [],
             "parent": ("week", "weeks"), "children": ["lesson-items"]},
            {"key": "lesson-items", "model": "learning_modules.LessonItem",
             "columns": ["title", "day", "kind", "order", "is_published"],
             "search": ["title", "description", "body"],
             "parent": ("day", "days"), "children": ["lesson-resources"]},
            {"key": "lesson-resources", "model": "learning_modules.LessonResource",
             "columns": ["title", "lesson_item", "order"], "search": ["title"],
             "parent": ("lesson_item", "lesson-items")},
        ],
    },
    {
        "slug": "book", "name": "44 Academy", "icon": "📖", "tone": "#7A2438",
        "blurb": "The 44 Academy sounds, their lessons, and the phonemic chart audio.",
        "screens": [
            *lesson_screens("academy", ""),
            {"key": "chart-audio", "model": "book.PhonemeAudio",
             "columns": ["key", "symbol", "source", "spoken_text", "updated_at"],
             "search": ["key", "symbol", "spoken_text"]},
        ],
    },
    {
        "slug": "tricks", "name": "Tricks to Sound Fluent", "icon": "✨", "tone": "#b8863b",
        "blurb": "The tricks, their groups, and everything on each trick's eight tabs.",
        "screens": lesson_screens("tricks", "trick-"),
    },
    {
        "slug": "tutor", "name": "AI Reading Tutor", "icon": "🎙️", "tone": "#1f6f5c",
        "blurb": "Passages learners read aloud to the live tutor, and how each reading went.",
        "screens": [
            {"key": "tutor-passages", "model": "tutor.TutorPassage",
             "columns": ["title", "level", "order", "is_published"],
             "search": ["title", "body"], "order": ["order", "title"]},
            {"key": "tutor-sessions", "model": "tutor.TutorSession",
             "columns": ["user", "title", "accuracy_percent", "wcpm", "reading_level", "started_at"],
             "search": ["user__email", "title"], "order": ["-started_at"], "readonly": True},
        ],
    },
    {
        "slug": "quick-words", "name": "Quick Words", "icon": "🔤", "tone": "#b8863b",
        "blurb": "The word library: meanings, transcriptions and pronunciations.",
        "screens": [
            {"key": "words", "model": "quick_words.QuickWord",
             "columns": ["word", "ipa", "level", "source", "is_published"],
             "search": ["word", "definition", "example_sentence"], "order": ["word"]},
            {"key": "word-lists", "model": "quick_words.WordList",
             "columns": ["name", "user", "created_at"], "search": ["name", "user__email"]},
        ],
    },
    {
        "slug": "assessments", "name": "Assessments", "icon": "📋", "tone": "#9b3550",
        "blurb": "Quizzes, timed tests, speaking assessments and results.",
        "screens": [
            {"key": "assessments", "model": "assessments.Assessment",
             "columns": ["title", "kind", "level", "pass_mark", "is_published"],
             "search": ["title", "summary"], "children": ["questions"]},
            {"key": "questions", "model": "assessments.Question",
             "columns": ["__str__", "assessment", "type", "points", "order"],
             "search": ["prompt", "word"], "order": ["order"],
             "parent": ("assessment", "assessments")},
            {"key": "attempts", "model": "assessments.Attempt",
             "columns": ["user", "assessment", "status", "percent", "submitted_at"],
             "search": ["user__email", "assessment__title"], "readonly": True, "view": "assessment"},
        ],
    },
    {
        "slug": "reading-club", "name": "Reading Club", "icon": "📚", "tone": "#1b6b78",
        "blurb": "Termly reading books, chapter by chapter.",
        "screens": [
            {"key": "books", "model": "reading_club.Book",
             "columns": ["title", "author", "order", "is_published"],
             "search": ["title", "author"], "children": ["book-terms"]},
            {"key": "book-terms", "model": "reading_club.Term",
             "columns": ["name", "book", "order"], "search": ["name"],
             "parent": ("book", "books"), "children": ["chapters"]},
            {"key": "chapters", "model": "reading_club.Chapter",
             "columns": ["display_name", "term", "number", "is_published"],
             "search": ["title", "summary", "body"],
             "parent": ("term", "book-terms"), "children": ["chapter-resources"]},
            {"key": "chapter-resources", "model": "reading_club.ChapterResource",
             "columns": ["title", "chapter", "order"], "search": ["title"],
             "parent": ("chapter", "chapters")},
        ],
    },
    {
        "slug": "reference-library", "name": "Reference Library", "icon": "🔎", "tone": "#8c6526",
        "blurb": "Topics, tags and articles learners look things up in.",
        "screens": [
            {"key": "topics", "model": "reference_library.LibraryCategory",
             "columns": ["name", "order"], "search": ["name", "description"],
             "children": ["articles"]},
            {"key": "articles", "model": "reference_library.LibraryArticle",
             "columns": ["title", "category", "order", "is_published"],
             "search": ["title", "summary", "body"],
             "parent": ("category", "topics"), "children": ["attachments"]},
            {"key": "attachments", "model": "reference_library.LibraryAttachment",
             "columns": ["title", "article", "order"], "search": ["title"],
             "parent": ("article", "articles")},
            {"key": "tags", "model": "reference_library.LibraryTag",
             "columns": ["name"], "search": ["name"]},
        ],
    },
    {
        "slug": "people", "name": "People & schools", "icon": "👥", "tone": "#5a3d8a",
        "blurb": "Learners, teachers, admins, schools and joining codes.",
        "screens": [
            {"key": "users", "model": "accounts.User",
             "columns": ["email", "get_full_name", "role", "level", "school", "is_active"],
             "search": ["email", "first_name", "last_name"],
             "form": ["first_name", "last_name", "email", "role", "level", "school", "is_active", "is_staff"]},
            {"key": "schools", "model": "schools.School",
             "columns": ["name", "code", "email", "phone"], "search": ["name", "email", "code"],
             "children": ["joining-codes"]},
            {"key": "joining-codes", "model": "schools.AccessCode",
             "columns": ["code", "school", "role", "level", "label", "used_by"],
             "search": ["code", "label"], "parent": ("school", "schools"),
             "form": ["school", "role", "level", "label"]},
        ],
    },
    {
        "slug": "clash", "name": "Diction Clash", "icon": "⚔️", "tone": "#14213D",
        "blurb": "Games played, with every question and answer.",
        "screens": [
            {"key": "matches", "model": "clash.Match",
             "columns": ["user", "mode", "difficulty", "score", "status", "started_at"],
             "search": ["user__email"], "readonly": True},
        ],
    },
    {
        "slug": "billing", "name": "Billing", "icon": "💳", "tone": "#2e7d62",
        "blurb": "Plans and prices, who has access until when, and every payment.",
        "screens": [
            {"key": "plans", "model": "billing.Plan",
             "columns": ["name", "audience", "band_label", "price", "duration_days", "is_active"],
             "search": ["name", "description"], "order": ["audience", "min_units", "duration_days", "order"],
             "form": ["audience", "name", "min_units", "max_units", "price", "duration_days", "period_label",
                      "description", "features", "is_featured", "is_active", "order"]},
            {"key": "subscriptions", "model": "billing.Subscription",
             "columns": ["__str__", "plan", "trial_ends_at", "paid_until"],
             "search": ["user__email", "school__name"], "order": ["-updated_at"],
             "form": ["plan", "trial_ends_at", "paid_until"]},
            {"key": "payments", "model": "billing.Payment",
             "columns": ["reference", "account_name", "plan_name", "amount_display", "status", "channel", "paid_at"],
             "search": ["reference", "email", "account_name"], "order": ["-created_at"], "readonly": True},
        ],
    },
]

# Quick "add" buttons on the control room home page.
QUICK_ADDS = [
    ("words", "Word", "🔤"),
    ("tutor-passages", "Tutor passage", "🎙️"),
    ("activities", "EchoSpell activity", "🧩"),
    ("card-lessons", "Card lesson", "🃏"),
    ("lesson-items", "Lesson video / audio", "🎬"),
    ("sounds", "Sound lesson", "🗣️"),
    ("assessments", "Assessment", "📋"),
    ("chapters", "Reading chapter", "📚"),
    ("articles", "Library article", "📄"),
    ("schools", "School", "🏫"),
    ("users", "User", "👤"),
    ("plans", "Billing plan", "💳"),
]


def screens():
    """Every screen, keyed by its address-bar name."""
    found = {}
    for section in SECTIONS:
        for screen in section["screens"]:
            found[screen["key"]] = {**screen, "section": section}
    return found


def get_screen(key):
    return screens().get(key)
