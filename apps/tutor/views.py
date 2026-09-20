"""
Pages and endpoints for the live AI reading tutor.

    hub       choose a passage; see past readings
    read      the live reading page (static/js/tutor.js does the work)
    start     open a session for a passage
    check     hear one sentence, or one word said again, and judge it
    say       the tutor's model pronunciation of a word or sentence
    finish    score the reading and write the feedback
    report    the result, straight after reading and any time later

Everything a session does is tied to its owner. The tutor's voice only
ever speaks words from the passage being read — never text sent by the
page — so the voice service can't be used for anything else.
"""

import logging
import re

from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import Http404, HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.access import limit_to_levels
from apps.book.read_along import AlignmentUnavailable

from . import listen, pronounce, report, voice
from .models import TutorPassage, TutorSession, level_index

logger = logging.getLogger(__name__)

# Each check is a paid transcription. Nobody reads more than a sentence
# every two seconds; anything faster is a script.
CHECKS_PER_MINUTE = 30
CHECKS_PER_SESSION = 400
SPEECH_PER_MINUTE = 40
PIECES_PER_MINUTE = 400        # a recording arrives in pieces while it is spoken
MAX_CLIP_BYTES = 6 * 1024 * 1024


def _passages(user):
    return limit_to_levels(TutorPassage.objects.filter(is_published=True), user)


def _limited(user, name, per_minute):
    key = f"tutor:{name}:{user.pk}"
    count = cache.get(key, 0)
    if count >= per_minute:
        return True
    cache.set(key, count + 1, 60)
    return False


def _own_session(request, session_id):
    session = get_object_or_404(TutorSession.objects.select_related("passage"), pk=session_id)
    if session.user_id != request.user.id and not request.user.is_staff:
        raise Http404
    return session


def recommend(user, after=None):
    """The passage to read next: harder after a comfortable reading, the
    same level after a good one, easier after a struggle."""
    passages = list(_passages(user))
    if not passages:
        return None
    read_ids = set(TutorSession.objects.filter(user=user, status=TutorSession.STATUS_DONE)
                   .values_list("passage_id", flat=True))
    after = after or TutorSession.objects.filter(user=user, status=TutorSession.STATUS_DONE).first()
    if after is None:
        return passages[0]
    here = level_index(after.passage_level)
    step = {TutorSession.BAND_INDEPENDENT: 1, TutorSession.BAND_INSTRUCTIONAL: 0}.get(after.band, -1)
    target = here + step

    def distance(passage):
        return (abs(passage.level_rank - target), passage.id in read_ids, passage.id == after.passage_id,
                passage.order)
    return min(passages, key=distance)


@login_required
@require_GET
def hub(request):
    passages = sorted(_passages(request.user), key=lambda p: (p.level_rank, p.order, p.title))
    history = list(TutorSession.objects.filter(user=request.user, status=TutorSession.STATUS_DONE)[:8])
    return render(request, "tutor/hub.html", {
        "passages": passages,
        "history": history,
        "latest": history[0] if history else None,
        "suggested": recommend(request.user),
    })


@login_required
@require_GET
def read(request, pk):
    passage = get_object_or_404(_passages(request.user), pk=pk)
    sentences = _with_british(listen.sentences(passage.body))
    return render(request, "tutor/read.html", {
        "passage": passage,
        "sentences": sentences,
        "first_name": (request.user.first_name or "").strip(),
    })


def _with_british(sentences):
    """Mark the words an American would say differently enough to be worth
    hearing in British — "dance", "water", "new" — so the page can show
    them and the tutor can model them."""
    for sentence in sentences:
        found = pronounce.british_words([word["text"] for word in sentence["words"]])
        for index, difference in found.items():
            sentence["words"][index]["british"] = difference
    return sentences


@login_required
@require_POST
def start(request, pk):
    passage = get_object_or_404(_passages(request.user), pk=pk)
    session = TutorSession.objects.create(
        user=request.user, passage=passage, title=passage.title, passage_level=passage.level,
    )
    listen.sweep()      # anything left by a reading someone walked away from
    return JsonResponse({"session": session.pk})


def _index(value, size):
    try:
        index = int(value)
    except (TypeError, ValueError):
        return None
    return index if 0 <= index < size else None


@login_required
@require_POST
def piece(request, session_id):
    """One piece of a recording, sent while the learner is still reading,
    so that when they stop there is nothing left to upload."""
    session = _own_session(request, session_id)
    if session.status != TutorSession.STATUS_READING:
        return JsonResponse({"error": "This reading has finished."}, status=409)
    clip, number, audio = request.POST.get("clip"), request.POST.get("piece"), request.FILES.get("audio")
    if not clip or number is None or audio is None:
        return JsonResponse({"error": "Missing piece."}, status=400)
    if _limited(request.user, "piece", PIECES_PER_MINUTE):
        return JsonResponse({"error": "Too many pieces."}, status=429)
    try:
        held = listen.keep_piece(session.pk, clip, number, audio,
                                 listen._suffix(audio.name, audio.content_type))
    except (OSError, ValueError):
        return JsonResponse({"error": "Couldn't keep that piece."}, status=400)
    if held > MAX_CLIP_BYTES:
        listen.forget(session.pk, clip)
        return JsonResponse({"error": "That recording is too long."}, status=413)
    return JsonResponse({"ok": True})


@login_required
@require_POST
def check(request, session_id):
    session = _own_session(request, session_id)
    if session.status != TutorSession.STATUS_READING or session.passage is None:
        return JsonResponse({"error": "This reading has finished."}, status=409)
    parts = listen.sentences(session.passage.body)
    number = _index(request.POST.get("sentence"), len(parts))
    upload = request.FILES.get("audio")
    clip = request.POST.get("clip")
    if number is None or (upload is None and not clip):
        return JsonResponse({"error": "Missing sentence or recording."}, status=400)
    if session.checks >= CHECKS_PER_SESSION or _limited(request.user, "check", CHECKS_PER_MINUTE):
        return JsonResponse({"error": "Slow down a little — try again in a moment."}, status=429)
    session.checks += 1

    words = parts[number]["words"]
    word_at = request.POST.get("word")
    try:
        if clip:
            # Sent piece by piece while it was spoken; the last piece comes
            # with this request, so nothing is waited on here.
            if upload is not None:
                listen.keep_piece(session.pk, clip, request.POST.get("piece") or 999, upload,
                                  listen._suffix(upload.name, upload.content_type))
            heard = listen.transcribe_file(listen.gather(session.pk, clip))
        else:
            heard = listen.transcribe(upload)
    except listen.NotHeard:
        session.save(update_fields=["checks"])
        return JsonResponse({"heard": False})
    except AlignmentUnavailable as error:
        session.save(update_fields=["checks"])
        logger.warning("Tutor couldn't transcribe: %s", error)
        return JsonResponse({"error": "The tutor can't listen right now. Please try again shortly."}, status=503)
    finally:
        if clip:
            listen.forget(session.pk, clip)

    if word_at not in (None, ""):
        at = _index(word_at, len(words))
        if at is None:
            return JsonResponse({"error": "Unknown word."}, status=400)
        target = words[at]["text"]
        result = listen.judge_word(target, heard)
        bare = voice.bare(target).lower()
        entry = session.practised.get(bare, {"tries": 0, "ok": False})
        entry["tries"] += 1
        entry["ok"] = entry["ok"] or result["ok"]
        session.practised[bare] = entry
        session.save(update_fields=["checks", "practised"])
        return JsonResponse({"heard": True, "word": result})

    result = listen.judge_sentence(words, heard)
    # How the words to practise are written on the phonemic chart, where
    # Quick Words knows them.
    result["ipa"] = {}
    for at in result["model"]:
        entry = voice.library_word(words[at]["text"])
        result["ipa"][str(at)] = (entry.ipa if entry and entry.ipa
                                  else pronounce.transcription(words[at]["text"]))
    kept = session.sentences.get(str(number))
    if kept is None:
        # The first reading is the one scored; later ones are practice.
        session.sentences[str(number)] = {**result, "tries": 1}
    else:
        kept["tries"] = kept.get("tries", 1) + 1
    session.save(update_fields=["checks", "sentences"])
    return JsonResponse({"heard": True, "sentence": result})


@login_required
@require_GET
def say(request, session_id):
    """The tutor saying a word (?sentence=&word=) or a whole sentence
    (?sentence=) from this session's passage, as audio: a redirect to a
    recording already kept, or a fresh one. 204 when there's no voice to
    be had — the page then uses the browser's own."""
    session = _own_session(request, session_id)
    if session.passage is None:
        raise Http404
    parts = listen.sentences(session.passage.body)
    number = _index(request.GET.get("sentence"), len(parts))
    if number is None:
        raise Http404
    words = parts[number]["words"]
    word_at = request.GET.get("word")
    single = word_at not in (None, "")
    if single:
        at = _index(word_at, len(words))
        if at is None:
            raise Http404
        text = words[at]["text"]
    else:
        text = parts[number]["text"]

    found = voice.kept_url(text, single_word=single)
    if found:
        return HttpResponseRedirect(found)
    if _limited(request.user, "say", SPEECH_PER_MINUTE):
        return HttpResponse(status=204)
    audio = voice.make(text, single_word=single)
    if not audio:
        return HttpResponse(status=204)
    voice.keep_later(text, audio, single_word=single)
    return _audio_response(request, audio)


def _audio_response(request, audio):
    """MP3 bytes, answering a byte-range request properly — Safari won't
    play audio from a server that doesn't."""
    size = len(audio)
    match = re.match(r"bytes=(\d*)-(\d*)$", request.headers.get("Range", ""))
    if match and (match.group(1) or match.group(2)):
        if match.group(1):
            first = int(match.group(1))
            last = min(int(match.group(2)), size - 1) if match.group(2) else size - 1
        else:
            first, last = max(size - int(match.group(2)), 0), size - 1
        if first > last or first >= size:
            response = HttpResponse(status=416)
            response["Content-Range"] = f"bytes */{size}"
            return response
        response = HttpResponse(audio[first:last + 1], status=206, content_type="audio/mpeg")
        response["Content-Range"] = f"bytes {first}-{last}/{size}"
    else:
        response = HttpResponse(audio, content_type="audio/mpeg")
    response["Accept-Ranges"] = "bytes"
    response["Cache-Control"] = "private, max-age=3600"
    return response


@login_required
@require_POST
def finish(request, session_id):
    session = _own_session(request, session_id)
    listen.forget(session.pk)
    if session.status == TutorSession.STATUS_READING:
        if session.passage is None or not session.sentences:
            return JsonResponse({"error": "Read at least one sentence first."}, status=400)
        report.finish(session, session.passage.body)
    return JsonResponse({"report": reverse("tutor:report", args=[session.pk])})


@login_required
@require_GET
def report_page(request, session_id):
    session = _own_session(request, session_id)
    if session.status != TutorSession.STATUS_DONE:
        raise Http404
    parts = listen.sentences(session.passage.body) if session.passage else []
    # The passage with each word as it was first read, for the page.
    marked = []
    for index, part in enumerate(parts):
        result = session.sentences.get(str(index)) or {}
        statuses = {w["i"]: w for w in result.get("words", [])}
        marked.append([
            {"text": word["text"], "status": statuses.get(i, {}).get("status", "unread" if not result else "skip"),
             "heard": statuses.get(i, {}).get("heard", ""), "i": i}
            for i, word in enumerate(part["words"])
        ])
    practise, seen = [], set()
    for index, part in enumerate(parts):
        result = session.sentences.get(str(index)) or {}
        for word in result.get("words", []):
            if word["status"] in ("wrong", "missed"):
                text = voice.bare(part["words"][word["i"]]["text"])
                if text.lower() in seen or not text:
                    continue
                seen.add(text.lower())
                practise.append({"text": text, "sentence": index, "word": word["i"],
                                 "heard": word.get("heard", ""), "tips": word.get("tips", []),
                                 "status": word["status"]})
    british = []
    for index, part in enumerate(parts):
        for at, difference in pronounce.british_words([w["text"] for w in part["words"]]).items():
            text = voice.bare(part["words"][at]["text"])
            if text and text.lower() not in {entry["text"].lower() for entry in british}:
                british.append({"text": text, "sentence": index, "word": at, **difference})
    return render(request, "tutor/report.html", {
        "session": session,
        "british": british[:10],
        "marked": marked,
        "practise": practise[:12],
        "typical": report.TYPICAL_WCPM.get(session.passage_level),
        "next_passage": recommend(session.user, after=session),
    })
