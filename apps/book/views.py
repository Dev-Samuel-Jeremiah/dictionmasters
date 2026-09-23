from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, render

from .models import ACADEMY, SECTION_CHOICES, Sound, SoundCategory
from .programmes import programme_for
from . import phoneme_audio, read_along

# The 44 sounds of British English, fixed — this is a linguistic
# reference chart, not admin content, so it always shows all 44
# regardless of how much of the 44 Academy has been filled in yet.
# Each is cross-referenced against real Sound rows by symbol (see
# _real_sounds_by_symbol) so a tap shows the real lesson content
# once an admin has added it, and a "coming soon" note until then.
PHONEMIC_CHART = [
    {
        "group": "Pure Vowels",
        "sounds": [
            ("fleece", "iː", "FLEECE"), ("kit", "ɪ", "KIT"),
            ("foot", "ʊ", "FOOT"), ("goose", "uː", "GOOSE"),
            ("dress", "e", "DRESS"), ("comma", "ə", "COMMA"),
            ("nurse", "ɜː", "NURSE"), ("thought", "ɔː", "THOUGHT"),
            ("trap", "æ", "TRAP"), ("strut", "ʌ", "STRUT"),
            ("start", "ɑː", "START"), ("lot", "ɒ", "LOT"),
        ],
    },
    {
        "group": "Diphthongs",
        "sounds": [
            ("near", "ɪə", "NEAR"), ("face", "eɪ", "FACE"),
            ("cure", "ʊə", "CURE"), ("choice", "ɔɪ", "CHOICE"),
            ("goat", "əʊ", "GOAT"), ("square", "eə", "SQUARE"),
            ("price", "aɪ", "PRICE"), ("mouth", "aʊ", "MOUTH"),
        ],
    },
    {
        "group": "Consonants",
        "sounds": [
            ("pen", "p", "PEN"), ("bad", "b", "BAD"),
            ("tea", "t", "TEA"), ("did", "d", "DID"),
            ("church", "tʃ", "CHURCH"), ("judge", "dʒ", "JUDGE"),
            ("cat", "k", "CAT"), ("got", "g", "GOT"),
            ("fat", "f", "FAT"), ("van", "v", "VAN"),
            ("think", "θ", "THINK"), ("this", "ð", "THIS"),
            ("sit", "s", "SIT"), ("zoo", "z", "ZOO"),
            ("she", "ʃ", "SHE"), ("vision", "ʒ", "VISION"),
            ("man", "m", "MAN"), ("no", "n", "NO"),
            ("sing", "ŋ", "SING"), ("hot", "h", "HOT"),
            ("leg", "l", "LEG"), ("red", "r", "RED"),
            ("wet", "w", "WET"), ("yes", "j", "YES"),
        ],
    },
]


def _normalize_symbol(symbol):
    """So an admin-typed '/u:/' matches the chart's proper '/uː/'."""
    return symbol.strip().strip("/").replace(":", "ː").lower()


def _real_sounds_by_symbol():
    return {
        _normalize_symbol(s.symbol): s
        for s in Sound.objects.in_programme(ACADEMY).filter(is_published=True).select_related("category")
    }


# (url slug, tab label) — order here is the order the tabs appear in.
TABS = SECTION_CHOICES
TAB_SLUGS = {slug for slug, _label in TABS}

def programme_tabs(info):
    """Use each programme's name for its first lesson tab."""
    if info["numbered"]:
        return TABS
    return [(slug, "Sound" if slug == "lens" else label) for slug, label in TABS]


@login_required
def home(request):
    categories = SoundCategory.objects.filter(programme=ACADEMY).order_by("order").prefetch_related("sounds")
    total_sounds = Sound.objects.in_programme(ACADEMY).filter(is_published=True).count()
    from apps.tricks.progress import Standing

    standing = Standing(request.user, ACADEMY)
    context = {
        "categories": categories,
        "total_sounds": total_sounds,
        "done": standing.done,
        "current": standing.current,
    }
    return render(request, "book/home.html", context)


def lesson_groups(programme):
    """A programme's published lessons, group by group, in order."""
    groups = []
    for category in SoundCategory.objects.filter(programme=programme).order_by("order", "name", "pk"):
        sounds = category.sounds.filter(is_published=True).order_by("order", "name")
        if sounds:
            groups.append({"category": category, "sounds": sounds})
    return groups


def lesson_list(request, programme, steps=None):
    """Every lesson of one programme — All 44 Sounds, or All Tricks — with
    where the learner stands on each, when the lessons are taken in order."""
    groups = lesson_groups(programme)
    for group in groups:
        group["rows"] = [{"sound": sound, "step": (steps or {}).get(sound.pk)} for sound in group["sounds"]]
    return render(request, "book/academy.html", {"groups": groups, "programme": programme_for(programme)})


@login_required
def academy(request):
    from apps.tricks.progress import Standing

    return lesson_list(request, ACADEMY, steps=Standing(request.user, ACADEMY).by_lesson)


@login_required
def phonemic_chart(request):
    """A compact, all-44-sounds quick reference — tap a symbol to preview
    its articulation notes here, or jump straight to its full lesson."""
    real_sounds = _real_sounds_by_symbol()
    recordings = phoneme_audio.audio_by_key()

    groups = []
    for group in PHONEMIC_CHART:
        entries = [
            {
                "key": key,
                "symbol": symbol,
                "name": name,
                "sound": real_sounds.get(_normalize_symbol(symbol)),
                "audio": recordings.get(key),
            }
            for key, symbol, name in group["sounds"]
        ]
        groups.append({"label": group["group"], "sounds": entries})

    selected = None
    selected_key = request.GET.get("symbol")
    if selected_key:
        for group in groups:
            for entry in group["sounds"]:
                if entry["key"] == selected_key:
                    selected = {**entry, "group": group["label"]}
                    break
            if selected:
                break

    # Like Quick Words: the sound being opened gets its recording now,
    # and any others still missing are made in the background.
    if selected and not selected["audio"]:
        made = phoneme_audio.make_audio(selected["key"], selected["symbol"])
        selected["audio"] = made if phoneme_audio.has_audio(made) else None
    phoneme_audio.fill_missing_in_background()

    context = {
        "groups": groups,
        "total_sounds": sum(len(g["sounds"]) for g in PHONEMIC_CHART),
        "selected": selected,
        "articulation": getattr(selected["sound"], "articulation", None) if selected and selected["sound"] else None,
    }
    return render(request, "book/phonemic_chart.html", context)


def lesson_detail(request, programme, slug, tab="lens", sound=None, extra_tabs=(), extra=None):
    """One lesson and its eight tabs, in either programme. A lesson is only
    ever found in its own programme, so an address never crosses over.
    A programme can add tabs of its own (`extra_tabs`, e.g. a trick's
    Assessment) and what they show (`extra`)."""
    if tab not in TAB_SLUGS and tab not in dict(extra_tabs):
        raise Http404("That tab doesn't exist.")

    if sound is None:
        sound = get_object_or_404(
            Sound.objects.in_programme(programme).select_related("category"), slug=slug, is_published=True
        )

    info = programme_for(programme)
    context = {
        "sound": sound,
        "programme": info,
        # Tricks are numbered by their place in the list: Trick 1, Trick 2…
        "number": ([s.pk for group in lesson_groups(programme) for s in group["sounds"]].index(sound.pk) + 1
                   if info["numbered"] else None),
        "tabs": [*programme_tabs(info), *extra_tabs],
        "active_tab": tab,
        **(extra or {}),
        # Any number of videos for this tab, in the order the admin set.
        "section_videos": list(sound.videos.filter(section=tab)),
    }

    if tab == "lens":
        context["articulation"] = getattr(sound, "articulation", None)
    elif tab == "word-bank":
        context["entries"] = sound.word_bank_entries.all()
    elif tab == "sentence-practice":
        context["entries"] = sound.sentence_practices.all()
    elif tab == "passage":
        context["entries"] = sound.passages.all()
    elif tab == "conversations":
        context["entries"] = sound.conversations.all()
    elif tab == "twisters":
        context["entries"] = sound.tongue_twisters.all()
    elif tab == "minimal-pairs":
        context["entries"] = sound.minimal_pairs.all()
        context["minimal_pairs_audio"] = getattr(sound, "minimal_pairs_audio", None)
    elif tab == "external-links":
        context["entries"] = sound.external_links.all()

    return render(request, "book/sound_detail.html", context)


@login_required
def sound_detail(request, slug, tab="lens"):
    """A sound's lesson. The 44 sounds are taken in order, each unlocking
    the next once finished and its assessment passed (apps/tricks)."""
    from apps.tricks.views import open_lesson

    return open_lesson(request, ACADEMY, slug, tab)


@login_required
def sound_activity(request, slug, activity_slug):
    from apps.tricks.views import take_activity

    return take_activity(request, ACADEMY, slug, activity_slug)


@login_required
def sound_activity_result(request, slug, activity_slug, attempt_id):
    from apps.tricks.views import activity_result

    return activity_result(request, ACADEMY, slug, activity_slug, attempt_id)


@login_required
def read_along_timing(request, token):
    """Measured word timings for one read-along recording, for the page's
    highlight. Starts measuring in the background if there are none yet."""
    obj = read_along.object_for_token(token)
    if obj is None:
        raise Http404("Nothing to read along with.")
    status, row = read_along.timing_for(obj)
    response = JsonResponse({
        "status": status,
        # While it is still being measured, the page is told how long to
        # keep asking rather than guessing.
        "retry": 4 if status == "pending" else 0,
        # Sent even when the recording turns out to be reading something
        # else: the times still say when and how fast the voice speaks.
        "words": row.words if row else [],
        "speech": row.speech if row else [],
        "duration": row.duration if row else None,
        "quality": row.quality if row else None,
    })
    response["Cache-Control"] = "private, no-cache"
    return response


# ---------------------------------------------------------------------------
# Tricks to Sound Fluent — the lesson, one section at a time
# ---------------------------------------------------------------------------

# What each section of a sound's lesson is for, in a line.
SECTION_BLURBS = {
    "lens": "The trick itself — how to shape your mouth, lips and tongue.",
    "word-bank": "Words to practise it with, grouped by how they are spelt.",
    "sentence-practice": "Sentences to say aloud, packed with it.",
    "passage": "Short passages to read aloud.",
    "conversations": "Conversations to act out, one voice at a time.",
    "twisters": "Tongue twisters that make it stick.",
    "minimal-pairs": "Pairs of words one sound apart, to train your ear.",
    "external-links": "More to watch and read.",
}
SECTION_ICONS = {
    "lens": "\U0001F444", "word-bank": "\U0001F4DD", "sentence-practice": "\U0001F4AC",
    "passage": "\U0001F4D6", "conversations": "\U0001F5E3", "twisters": "\U0001F32A",
    "minimal-pairs": "\U0001F442", "external-links": "\U0001F517",
}
# How to count a sound's content in each section.
SECTION_COUNTS = {
    "lens": "articulation", "word-bank": "word_bank_entries", "sentence-practice": "sentence_practices",
    "passage": "passages", "conversations": "conversations", "twisters": "tongue_twisters",
    "minimal-pairs": "minimal_pairs", "external-links": "external_links",
}


def lesson_sections(request, programme, section=None, steps=None):
    """A programme's lessons one section at a time: the eight sections, or
    — for one section — every lesson, so a learner can go straight to,
    say, the Word List of any of them."""
    from django.db.models import Count, Q

    info = programme_for(programme)
    sections = [{"slug": slug, "label": label, "blurb": SECTION_BLURBS.get(slug, ""),
                 "icon": SECTION_ICONS.get(slug, "")} for slug, label in programme_tabs(info)]
    if section is None:
        return render(request, "book/sections.html", {"sections": sections, "programme": info})
    if section not in TAB_SLUGS:
        raise Http404("That section doesn't exist.")

    relation = SECTION_COUNTS[section]
    sounds = (Sound.objects.in_programme(programme).filter(is_published=True)
              .select_related("category")
              .annotate(items=Count(relation, distinct=True),
                        videos_here=Count("videos", filter=Q(videos__section=section), distinct=True))
              .order_by("category__order", "order"))
    groups = []
    for sound in sounds:
        if not groups or groups[-1]["category"] != sound.category:
            groups.append({"category": sound.category, "sounds": []})
        groups[-1]["sounds"].append(sound)
    current = next(one for one in sections if one["slug"] == section)
    return render(request, "book/sections.html", {
        "sections": sections, "section": current, "groups": groups, "programme": info,
        # One running list for numbered programmes, with where the learner
        # stands on each when they are taken in order.
        "rows": [{"sound": sound, "step": (steps or {}).get(sound.pk)}
                 for group in groups for sound in group["sounds"]],
    })


def moved_to_tricks(request, section=None):
    """/book/tricks/… was Tricks to Sound Fluent before it had a home of its own."""
    from django.shortcuts import redirect

    return redirect("tricks:section", section) if section else redirect("tricks:home")
