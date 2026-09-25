from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse

from apps.accounts.access import limit_to_levels
from apps.learning_tools.views import TOOLS
from apps.manage.rich_text import plain_text


MAX_RESULTS_PER_TYPE = 8


def _search_items(request, query, per_type=MAX_RESULTS_PER_TYPE):
    items = []

    def add(queryset, title, section, summary, url):
        for obj in queryset[:per_type]:
            items.append({
                "title": title(obj),
                "section": section,
                "summary": plain_text(summary(obj)),
                "url": url(obj),
            })

    if len(query) >= 2:
        needle = query
        for tool in TOOLS:
            if needle.casefold() in f"{tool['name']} {tool['blurb']}".casefold():
                items.append({"title": tool["name"], "section": "Platform feature", "summary": tool["blurb"], "url": reverse(tool["url_name"])})

        from apps.reference_library.models import LibraryArticle
        articles = LibraryArticle.objects.filter(is_published=True).filter(
            Q(title__icontains=needle) | Q(summary__icontains=needle) | Q(body__icontains=needle) | Q(tags__name__icontains=needle)
        ).select_related("category").distinct().order_by("title")
        add(articles, lambda x: x.title, "Reference Library", lambda x: x.summary or x.category.name, lambda x: reverse("reference_library:article", args=[x.slug]))

        from apps.diction_library.models import LibraryItem
        library = LibraryItem.objects.filter(is_published=True).filter(
            Q(title__icontains=needle) | Q(summary__icontains=needle) | Q(description__icontains=needle)
        )
        if request.user.is_authenticated and request.user.school_id:
            library = library.filter(Q(school__isnull=True) | Q(school_id=request.user.school_id))
        else:
            library = library.filter(school__isnull=True)
        add(library.order_by("title"), lambda x: x.title, "Diction Library", lambda x: x.summary or x.get_kind_display(), lambda x: reverse("diction_library:detail", args=[x.slug]))

        from apps.diction_radio.models import RadioEpisode, RadioProgram
        programs = RadioProgram.objects.filter(is_published=True).filter(
            Q(title__icontains=needle) | Q(tagline__icontains=needle) | Q(description__icontains=needle) | Q(presenter__icontains=needle)
        )
        add(programs, lambda x: x.title, "Diction Radio programme", lambda x: x.tagline or x.description, lambda x: reverse("diction_radio:home") + f"#program-{x.pk}")
        episodes = RadioEpisode.objects.filter(is_published=True, program__is_published=True).filter(
            Q(title__icontains=needle) | Q(description__icontains=needle) | Q(transcript__icontains=needle) | Q(program__title__icontains=needle)
        ).select_related("program")
        add(episodes, lambda x: x.title, "Diction Radio episode", lambda x: x.description or x.program.title, lambda x: reverse("diction_radio:home") + f"#program-{x.program_id}")

        from apps.reading_club.models import Book, Chapter
        books = Book.objects.filter(is_published=True).filter(Q(title__icontains=needle) | Q(author__icontains=needle) | Q(description__icontains=needle) | Q(overview__icontains=needle))
        add(books, lambda x: x.title, "Reading Club book", lambda x: x.description or x.author, lambda x: reverse("reading_club:book_detail", args=[x.slug]))
        chapters = Chapter.objects.filter(is_published=True, term__book__is_published=True).filter(Q(title__icontains=needle) | Q(summary__icontains=needle) | Q(body__icontains=needle)).select_related("term__book")
        add(chapters, lambda x: x.title, "Reading Club lesson", lambda x: x.summary or x.term.book.title, lambda x: reverse("reading_club:chapter_detail", args=[x.term.book.slug, x.term.slug, x.slug]))

        from apps.learning_modules.models import LearningModule, LessonItem
        modules = LearningModule.objects.filter(is_published=True).filter(Q(name__icontains=needle) | Q(description__icontains=needle) | Q(overview__icontains=needle))
        add(modules, lambda x: x.name, "Learning Module", lambda x: x.description or x.overview, lambda x: reverse("learning_modules:module_detail", args=[x.slug]))
        lessons = LessonItem.objects.filter(is_published=True, day__is_published=True, day__week__term__module__is_published=True).filter(Q(title__icontains=needle) | Q(description__icontains=needle) | Q(body__icontains=needle)).select_related("day__week__term__module")
        add(lessons, lambda x: x.title, "Learning Module lesson", lambda x: x.description or x.day.week.term.module.name, lambda x: reverse("learning_modules:module_detail", args=[x.day.week.term.module.slug]))

        from apps.book.models import Sound
        sounds = Sound.objects.filter(is_published=True).filter(Q(name__icontains=needle) | Q(symbol__icontains=needle) | Q(example_words__icontains=needle) | Q(category__name__icontains=needle)).select_related("category")
        academy = sounds.filter(category__programme="academy")
        add(academy, lambda x: x.name, "44 Academy lesson", lambda x: f"{x.symbol} · {x.example_words}".strip(" ·"), lambda x: reverse("book:sound_detail", args=[x.slug]))
        tricks = sounds.filter(category__programme="tricks")
        add(tricks, lambda x: x.name, "Tricks to Sound Fluent lesson", lambda x: x.example_words or x.symbol, lambda x: reverse("tricks:lesson", args=[x.slug]))

        from apps.quick_words.models import QuickWord
        words = limit_to_levels(QuickWord.objects.filter(is_published=True).filter(
            Q(word__icontains=needle) | Q(definition__icontains=needle) | Q(example_sentence__icontains=needle) | Q(ipa__icontains=needle)
        ), request.user)
        add(words, lambda x: x.word, "Quick Words", lambda x: x.definition, lambda x: reverse("quick_words:word_detail", args=[x.slug]))

        from apps.tutor.models import TutorPassage
        passages = limit_to_levels(TutorPassage.objects.filter(is_published=True).filter(Q(title__icontains=needle) | Q(summary__icontains=needle) | Q(body__icontains=needle)), request.user)
        add(passages, lambda x: x.title, "AI Reading Tutor passage", lambda x: x.summary or x.level, lambda x: reverse("tutor:read", args=[x.pk]))

        from apps.assessments.models import Assessment
        assessments = limit_to_levels(Assessment.objects.filter(is_published=True).filter(Q(title__icontains=needle) | Q(summary__icontains=needle) | Q(instructions__icontains=needle)), request.user)
        add(assessments, lambda x: x.title, "Assessment", lambda x: x.summary or x.get_kind_display(), lambda x: reverse("assessments:detail", args=[x.slug]))

        from apps.echospell.models import CardLesson, Level
        lessons = CardLesson.objects.filter(is_published=True).filter(
            Q(title__icontains=needle) | Q(word__icontains=needle) | Q(definition__icontains=needle) | Q(example_sentence__icontains=needle) | Q(category__name__icontains=needle)
        ).select_related("group__level", "category")
        lessons = limit_to_levels(lessons, request.user, field="group__level__name", allow_blank=False)
        add(lessons, lambda x: x.title or (x.word_list[0] if x.word_list else x.category.name), "EchoSpell lesson", lambda x: f"{x.group.level.name} · {x.category.name}", lambda x: reverse("echospell:card_detail", args=[x.group.level.slug, x.group.slug, x.category.slug]))
        levels = Level.objects.filter(is_published=True).filter(Q(name__icontains=needle) | Q(description__icontains=needle))
        if request.user.is_authenticated and request.user.role in {"teacher", "student"} and request.user.level:
            levels = levels.filter(name=request.user.level)
        add(levels, lambda x: x.name, "EchoSpell level", lambda x: x.description, lambda x: reverse("echospell:level_detail", args=[x.slug]))

    return items


def results(request):
    query = request.GET.get("q", "").strip()[:100]
    items = _search_items(request, query) if len(query) >= 2 else []
    return render(request, "platform_search/results.html", {
        "query": query,
        "items": items,
        "minimum_length": len(query) < 2,
    })


def suggest(request):
    query = request.GET.get("q", "").strip()[:100]
    items = _search_items(request, query, per_type=3) if len(query) >= 2 else []
    return JsonResponse({"results": items[:10]})
