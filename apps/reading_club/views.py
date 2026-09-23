"""
Views for Reading Club: Book > Term > Chapter, one level shallower
than Learning Modules since a chapter is opened straight from its
term — no week, no day, no separate lesson items. Terms still unlock
in order, using the same locked/active/done pattern as
apps.learning_modules.views (kept separate here since the two apps
are decoupled, but the logic is intentionally the same shape).
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import Book, Chapter, ChapterProgress, Term


def _completed_chapter_ids(user, book):
    return set(
        ChapterProgress.objects.filter(user=user, chapter__term__book=book).values_list(
            "chapter_id", flat=True
        )
    )


def _book_tree(book):
    """Terms, with their published chapters, prefetched in one go."""
    return book.terms.order_by("order", "id").prefetch_related(
        Prefetch("chapters", queryset=Chapter.objects.filter(is_published=True).order_by("number"))
    )


def _progress(chapter_ids, completed_ids):
    total = len(chapter_ids)
    done = sum(1 for c in chapter_ids if c in completed_ids)
    percent = round(done * 100 / total) if total else 0
    return {"total": total, "done": done, "percent": percent}


def _progress_chain(items, get_chapter_ids, completed_ids, label):
    """Attach a locked/active/done status to each item in order — each
    one stays locked until the one before it is fully complete."""
    cards = []
    unlocked = True
    for item in items:
        chapter_ids = get_chapter_ids(item)
        prog = _progress(chapter_ids, completed_ids)
        complete = prog["total"] == 0 or prog["done"] == prog["total"]
        status = "locked" if not unlocked else ("done" if complete and prog["total"] else "active")
        cards.append({label: item, "status": status, **prog})
        unlocked = unlocked and complete
    return cards


def _flatten(terms):
    """Every (term, chapter) in the book, in order — regardless of lock state."""
    return [
        {"term": term, "chapter": chapter}
        for term in terms
        for chapter in term.chapters.all()
    ]


def _reachable_flat(terms, completed_ids):
    """Every (term, chapter) that sits inside an unlocked term."""
    flat = []
    term_cards = _progress_chain(
        terms, lambda t: [c.id for c in t.chapters.all()], completed_ids, "term"
    )
    for tcard in term_cards:
        if tcard["status"] == "locked":
            break
        for chapter in tcard["term"].chapters.all():
            flat.append({"term": tcard["term"], "chapter": chapter})
    return flat


def _term_status(book, term, completed_ids):
    terms = list(_book_tree(book))
    cards = _progress_chain(terms, lambda t: [c.id for c in t.chapters.all()], completed_ids, "term")
    return next((c["status"] for c in cards if c["term"].id == term.id), "locked")


@login_required
def hub(request):
    books = Book.objects.filter(is_published=True).order_by("order", "title")
    book_cards = []
    for book in books:
        terms = list(_book_tree(book))
        completed_ids = _completed_chapter_ids(request.user, book)
        flat = _flatten(terms)
        book_cards.append({
            "book": book,
            "term_count": len(terms),
            "progress": _progress([e["chapter"].id for e in flat], completed_ids),
        })
    return render(request, "reading_club/hub.html", {"book_cards": book_cards})


@login_required
def book_detail(request, book_slug):
    book = get_object_or_404(Book, slug=book_slug, is_published=True)
    terms = list(_book_tree(book))
    completed_ids = _completed_chapter_ids(request.user, book)
    flat = _flatten(terms)
    progress = _progress([e["chapter"].id for e in flat], completed_ids)

    term_cards = _progress_chain(terms, lambda t: [c.id for c in t.chapters.all()], completed_ids, "term")

    reachable = _reachable_flat(terms, completed_ids)
    continue_entry = next((e for e in reachable if e["chapter"].id not in completed_ids), None) or (
        reachable[0] if reachable else None
    )

    context = {
        "book": book,
        "term_cards": term_cards,
        "progress": progress,
        "continue_entry": continue_entry,
    }
    return render(request, "reading_club/book_detail.html", context)


@login_required
def term_detail(request, book_slug, term_slug):
    book = get_object_or_404(Book, slug=book_slug, is_published=True)
    term = get_object_or_404(book.terms, slug=term_slug)
    completed_ids = _completed_chapter_ids(request.user, book)

    if _term_status(book, term, completed_ids) == "locked":
        messages.warning(request, "Complete the term before this one to unlock it.")
        return redirect("reading_club:book_detail", book_slug=book_slug)

    chapters = term.chapters.filter(is_published=True).order_by("number")
    current_id = next((c.id for c in chapters if c.id not in completed_ids), None)
    chapter_rows = [
        {
            "chapter": chapter,
            "is_complete": chapter.id in completed_ids,
            "is_current": chapter.id == current_id,
        }
        for chapter in chapters
    ]

    return render(
        request,
        "reading_club/term_detail.html",
        {"book": book, "term": term, "chapter_rows": chapter_rows},
    )


@login_required
def chapter_detail(request, book_slug, term_slug, chapter_slug):
    book = get_object_or_404(Book, slug=book_slug, is_published=True)
    term = get_object_or_404(book.terms, slug=term_slug)
    completed_ids = _completed_chapter_ids(request.user, book)

    if _term_status(book, term, completed_ids) == "locked":
        messages.warning(request, "Complete the term before this one to unlock it.")
        return redirect("reading_club:book_detail", book_slug=book_slug)

    chapter = get_object_or_404(term.chapters, slug=chapter_slug, is_published=True)

    terms = list(_book_tree(book))
    reachable = _reachable_flat(terms, completed_ids)
    index = next((i for i, e in enumerate(reachable) if e["chapter"].id == chapter.id), None)
    prev_entry = reachable[index - 1] if index else None
    next_entry = reachable[index + 1] if index is not None and index < len(reachable) - 1 else None

    context = {
        "book": book,
        "term": term,
        "chapter": chapter,
        "is_complete": chapter.id in completed_ids,
        "prev_entry": prev_entry,
        "next_entry": next_entry,
        "resources": chapter.resources.all(),
    }
    return render(request, "reading_club/chapter_detail.html", context)


@login_required
@require_POST
def toggle_complete(request, book_slug, term_slug, chapter_slug):
    book = get_object_or_404(Book, slug=book_slug, is_published=True)
    term = get_object_or_404(book.terms, slug=term_slug)
    chapter = get_object_or_404(term.chapters, slug=chapter_slug)

    ChapterProgress.objects.get_or_create(user=request.user, chapter=chapter)

    return redirect(
        "reading_club:chapter_detail", book_slug=book_slug, term_slug=term_slug, chapter_slug=chapter_slug
    )
