"""
How the admin is arranged: every part of Diction Masters, grouped the way
an admin thinks about it rather than by Django app.

Each feature lists the admin screens that belong to it, as
"app_label.model_name". The same order drives the console's content
library and the admin sidebar, so everything is always in one place.
Add a new model here once and it appears in both.
"""

FEATURES = [
    {
        "slug": "learning-modules", "name": "Learning Modules", "icon": "🎓", "tone": "#2f5d8a",
        "blurb": "Term-by-term courses: modules, terms, weeks, days and their lessons.",
        "models": ["learning_modules.learningmodule", "learning_modules.term", "learning_modules.week",
                   "learning_modules.day", "learning_modules.lessonitem"],
        "site_url": "learning_modules:hub",
    },
    {
        "slug": "echospell", "name": "EchoSpell", "icon": "🔊", "tone": "#2e7d62",
        "blurb": "Levels, groups, card lessons, passages, dialogues and scored activities.",
        "models": ["echospell.level", "echospell.group", "echospell.category", "echospell.cardlesson",
                   "echospell.passage", "echospell.dialogue", "echospell.activity", "echospell.activityattempt"],
        "site_url": "echospell:hub",
    },
    {
        "slug": "book", "name": "44 Academy", "icon": "📖", "tone": "#7A2438",
        "blurb": "The 44 sounds, their lessons, and the phonemic chart audio.",
        "models": ["book.soundcategory", "book.sound", "book.sectionvideo", "book.wordbankentry", "book.sentencepractice",
                   "book.passage", "book.conversation", "book.tonguetwister", "book.minimalpair",
                   "book.externallink", "book.phonemeaudio"],
        "site_url": "book:home",
    },
    {
        "slug": "tutor", "name": "AI Reading Tutor", "icon": "🎙️", "tone": "#1f6f5c",
        "blurb": "Passages learners read aloud to the live tutor, and how each reading went.",
        "models": ["tutor.tutorpassage", "tutor.tutorsession"],
        "site_url": "tutor:hub",
    },
    {
        "slug": "quick-words", "name": "Quick Words", "icon": "🔤", "tone": "#b8863b",
        "blurb": "The word library with meanings, transcriptions and pronunciations.",
        "models": ["quick_words.quickword", "quick_words.wordlist"],
        "site_url": "quick_words:hub",
    },
    {
        "slug": "assessments", "name": "Assessments", "icon": "📋", "tone": "#9b3550",
        "blurb": "Quizzes, timed tests, speaking assessments, placement tests and results.",
        "models": ["assessments.assessment", "assessments.attempt"],
        "site_url": "assessments:hub",
    },
    {
        "slug": "reading-club", "name": "Reading Club", "icon": "📚", "tone": "#1b6b78",
        "blurb": "Termly reading books, chapter by chapter.",
        "models": ["reading_club.book", "reading_club.term", "reading_club.chapter"],
        "site_url": "reading_club:hub",
    },
    {
        "slug": "reference-library", "name": "Reference Library", "icon": "🔎", "tone": "#8c6526",
        "blurb": "Topics, tags and articles learners can look things up in.",
        "models": ["reference_library.librarycategory", "reference_library.librarytag",
                   "reference_library.libraryarticle"],
        "site_url": "reference_library:home",
    },
    {
        "slug": "clash", "name": "Diction Clash", "icon": "⚔️", "tone": "#14213D",
        "blurb": "Games played, with every question and answer.",
        "models": ["clash.match"],
        "site_url": "clash:hub",
    },
    {
        "slug": "people", "name": "People & schools", "icon": "👥", "tone": "#5a3d8a",
        "blurb": "Learners, teachers, admins, schools and joining codes.",
        "models": ["accounts.user", "schools.school", "schools.accesscode", "auth.group"],
        "site_url": None,
    },
    {
        "slug": "progress", "name": "Progress records", "icon": "📈", "tone": "#4b5563",
        "blurb": "What learners have marked complete.",
        "models": ["echospell.groupprogress", "learning_modules.dayprogress", "reading_club.chapterprogress"],
        "site_url": None,
    },
]

# Sidebar order for the Django apps (anything unlisted goes last).
APP_ORDER = [
    "learning_modules", "echospell", "book", "quick_words", "assessments",
    "reading_club", "reference_library", "clash", "accounts", "schools", "auth",
]

# The buttons along the top of the console: the things added most often.
QUICK_ADDS = [
    ("quick_words.quickword", "Word", "🔤"),
    ("echospell.activity", "EchoSpell activity", "🧩"),
    ("echospell.cardlesson", "Card lesson", "🃏"),
    ("learning_modules.lessonitem", "Lesson video / audio", "🎬"),
    ("book.sound", "Sound lesson", "🗣️"),
    ("assessments.assessment", "Assessment", "📋"),
    ("reading_club.chapter", "Reading chapter", "📚"),
    ("reference_library.libraryarticle", "Library article", "📄"),
    ("schools.school", "School", "🏫"),
    ("accounts.user", "User", "👤"),
]
