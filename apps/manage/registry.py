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
"""

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
             "search": ["user__email", "activity__title"], "readonly": True},
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
            {"key": "sound-groups", "model": "book.SoundCategory",
             "columns": ["name", "order"], "search": ["name"], "children": ["sounds"]},
            {"key": "sounds", "model": "book.Sound",
             "columns": ["symbol", "name", "category", "order", "is_published"],
             "search": ["name", "symbol", "example_words"],
             "parent": ("category", "sound-groups"),
             "children": ["articulation", "word-bank", "sentences", "book-passages",
                          "conversations", "twisters", "minimal-pairs", "links"]},
            {"key": "articulation", "model": "book.Articulation",
             "columns": ["sound", "video_caption"], "search": ["trap_text", "mouth_position_text"],
             "parent": ("sound", "sounds")},
            {"key": "word-bank", "model": "book.WordBankEntry",
             "columns": ["word", "sound", "spelling_pattern", "order"], "search": ["word"],
             "parent": ("sound", "sounds")},
            {"key": "sentences", "model": "book.SentencePractice",
             "columns": ["sentence", "sound", "order"], "search": ["sentence"],
             "parent": ("sound", "sounds")},
            {"key": "book-passages", "model": "book.Passage",
             "columns": ["title", "sound", "order"], "search": ["title", "body"],
             "parent": ("sound", "sounds")},
            {"key": "conversations", "model": "book.Conversation",
             "columns": ["title", "sound", "order"], "search": ["title", "script"],
             "parent": ("sound", "sounds")},
            {"key": "twisters", "model": "book.TongueTwister",
             "columns": ["text", "sound", "order"], "search": ["text"],
             "parent": ("sound", "sounds")},
            {"key": "minimal-pairs", "model": "book.MinimalPair",
             "columns": ["word_a", "word_b", "sound", "order"], "search": ["word_a", "word_b"],
             "parent": ("sound", "sounds")},
            {"key": "links", "model": "book.ExternalLink",
             "columns": ["title", "sound", "url", "order"], "search": ["title", "url"],
             "parent": ("sound", "sounds")},
            {"key": "chart-audio", "model": "book.PhonemeAudio",
             "columns": ["key", "symbol", "source", "spoken_text", "updated_at"],
             "search": ["key", "symbol", "spoken_text"]},
        ],
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
             "search": ["user__email", "assessment__title"], "readonly": True},
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
