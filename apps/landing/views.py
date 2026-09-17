import random

from django.shortcuts import render

from apps.book.views import PHONEMIC_CHART

# The words the hero card cycles through. Each one is a sound Nigerian
# learners are most often corrected on — a silent letter, a V read as B,
# a TH read as T or D — so the animation is teaching, not decoration.
HERO_WORDS = [
    {"word": "Wednesday", "ipa": "/ˈwɛnzdeɪ/",
     "tip": "Three syllables on paper, two out loud: <em>WENZ</em>-day."},
    {"word": "achieve", "ipa": "/əˈtʃiːv/",
     "tip": "Hold the <em>ee</em> long — a-CHEEVE, never a-chiv."},
    {"word": "village", "ipa": "/ˈvɪlɪdʒ/",
     "tip": "Upper teeth on the lower lip for the <em>V</em> — never a B."},
    {"word": "breathe", "ipa": "/briːð/",
     "tip": "Voiced <em>TH</em> at the end — feel your throat buzz."},
    {"word": "knowledge", "ipa": "/ˈnɒlɪdʒ/",
     "tip": "The <em>K</em> is silent: NOL-ij."},
    {"word": "warmth", "ipa": "/wɔːmθ/",
     "tip": "Finish the word — tongue between the teeth for the <em>TH</em>."},
]


def _phoneme_symbols():
    """All 44 symbols, in chart order, for the drifting and ribbon layers."""
    return [symbol for group in PHONEMIC_CHART for _, symbol, _ in group["sounds"]]


def _drift_layer():
    """Scatter the 44 symbols across the hero for the background drift.

    The positions are worked out here rather than in CSS because
    calc() has no modulo — `%` inside it means percent, not remainder.
    A fixed seed keeps the scatter identical on every render, so the
    hero looks the same to everyone and nothing shifts between loads.
    """
    scatter = random.Random(44)
    return [
        {
            "symbol": symbol,
            "left": round(scatter.uniform(1, 96), 2),
            "size": round(scatter.uniform(0.85, 2.0), 2),
            "delay": round(scatter.uniform(0, 34), 1),
            "duration": round(scatter.uniform(26, 46), 1),
            "sway": scatter.randint(-38, 38),
        }
        for symbol in _phoneme_symbols()
    ]


def home(request):
    """The public marketing homepage.

    Static copy for now (stats, testimonial, feature text). Once the
    schools/lessons apps exist, the numbers in `stats` can be swapped
    for real querysets without touching the template.
    """
    context = {
        "hero_words": HERO_WORDS,
        "phonemes": _phoneme_symbols(),
        "drift": _drift_layer(),
        "stats": [
            {"value": "100", "label": "schools onboarding"},
            {"value": "350", "label": "videos in the Book of Conversation"},
            {"value": "44", "label": "sounds on the phonemic chart"},
        ],
        "steps": [
            {
                "title": "The school gets an access code",
                "body": "We set your school up and hand your admin a "
                        "code that switches Diction Masters on.",
            },
            {
                "title": "Teachers enrol their class",
                "body": "Each class gets its own code. Pupils join the "
                        "right class and nowhere else.",
            },
            {
                "title": "Pupils watch, listen and speak",
                "body": "Short videos, audio drills and speaking "
                        "tasks, paced like a private lesson.",
            },
            {
                "title": "Teachers see everything",
                "body": "Every recording, score and streak lands on "
                        "the teacher's dashboard, automatically.",
            },
        ],
        "features": [
            {
                "eyebrow": "Watch",
                "icon": "🎬",
                "title": "Lessons a child actually wants to finish",
                "body": "Short British-English videos on pronunciation, "
                        "spelling and vocabulary, built for a term at a "
                        "time so nothing feels overwhelming.",
                "align": "left",
            },
            {
                "eyebrow": "Listen",
                "icon": "🎧",
                "title": "An ear trained on the real sound of English",
                "body": "Audio drills built around the 44 sounds of the "
                        "phonemic chart, so pupils hear the difference "
                        "between how a word is spelled and how it's said.",
                "align": "right",
            },
            {
                "eyebrow": "Speak",
                "icon": "🎤",
                "title": "Practice out loud, without the fear of a class watching",
                "body": "Pupils record themselves reading, repeating "
                        "and presenting, as many times as they need, "
                        "before anyone else hears it.",
                "align": "left",
            },
            {
                "eyebrow": "Get feedback",
                "icon": "📊",
                "title": "A teacher who sees the whole journey",
                "body": "Every video watched, every drill scored, "
                        "every recording made — laid out for the "
                        "teacher, class by class, pupil by pupil.",
                "align": "right",
            },
        ],
    }
    return render(request, "landing/home.html", context)
