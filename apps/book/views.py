from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, render

from .models import SECTION_CHOICES, Sound, SoundCategory
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
        for s in Sound.objects.filter(is_published=True).select_related("category")
    }


# (url slug, tab label) — order here is the order the tabs appear in.
TABS = SECTION_CHOICES
TAB_SLUGS = {slug for slug, _label in TABS}


@login_required
def home(request):
    categories = SoundCategory.objects.order_by("order").prefetch_related("sounds")
    total_sounds = Sound.objects.filter(is_published=True).count()
    context = {
        "categories": categories,
        "total_sounds": total_sounds,
    }
    return render(request, "book/home.html", context)


@login_required
def academy(request):
    groups = []
    for category in SoundCategory.objects.order_by("order"):
        sounds = category.sounds.filter(is_published=True).order_by("order")
        if sounds:
            groups.append({"category": category, "sounds": sounds})
    return render(request, "book/academy.html", {"groups": groups})


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


@login_required
def sound_detail(request, slug, tab="lens"):
    if tab not in TAB_SLUGS:
        raise Http404("That tab doesn't exist.")

    sound = get_object_or_404(
        Sound.objects.select_related("category"), slug=slug, is_published=True
    )

    context = {
        "sound": sound,
        "tabs": TABS,
        "active_tab": tab,
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
