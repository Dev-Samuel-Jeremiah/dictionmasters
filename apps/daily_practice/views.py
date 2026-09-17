"""Daily Practice picks a small set of pronunciation drills at random
from whatever already lives in the 44 Academy (word bank, sentence
practice, tongue twisters, minimal pairs) — no content of its own.

The set is seeded by today's date, so everyone sees the same set for
the whole day unless they ask for a fresh one via the shuffle link.
"""

import random
import uuid
from datetime import date

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.book.models import Sound

# (tab slug, label, related_name on Sound) — also doubles as the link
# back into the matching tab of the sound's full lesson page.
ACTIVITY_KINDS = [
    ("word-bank", "Word Bank", "word_bank_entries"),
    ("sentence-practice", "Sentence Practice", "sentence_practices"),
    ("twisters", "Tongue Twister", "tongue_twisters"),
    ("minimal-pairs", "Minimal Pair", "minimal_pairs"),
]


@login_required
def home(request):
    shuffle_token = request.GET.get("shuffle")
    rng = random.Random(shuffle_token or date.today().isoformat())

    sound, activities = _pick_activity_set(rng)

    context = {
        "sound": sound,
        "activities": activities,
        "is_daily": not shuffle_token,
        "next_shuffle_token": uuid.uuid4().hex,
    }
    return render(request, "daily_practice/home.html", context)


def _pick_activity_set(rng):
    """Shuffle the published sounds and return the first one that has
    at least one activity, with one random pick from each kind it has."""
    sounds = list(Sound.objects.filter(is_published=True))
    rng.shuffle(sounds)

    for sound in sounds:
        activities = []
        for tab_slug, label, related_name in ACTIVITY_KINDS:
            items = list(getattr(sound, related_name).all())
            if items:
                activities.append(_build_activity(tab_slug, label, rng.choice(items)))
        if activities:
            return sound, activities
    return None, []


def _build_activity(kind, label, item):
    activity = {"kind": kind, "label": label, "tab_slug": kind}
    if kind == "word-bank":
        activity["heading"] = item.word
        activity["body"] = item.spelling_pattern
        activity["audio"] = item.audio_source
    elif kind == "sentence-practice":
        activity["body"] = item.sentence
        activity["audio"] = item.audio_source
    elif kind == "twisters":
        activity["body"] = item.text
        activity["audio"] = item.audio_source
    elif kind == "minimal-pairs":
        activity["word_a"] = item.word_a
        activity["word_b"] = item.word_b
        activity["body"] = item.notes
    return activity
