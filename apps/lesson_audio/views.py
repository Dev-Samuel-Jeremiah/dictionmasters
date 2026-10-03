"""
Lesson Notes to Audio, for teachers.

    /lesson-audio/                     my lesson notes, and a new one
    /lesson-audio/new/                 POST: typed, uploaded or written with AI
    /lesson-audio/<pk>/                the note: edit, listen, key words
    /lesson-audio/<pk>/save/           POST: the edited note
    /lesson-audio/<pk>/audio/          POST: make the read-aloud
    /lesson-audio/<pk>/status/         GET: where the audio and key words stand
    /lesson-audio/<pk>/keywords/       POST: pick the key words again
    /lesson-audio/<pk>/words/add/      POST: a word of the teacher's own
    /lesson-audio/<pk>/words/<w>/...   POST: practise, or remove, a word
    /lesson-audio/<pk>/download/       the note as a Word file (the audio is
                                       never a download: Save for offline
                                       keeps it inside the app)
    /lesson-audio/<pk>/copy/           POST: my own editable copy
    /lesson-audio/<pk>/delete/         POST

A note belongs to its school's library: everyone there can find it, listen,
practise its key words, print it and download it. Only its owner edits it.
"""

from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from . import services
from .models import LessonNote, spoken_text
from .services import LessonAudioError

CLASS_SUGGESTIONS = ["Nursery 2", "Primary 1", "Primary 2", "Primary 3", "Primary 4", "Primary 5", "Primary 6",
                     "JSS 1", "JSS 2", "JSS 3", "SS 1", "SS 2", "SS 3"]
SUBJECT_SUGGESTIONS = ["English Language", "Mathematics", "Basic Science", "Basic Technology", "Social Studies",
                       "Civic Education", "Christian Religious Studies", "Islamic Religious Studies", "Agricultural Science",
                       "Biology", "Chemistry", "Physics", "Geography", "Economics", "Literature in English",
                       "Computer Studies", "Home Economics", "Creative Arts", "History", "Physical and Health Education"]


def for_teachers(view):
    """Teachers, school admins, individual learners and staff — not pupils."""
    @wraps(view)
    @login_required
    def wrapped(request, *args, **kwargs):
        if request.user.is_student and not request.user.is_staff:
            return render(request, "lesson_audio/teachers_only.html", status=403)
        try:
            return view(request, *args, **kwargs)
        except PermissionDenied as error:
            # Someone else's note: say so plainly, and go back to it.
            pk = kwargs.get("pk")
            return _fail(request, str(error), 403, f"/lesson-audio/{pk}/" if pk else None)
    return wrapped


def _note(request, pk, edit=False):
    """A note this person may see — and, with edit, change."""
    note = get_object_or_404(services.visible(request.user), pk=pk)
    if edit and not services.may_edit(request.user, note):
        raise PermissionDenied("Only the teacher who wrote this note can change it.")
    return note


def _wants_json(request):
    return request.headers.get("x-requested-with") == "XMLHttpRequest" or "application/json" in request.headers.get("accept", "")


def _fail(request, message, status=400, to=None):
    if _wants_json(request):
        return JsonResponse({"error": message}, status=status)
    messages.error(request, message)
    return redirect(to or "lesson_audio:hub")


@for_teachers
def hub(request):
    query = request.GET.get("q", "").strip()
    notes = list(services.search(request.user, query))
    mine = [n for n in notes if n.owner_id == request.user.pk]
    school = [n for n in notes if n.owner_id != request.user.pk]
    return render(request, "lesson_audio/hub.html", {
        "notes": mine,
        "school_notes": school,
        "result_count": len(notes),
        "query": query,
        "total": LessonNote.objects.filter(owner=request.user).count(),
        "library_name": request.user.school.name if request.user.school_id else "",
        "classes": CLASS_SUGGESTIONS,
        "subjects": SUBJECT_SUGGESTIONS,
        "max_chars": services.max_chars(),
        "tab": request.GET.get("tab", "write"),
    })


@for_teachers
@require_POST
def create(request):
    mode = request.POST.get("mode", "typed")
    title = request.POST.get("title", "").strip()[:200]
    subject = request.POST.get("subject", "").strip()[:100]
    class_level = request.POST.get("class_level", "").strip()[:100]
    try:
        if mode == "ai":
            topic = request.POST.get("topic", "").strip()[:200]
            if not topic:
                raise LessonAudioError("Type the topic of the lesson.")
            written = services.write_note(
                request.user, topic=topic, subject=subject, class_level=class_level,
                duration=request.POST.get("duration", "").strip()[:40],
                details=request.POST.get("details", "").strip()[:800],
            )
            title, body, source = written["title"], written["body"], "ai"
        elif mode == "upload":
            guess, body, source = services.extract_text(request.user, request.FILES.getlist("files"))
            title = title or guess
        else:
            body, source = services.tidy(request.POST.get("body", "")), "typed"
            if not body:
                raise LessonAudioError("Type or paste your lesson note.")
            title = title or body.split("\n", 1)[0][:80]
    except LessonAudioError as error:
        return _fail(request, str(error), to=f"/lesson-audio/?tab={mode}")

    note = LessonNote.objects.create(owner=request.user, school=request.user.school if request.user.school_id else None,
                                     title=title or "Lesson note", subject=subject,
                                     class_level=class_level, body=body, source=source)
    try:
        services.start_keywords(note)
    except LessonAudioError:
        pass
    if _wants_json(request):
        return JsonResponse({"url": note.get_absolute_url()})
    return redirect(note)


@for_teachers
def note_page(request, pk):
    note = _note(request, pk)
    words = list(note.keywords.all())
    return render(request, "lesson_audio/note.html", {
        "note": note,
        "can_edit": services.may_edit(request.user, note),
        "can_delete": services.may_delete(request.user, note),
        "words": words,
        "mastered": sum(1 for w in words if w.mastered),
        "voices": services.VOICES,
        "voice_name": services.voice_name(note.audio_voice),
        "audio_status": services.status_of(note, "audio"),
        "keywords_status": services.status_of(note, "keywords"),
        "classes": CLASS_SUGGESTIONS,
        "subjects": SUBJECT_SUGGESTIONS,
        "chars": f"{len(spoken_text(note.body)):,}",
        "max_chars": f"{services.max_chars():,}",
        "audio_left": f"{max(0, services.limit('audio') - services.used_today(request.user, 'audio')):,}",
    })


@for_teachers
@require_POST
def save(request, pk):
    note = _note(request, pk, edit=True)
    body = services.tidy(request.POST.get("body", note.body))
    if not body:
        return _fail(request, "Your note can't be empty.", to=note.get_absolute_url())
    note.title = request.POST.get("title", note.title).strip()[:200] or note.title
    note.subject = request.POST.get("subject", note.subject).strip()[:100]
    note.class_level = request.POST.get("class_level", note.class_level).strip()[:100]
    note.body = body
    note.save()
    if _wants_json(request):
        return JsonResponse(_state(note))
    messages.success(request, "Your note is saved.")
    return redirect(note)


def _state(note):
    note.refresh_from_db()
    return {
        "audio": services.status_of(note, "audio"),
        "audio_error": note.audio_error,
        "audio_current": note.audio_is_current,
        "keywords": services.status_of(note, "keywords"),
        "keywords_error": note.keywords_error,
        "keywords_current": note.keywords_are_current,
        "chars": len(spoken_text(note.body)),
        "words": note.word_count,
        "minutes": note.minutes,
    }


@for_teachers
def status(request, pk):
    response = JsonResponse(_state(_note(request, pk)))
    response["Cache-Control"] = "no-store"
    return response


@for_teachers
@require_POST
def make_audio(request, pk):
    note = _note(request, pk)
    if note.audio_file and not services.may_edit(request.user, note):
        return _fail(request, "This note already has audio. Make your own copy to change it.", 403, note.get_absolute_url())
    try:
        services.start_audio(note, request.POST.get("voice", ""), request.user)
    except LessonAudioError as error:
        return _fail(request, str(error), to=note.get_absolute_url())
    if _wants_json(request):
        return JsonResponse(_state(note))
    return redirect(note)


@for_teachers
@require_POST
def refresh_keywords(request, pk):
    note = _note(request, pk, edit=True)
    try:
        services.start_keywords(note)
    except LessonAudioError as error:
        return _fail(request, str(error), to=note.get_absolute_url())
    if _wants_json(request):
        return JsonResponse(_state(note))
    return redirect(f"{note.get_absolute_url()}#key-words")


@for_teachers
@require_POST
def add_word(request, pk):
    note = _note(request, pk, edit=True)
    try:
        services.add_word(note, request.POST.get("word", ""))
    except LessonAudioError as error:
        return _fail(request, str(error), to=note.get_absolute_url() + "#key-words")
    return redirect(f"{note.get_absolute_url()}#key-words")


@for_teachers
@require_POST
def remove_word(request, pk, word_id):
    note = _note(request, pk, edit=True)
    word = get_object_or_404(note.keywords, pk=word_id)
    if word.audio_file:
        word.audio_file.storage.delete(word.audio_file.name)
    name, storage = (word.audio_file.name, word.audio_file.storage) if word.audio_file else ("", None)
    word.delete()
    if name:
        services.forget_file(name, storage)
    return redirect(f"{note.get_absolute_url()}#key-words")


@for_teachers
@require_POST
def practise(request, pk, word_id):
    note = _note(request, pk)
    word = get_object_or_404(note.keywords, pk=word_id)
    upload = request.FILES.get("audio")
    if upload is None:
        return JsonResponse({"error": "No recording arrived. Please try again."}, status=400)
    try:
        result = services.practise(request.user, word, upload, keep=services.may_edit(request.user, note))
    except LessonAudioError as error:
        return JsonResponse({"error": str(error)}, status=503)
    result.update(attempts=word.attempts, mastered=word.mastered,
                  mastered_total=note.keywords.filter(mastered=True).count(), total=note.keywords.count())
    return JsonResponse(result)


@for_teachers
def download(request, pk):
    """The note as a Word file, for the teacher's device or printer. The
    audio is never a download: it can only be kept offline in the app."""
    note = _note(request, pk)
    name = slugify(note.title)[:60] or "lesson-note"
    response = HttpResponse(services.as_word(note),
                            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    response["Content-Disposition"] = f'attachment; filename="{name}.docx"'
    return response


@for_teachers
@require_POST
def copy(request, pk):
    note = _note(request, pk)
    mine = services.copy_note(note, request.user)
    messages.success(request, f"This is your own copy of “{note.title}”. Change it as you like — the original stays as it was.")
    return redirect(mine)


@for_teachers
@require_POST
def delete(request, pk):
    note = _note(request, pk)
    if not services.may_delete(request.user, note):
        raise PermissionDenied("Only the teacher who wrote this note, or your school admin, can delete it.")
    title = note.title
    services.delete_note(note)
    messages.success(request, f"“{title}” was deleted.")
    return redirect("lesson_audio:hub")
