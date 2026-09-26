import random

from django.shortcuts import render

from apps.book.views import PHONEMIC_CHART
from apps.manage.rich_text import plain_text

def _hero_words():
    """Choose today's six Quick Words with saved IPA, in a stable order."""
    from apps.quick_words.models import QuickWord
    from django.utils import timezone

    words = QuickWord.objects.filter(is_published=True).exclude(ipa="").order_by("word")
    count = words.count()
    if not count:
        return []

    # Advance through the library each day without showing a new random
    # selection on every page refresh.
    per_day = min(6, count)
    start = (timezone.localdate().toordinal() * per_day) % count
    fields = ("word", "ipa", "example_sentence", "definition")
    rows = list(words.values(*fields)[start:start + per_day])
    if len(rows) < per_day:
        rows.extend(words.values(*fields)[:per_day - len(rows)])

    return [
        {
            "word": row["word"],
            "ipa": row["ipa"],
            "tip": plain_text(row["example_sentence"] or row["definition"]),
        }
        for row in rows
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
    from apps.billing.models import BillingSettings, Plan

    def lowest(audience):
        plan = Plan.objects.filter(is_active=True, audience=audience).order_by("price").first()
        return plan

    billing = BillingSettings.load()
    context = {
        "trial_days": billing.trial_days if billing.paywall_enabled else 0,
        # One card per kind of learner, so nobody reads the page as
        # "schools only". Starting prices come from the plans in the database.
        "audiences": [
            {
                "key": "adults", "icon": "🧑", "tone": "#3D63E6",
                "title": "Adults & individual learners",
                "body": "Sharpen your pronunciation for work, study or confidence — "
                        "at your own pace, on your own schedule. No school needed.",
                "points": ["Every learning tool, just for you", "Practise speaking in private", "Weekly to yearly plans"],
                "plan": lowest(Plan.AUDIENCE_INDIVIDUAL),
                "cta": "Start learning", "url": "accounts:register_individual",
            },
            {
                "key": "students", "icon": "🎒", "tone": "#2f5d8a",
                "title": "Students learning at home",
                "body": "Keep practising after school with the lessons your school uses. "
                        "Sign up with your school's code — a parent can do it for you.",
                "points": ["Joins your school with its code", "The right work for your level", "Termly or yearly, per child"],
                "plan": lowest(Plan.AUDIENCE_STUDENT),
                "cta": "Sign up as a student", "url": "accounts:register_student",
            },
            {
                "key": "schools", "icon": "🏫", "tone": "#1846E0",
                "title": "Schools",
                "body": "Give every teacher the tools to teach British English sounds, "
                        "and see each class's progress in one place.",
                "points": ["Priced by number of teachers", "Codes put teachers in the right class", "Termly or yearly"],
                "plan": lowest(Plan.AUDIENCE_SCHOOL),
                "cta": "Register your school", "url": "accounts:register_school",
            },
        ],
        "hero_words": _hero_words(),
        "phonemes": _phoneme_symbols(),
        "drift": _drift_layer(),
        "stats": [
            {"value": "100", "label": "schools onboarding"},
            {"value": "350", "label": "videos in 44 Academy"},
            {"value": "44", "label": "sounds on the phonemic chart"},
        ],
        "steps": [
            {
                "title": "Choose how you join",
                "body": "On your own as an adult learner, as a student "
                        "with your school's code, or as a whole school.",
            },
            {
                "title": "Start free or pay",
                "body": "Try everything with the free trial, no card "
                        "needed, or pick a plan straight away.",
            },
            {
                "title": "Watch, listen and speak",
                "body": "Short videos, audio drills and speaking "
                        "tasks, paced like a private lesson.",
            },
            {
                "title": "See yourself improve",
                "body": "Scores, streaks and recordings build up on your "
                        "dashboard, and on your teacher's if you're in a school.",
            },
        ],
        "features": [
            {
                "eyebrow": "Watch",
                "icon": "🎬",
                "title": "Lessons you actually want to finish",
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
                        "phonemic chart, so you hear the difference "
                        "between how a word is spelled and how it's said.",
                "align": "right",
            },
            {
                "eyebrow": "Speak",
                "icon": "🎤",
                "title": "Practise out loud, without anyone watching",
                "body": "Record yourself reading, repeating "
                        "and presenting, as many times as they need, "
                        "before anyone else hears it.",
                "align": "left",
            },
            {
                "eyebrow": "Get feedback",
                "icon": "📊",
                "title": "Progress you can see",
                "body": "Every video watched, every drill scored, "
                        "every recording made — on your own dashboard, "
                        "and for schools, laid out class by class for teachers.",
                "align": "right",
            },
        ],
    }
    return render(request, "landing/home.html", context)


def privacy(request):
    """The privacy policy. Both app stores need its address; edit the text in
    templates/landing/privacy.html."""
    return render(request, "landing/privacy.html")
