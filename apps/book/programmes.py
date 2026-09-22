"""
The two programmes built on the same lessons, and what makes each its own.

44 Academy and Tricks to Sound Fluent share every page — the lesson with
its eight tabs, the list of lessons, browsing by section — so everything
one can do, the other can too. What differs lives here: the names, the
words for a lesson, and the addresses of each programme's own pages.
Templates are handed one of these as `programme` and link through it
(`{% url programme.lesson_tab lesson.slug tab %}`), so a page never
sends a learner to the other programme by mistake.
"""

from .models import ACADEMY, TRICKS

PROGRAMMES = {
    ACADEMY: {
        "key": ACADEMY,
        "name": "44 Academy",
        "icon": "\U0001F4D6",
        "lesson_word": "sound",
        "lessons_word": "sounds",
        "list_title": "All 44 Sounds",
        "home": "book:home",
        "list": "book:academy",
        "lesson": "book:sound_detail",
        "lesson_tab": "book:sound_detail_tab",
        "sections": None,
        "section": None,
    },
    TRICKS: {
        "key": TRICKS,
        "name": "Tricks to Sound Fluent",
        "icon": "✨",
        "lesson_word": "trick",
        "lessons_word": "tricks",
        "list_title": "All Tricks",
        "home": "tricks:home",
        "list": "tricks:lessons",
        "lesson": "tricks:lesson",
        "lesson_tab": "tricks:lesson_tab",
        "sections": "tricks:sections",
        "section": "tricks:section",
    },
}


def programme_for(key):
    return PROGRAMMES.get(key) or PROGRAMMES[ACADEMY]
