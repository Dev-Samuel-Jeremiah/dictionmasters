from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def hub(request):
    """The launcher for every learning tool. New tools join this list
    as they're built, each as its own app."""
    tools = [
        {
            "name": "AI Reading Tutor",
            "blurb": "Read a passage aloud to a live tutor. It stops to "
                     "help with any word you mispronounce, then gives you "
                     "your reading level and feedback straight away.",
            "url_name": "tutor:hub",
            "available": True,
            "icon": "tutor",
        },
        {
            "name": "Daily Practice",
            "blurb": "A fresh set of pronunciation drills — a word, a "
                     "sentence and a tongue twister — pulled at random "
                     "from the 44 Academy each day.",
            "url_name": "daily_practice:home",
            "available": True,
            "icon": "daily-practice",
        },
        {
            "name": "Book of Conversation",
            "blurb": "The 44 Academy — a full lesson for every sound of "
                     "English: articulation, word bank, sentence practice, "
                     "passages, conversations, twisters and minimal pairs.",
            "url_name": "book:home",
            "available": True,
            "icon": "book",
        },
        {
            "name": "Reading Club",
            "blurb": "This term's reading book, chapter by chapter — "
                     "listen to the model reading, follow the text, and "
                     "work through First, Second and Third term in order.",
            "url_name": "reading_club:hub",
            "available": True,
            "icon": "reading-club",
        },
        {
            "name": "Reference Library",
            "blurb": "Look things up — grammar points, spelling rules, "
                     "word origins and anything else worth researching, "
                     "browsable by topic or searchable by keyword.",
            "url_name": "reference_library:home",
            "available": True,
        },
    ]
    return render(request, "learning_tools/hub.html", {"tools": tools})
