"""
Views for Quick Words.

Everything here works without JavaScript: searching is a GET form,
and adding a word to a list is a POST that returns you to the exact
word you were looking at, so a slow classroom connection still behaves
predictably.
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

from apps.accounts.access import limit_to_levels

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.db.models import Case, IntegerField, Q, Value, When
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.text import slugify
from django.views.decorators.http import require_GET, require_POST

from apps.manage.rich_text import plain_text

from .british_ipa import get_british_ipa
from .lookup import LookupUnavailable, is_lookup_candidate, lookup
from .models import QuickWord, WordList
from .speech import SpeechUnavailable, is_configured as speech_is_configured, synthesise

logger = logging.getLogger(__name__)

SUGGESTION_LIMIT = 8
# Each look-up is a paid API call. No person types faster than this;
# a script hammering the endpoint would.
LOOKUPS_PER_MINUTE = 20
# Longest a look-up will wait for its audio before saving the word
# without it, so a slow voice service never leaves someone staring at
# a spinner.
AUDIO_WAIT_SECONDS = 15

# Audio is requested in the background the moment a look-up starts, so
# it is ready by the time OpenAI has answered instead of being made
# afterwards. Shared across requests so threads aren't created per call.
_speech_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="quick-words-speech")


def _published(user=None):
    """Published words. For a school's teachers and students that means
    their own level's words, plus any word with no level of its own."""
    words = QuickWord.objects.filter(is_published=True)
    return limit_to_levels(words, user) if user is not None else words


def _back_to(request, fallback):
    """Return the learner to where they pressed the button, anchor and
    search term intact, rather than to the top of the library."""
    target = request.POST.get("next", "")
    return redirect(target if target.startswith("/") else fallback)


@login_required
def hub(request):
    query = request.GET.get("q", "").strip()
    words = _published(request.user)
    if query:
        words = words.filter(Q(word__icontains=query) | Q(definition__icontains=query))

    lists = WordList.objects.filter(user=request.user).prefetch_related("words")
    saved = {wl.id: set(wl.words.values_list("id", flat=True)) for wl in lists}

    rows = [
        {"word": w, "in_lists": [wl for wl in lists if w.id in saved[wl.id]]}
        for w in words
    ]
    return render(request, "quick_words/hub.html", {
        "words": words,
        "query": query,
        "total": _published(request.user).count(),
        "lists": lists,
        "saved": saved,
        "rows": rows,
        # No match, but it looks like a real word: offer to look it up
        # rather than just saying nothing was found.
        "can_lookup": bool(query) and not rows and is_lookup_candidate(query),
    })


@login_required
@require_GET
def suggest(request):
    """Words matching what's been typed so far, for the live dropdown.

    Words that *start* with the typed letters come first — someone
    typing "ach" wants "achieve" before "teacher".
    """
    query = request.GET.get("q", "").strip()[:40]
    if not query:
        return JsonResponse({"query": query, "results": [], "can_lookup": False})

    matches = (
        _published(request.user)
        .filter(word__icontains=query)
        .annotate(rank=Case(
            When(word__iexact=query, then=Value(0)),
            When(word__istartswith=query, then=Value(1)),
            default=Value(2),
            output_field=IntegerField(),
        ))
        .order_by("rank", "word")
        .values(
            "word", "slug", "ipa", "ipa_source", "ipa_confidence",
            "ipa_review_required", "ipa_accent", "definition",
        )[:SUGGESTION_LIMIT]
    )
    results = [
        {
            "word": m["word"],
            "ipa": m["ipa"] or None,
            "ipa_source": m["ipa_source"] or None,
            "ipa_confidence": m["ipa_confidence"] or None,
            "ipa_review_required": m["ipa_review_required"],
            "ipa_accent": m["ipa_accent"],
            "definition": plain_text(m["definition"])[:90],
            "url": reverse("quick_words:word_detail", args=[m["slug"]]),
        }
        for m in matches
    ]
    has_exact = any(r["word"].lower() == query.lower() for r in results)
    return JsonResponse({
        "query": query,
        "results": results,
        "can_lookup": not has_exact and is_lookup_candidate(query),
    })


def _throttled(user):
    key = f"quick-words-lookups:{user.pk}"
    count = cache.get(key, 0)
    if count >= LOOKUPS_PER_MINUTE:
        return True
    cache.set(key, count + 1, timeout=60)
    return False


def _refresh_trusted_ipa(word):
    """Keep saved AI or legacy IPA from shadowing a local dictionary entry."""
    pronunciation = get_british_ipa(word.word, allow_ai=False)
    if pronunciation["source"] not in {"britfone", "ipa_dict"}:
        return word

    fields = {
        "ipa": pronunciation["ipa"] or "",
        "ipa_accent": pronunciation["accent"],
        "ipa_source": pronunciation["source"],
        "ipa_confidence": pronunciation["confidence"],
        "ipa_review_required": pronunciation["review_required"],
    }
    changed = [name for name, value in fields.items() if getattr(word, name) != value]
    if changed:
        for name in changed:
            setattr(word, name, fields[name])
        word.save(update_fields=[*changed, "updated_at"])
    return word


def _lookup_response(request, status, message=None, word=None, created=False):
    """JSON for the live search; a normal redirect for a plain form post."""
    wants_json = "application/json" in request.headers.get("Accept", "")
    if wants_json:
        data = {"message": message}
        if word is not None:
            data.update({
                "word": word.word,
                "url": reverse("quick_words:word_detail", args=[word.slug]),
                "created": created,
                "ipa": word.ipa or None,
                "ipa_source": word.ipa_source or None,
                "ipa_confidence": word.ipa_confidence or None,
                "ipa_review_required": word.ipa_review_required,
                "ipa_accent": word.ipa_accent,
            })
        return JsonResponse(data, status=status)

    if word is not None:
        return redirect("quick_words:word_detail", slug=word.slug)
    messages.error(request, message)
    return redirect(reverse("quick_words:hub"))


@login_required
@require_POST
def lookup_word(request):
    """Find a word the library doesn't have, and add it.

    Cheapest path first: if the word already exists nothing is sent to
    OpenAI at all. Only a genuinely new, real word is written.
    """
    typed = request.POST.get("word", "").strip()

    existing = _published(request.user).filter(word__iexact=typed).first()
    if existing:
        return _lookup_response(request, 200, word=_refresh_trusted_ipa(existing))

    if not is_lookup_candidate(typed):
        return _lookup_response(request, 400, "Type a single English word to look it up.")

    if _throttled(request.user):
        return _lookup_response(request, 429, "That's a lot of look-ups at once — give it a minute.")

    # Start the pronunciation now, alongside OpenAI, rather than after it.
    speech = _speech_pool.submit(synthesise, typed) if speech_is_configured() else None

    try:
        entry = lookup(typed)
    except LookupUnavailable:
        return _lookup_response(request, 503, "Word look-up isn't available right now. Please try again shortly.")

    if entry is None:
        return _lookup_response(
            request, 422, f"“{typed}” doesn't look like an English word — check the spelling."
        )

    # The model may have corrected the spelling to a word we already have.
    existing = QuickWord.objects.filter(word__iexact=entry["word"]).first()
    if existing:
        return _lookup_response(request, 200, word=_refresh_trusted_ipa(existing))

    try:
        with transaction.atomic():
            word = QuickWord.objects.create(
                slug=slugify(entry["word"]),
                source=QuickWord.SOURCE_AI,
                **entry,
            )
    except IntegrityError:
        # Someone else looked up the same word in the same instant.
        word = QuickWord.objects.get(slug=slugify(entry["word"]))
        return _lookup_response(request, 200, word=_refresh_trusted_ipa(word))

    _attach_pronunciation(word, typed, speech)
    return _lookup_response(request, 201, word=word, created=True)


def _attach_pronunciation(word, typed, speech):
    """Save the spoken word onto a freshly added entry.

    The audio already in progress was for what the person *typed*. If
    OpenAI corrected the spelling, that recording says the wrong word, so
    the corrected word is spoken instead. Any failure just leaves the
    word without audio — it is still a complete entry.
    """
    if speech is None:
        return
    try:
        if word.word.lower() != typed.lower():
            audio = synthesise(word.word)
        else:
            audio = speech.result(timeout=AUDIO_WAIT_SECONDS)
    except (SpeechUnavailable, FutureTimeout) as error:
        logger.warning("No pronunciation saved for %r: %s", word.word, error or "timed out")
        return

    word.audio_file.save(f"{word.slug}.mp3", ContentFile(audio), save=True)


@login_required
def word_detail(request, slug):
    word = get_object_or_404(_published(request.user), slug=slug)

    # Neighbours in the same A-Z order the library is browsed in.
    ordered = list(_published(request.user).values_list("slug", flat=True))
    index = ordered.index(word.slug)
    previous_slug = ordered[index - 1] if index > 0 else None
    next_slug = ordered[index + 1] if index < len(ordered) - 1 else None

    lists = WordList.objects.filter(user=request.user).prefetch_related("words")

    return render(request, "quick_words/word_detail.html", {
        "word": word,
        "previous": _published(request.user).filter(slug=previous_slug).first(),
        "next": _published(request.user).filter(slug=next_slug).first(),
        "list_rows": [
            {"list": wl, "has_word": wl.words.filter(pk=word.pk).exists()} for wl in lists
        ],
        "position": index + 1,
        "total": len(ordered),
    })


@login_required
def my_lists(request):
    lists = WordList.objects.filter(user=request.user).prefetch_related("words")
    return render(request, "quick_words/my_lists.html", {
        "rows": [{"list": wl, "words": list(wl.words.all())} for wl in lists],
    })


@login_required
@require_POST
def create_list(request):
    name = request.POST.get("name", "").strip()[:120]
    if name:
        WordList.objects.get_or_create(user=request.user, name=name)
    return _back_to(request, reverse("quick_words:my_lists"))


@login_required
@require_POST
def delete_list(request, list_id):
    get_object_or_404(WordList, pk=list_id, user=request.user).delete()
    return redirect("quick_words:my_lists")


@login_required
@require_POST
def toggle_word(request, list_id, slug):
    word_list = get_object_or_404(WordList, pk=list_id, user=request.user)
    word = get_object_or_404(_published(request.user), slug=slug)

    if word_list.words.filter(pk=word.pk).exists():
        word_list.words.remove(word)
    else:
        word_list.words.add(word)

    return _back_to(request, reverse("quick_words:hub"))
