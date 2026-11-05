"""
What each learner's app keeps on the device.

The app used to crawl the site from a list of front pages, re-fetching
everything each time and stopping at 400 pages. Now it asks for a list
instead: every page this learner may open, each with a version, and it
fetches only the pages whose version has changed (templates/pwa/sw.js).

Most content tables record no "last changed" date, so a version is a
fingerprint of the rows behind the page: change a word, a recording or an
answer and that page's fingerprint changes. Pictures and audio aren't
listed: they're found in the pages themselves, and a replaced file changes
the page that uses it.

    catalog(levels, tools)   the list for one level and its open tools.
                             The same for everyone on that level, so it's
                             kept for ten minutes and asked for once, not
                             once per learner.
    manifest(user)           that list for one person, as the app gets it.

Each source below adds one programme's pages. Add a source when a new
learning tool is built, or the app won't keep it.
"""

import hashlib
from collections import defaultdict

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.db.models import FileField
from django.urls import reverse

CACHE_SECONDS = 10 * 60


def _version(*parts):
    return hashlib.md5(repr(parts).encode("utf-8")).hexdigest()[:12]


def _is_video(field):
    return "video" in field.name and "poster" not in field.name


class Shelf:
    """The pages found so far, with the stored files behind them (only the
    size report reads those: apps/offline/management/commands)."""

    def __init__(self):
        self.pages = []
        self.seen = set()
        self.files = set()
        self.videos = set()
        self.video_refs = []
        self.source = ""
        self.counts = defaultdict(int)

    def add(self, path, version=""):
        if path in self.seen:
            return
        self.seen.add(path)
        self.pages.append({"p": path, "v": version})
        self.counts[self.source] += 1

    def rows(self, queryset):
        """A table's rows as plain values, noting the files they hold."""
        found = list(queryset.values())
        fields = [f for f in queryset.model._meta.concrete_fields if isinstance(f, FileField)]
        for row in found:
            for field in fields:
                if row.get(field.attname):
                    (self.videos if _is_video(field) else self.files).add(row[field.attname])
                    if field.attname == "video_file":
                        # The name static/js/offline_video.js keeps a copy under.
                        self.video_refs.append(f"{ContentType.objects.get_for_model(queryset.model).pk}-{row['id']}")
        return found


def _front_pages(shelf, tools):
    """The way in to each tool. Their contents change with the learner's
    progress, so they have no version and are fetched at every sync."""
    shelf.source = "front pages"
    shelf.add(reverse("accounts:dashboard"))
    shelf.add(reverse("learning_tools:hub"))
    shelf.add("/videos/offline/")
    pages = {
        "book:home": ["book:home", "book:academy"],
        "tricks:home": ["tricks:home", "tricks:lessons", "tricks:sections"],
        "echospell:hub": ["echospell:hub"],
        "learning_modules:hub": ["learning_modules:hub"],
        "reading_club:hub": ["reading_club:hub"],
        "assembly_recitals:hub": ["assembly_recitals:hub"],
        "conversational_dialogue:hub": ["conversational_dialogue:hub"],
        "daily_practice:home": ["daily_practice:home"],
        "quick_words:hub": ["quick_words:hub", "quick_words:my_lists"],
        "book:phonemic_chart": ["book:phonemic_chart"],
        "diction_library:hub": ["diction_library:hub"],
        "diction_radio:home": ["diction_radio:home"],
        "reference_library:home": ["reference_library:home"],
    }
    for tool, names in pages.items():
        if tool in tools:
            for name in names:
                shelf.add(reverse(name))
    shelf.add(reverse("assessments:hub"))


def _echospell(shelf, levels):
    from apps.echospell.levels import echospell_level
    from apps.echospell.models import Activity, ActivityItem, CardLesson, Dialogue, DialogueLine, Level, Passage

    shelf.source = "EchoSpell"
    names = {echospell_level(level) for level in levels}
    if not names:
        return
    for level in Level.objects.filter(is_published=True, name__in=names).prefetch_related("categories", "groups"):
        groups = list(level.groups.all())
        categories = list(level.categories.all())
        parts = defaultdict(list)
        for model, key in ((CardLesson, "group_id"), (Passage, "group_id"), (Dialogue, "group_id")):
            found = model.objects.filter(group__level=level)
            for row in shelf.rows(found):
                parts[row[key]].append(row)
        talks = {row["id"]: row["group_id"] for row in Dialogue.objects.filter(group__level=level).values("id", "group_id")}
        for row in shelf.rows(DialogueLine.objects.filter(dialogue__group__level=level)):
            parts[talks.get(row["dialogue_id"])].append(row)
        activities = defaultdict(list)
        owners = {}
        for row in shelf.rows(Activity.objects.filter(group__level=level, is_published=True)):
            activities[row["group_id"]].append(row)
            owners[row["id"]] = row["group_id"]
            parts[row["group_id"]].append(row)
        for row in shelf.rows(ActivityItem.objects.filter(activity__group__level=level, activity__is_published=True)):
            parts[owners.get(row["activity_id"])].append(row)

        shelf.add(reverse("echospell:level_detail", args=[level.slug]),
                  _version(level.name, [(g.pk, g.title) for g in groups], [c.pk for c in categories]))
        for group in groups:
            version = _version(group.title, parts[group.pk])
            shelf.add(reverse("echospell:group_detail", args=[level.slug, group.slug]), version)
            for category in categories:
                shelf.add(reverse("echospell:card_detail", args=[level.slug, group.slug, category.slug]), version)
            for activity in activities[group.pk]:
                shelf.add(reverse("echospell:activity_detail", args=[level.slug, group.slug, activity["slug"]]), version)


def _lessons(shelf, programme, label):
    """The 44 Academy or Tricks. Lessons are opened in order, so a learner's
    app is turned away from later ones (a redirect) until they get there:
    it skips them and picks them up at a later sync."""
    from apps.book.models import Sound
    from apps.book.programmes import programme_for
    from apps.tricks.models import LessonActivity, LessonActivityItem
    from apps.tricks.progress import TAB_CONTENT, _tabs_with_content, lessons_in_order

    shelf.source = label
    info = programme_for(programme)
    lessons = lessons_in_order(programme)
    ids = [lesson.pk for lesson in lessons]
    parts = defaultdict(list)
    for relation in (*TAB_CONTENT.values(), "videos"):
        field = Sound._meta.get_field(relation)
        link = field.field.attname
        for row in shelf.rows(field.related_model.objects.filter(**{f"{link}__in": ids})):
            parts[row[link]].append(row)
    activities = defaultdict(list)
    owners = {}
    for row in shelf.rows(LessonActivity.objects.filter(lesson_id__in=ids, is_published=True)):
        activities[row["lesson_id"]].append(row)
        owners[row["id"]] = row["lesson_id"]
        parts[row["lesson_id"]].append(row)
    for row in shelf.rows(LessonActivityItem.objects.filter(activity__lesson_id__in=ids, activity__is_published=True)):
        parts[owners.get(row["activity_id"])].append(row)
    tabs = _tabs_with_content(lessons)
    for lesson in lessons:
        version = _version(lesson.name, lesson.symbol, parts[lesson.pk])
        shelf.add(reverse(info["lesson"], args=[lesson.slug]), version)
        for tab in tabs.get(lesson.pk, []):
            shelf.add(reverse(info["lesson_tab"], args=[lesson.slug, tab]), version)
        if activities[lesson.pk]:
            shelf.add(reverse(info["lesson_tab"], args=[lesson.slug, "assessment"]), version)
        for activity in activities[lesson.pk]:
            shelf.add(reverse(info["activity"], args=[lesson.slug, activity["slug"]]), version)


def _for_levels(queryset, levels, field="levels"):
    """Content made for several levels, or for everyone (no levels ticked)."""
    from django.db.models import Q

    condition = Q(**{field: ""})
    for level in levels:
        condition |= Q(**{f"{field}__contains": f",{level},"})
    return queryset.filter(condition)


def _modules(shelf, levels):
    from apps.learning_modules.models import Day, LearningModule, LessonItem, LessonResource, LessonSlide, Term, Week

    shelf.source = "Learning Modules"
    modules = list(_for_levels(LearningModule.objects.filter(is_published=True), levels))
    ids = [module.pk for module in modules]
    terms = list(Term.objects.filter(module_id__in=ids).select_related("module"))
    weeks = list(Week.objects.filter(term__module_id__in=ids).select_related("term__module"))
    days = list(Day.objects.filter(is_published=True, week__term__module_id__in=ids).select_related("week__term__module"))
    parts = defaultdict(list)
    item_days = {}
    for row in shelf.rows(LessonItem.objects.filter(is_published=True, day__in=days)):
        parts[row["day_id"]].append(row)
        item_days[row["id"]] = row["day_id"]
    for model in (LessonSlide, LessonResource):
        for row in shelf.rows(model.objects.filter(lesson_item__day__in=days, lesson_item__is_published=True)):
            parts[item_days.get(row["lesson_item_id"])].append(row)

    outline = _version([(t.pk, t.name) for t in terms], [(w.pk, w.number) for w in weeks], [d.pk for d in days])
    for module in modules:
        shelf.add(reverse("learning_modules:module_detail", args=[module.slug]), _version(module.name, outline))
    for term in terms:
        shelf.add(reverse("learning_modules:term_detail", args=[term.module.slug, term.slug]), outline)
    for week in weeks:
        shelf.add(reverse("learning_modules:week_detail", args=[week.term.module.slug, week.term.slug, week.slug]), outline)
    for day in days:
        week = day.week
        shelf.add(reverse("learning_modules:day_detail", args=[week.term.module.slug, week.term.slug, week.slug, day.day_name]),
                  _version(parts[day.pk]))


def _reading_club(shelf, levels):
    from apps.reading_club.models import Book, Chapter, ChapterResource, Term

    shelf.source = "Reading Club"
    books = list(_for_levels(Book.objects.filter(is_published=True), levels))
    terms = list(Term.objects.filter(book__in=books).select_related("book"))
    chapters = list(Chapter.objects.filter(is_published=True, term__in=terms).select_related("term__book"))
    rows = {row["id"]: row for row in shelf.rows(Chapter.objects.filter(is_published=True, term__in=terms))}
    extras = defaultdict(list)
    for row in shelf.rows(ChapterResource.objects.filter(chapter__in=chapters)):
        extras[row["chapter_id"]].append(row)
    outline = _version([(t.pk, t.name) for t in terms], list(rows))
    for book in books:
        shelf.add(reverse("reading_club:book_detail", args=[book.slug]), _version(book.title, outline))
    for term in terms:
        shelf.add(reverse("reading_club:term_detail", args=[term.book.slug, term.slug]), outline)
    for chapter in chapters:
        shelf.add(reverse("reading_club:chapter_detail", args=[chapter.term.book.slug, chapter.term.slug, chapter.slug]),
                  _version(rows[chapter.pk], extras[chapter.pk]))


def _recitals(shelf):
    from apps.assembly_recitals.models import Recital, Section

    shelf.source = "Assembly Recitals"
    sections = {section.pk: section for section in Section.objects.filter(is_published=True)}
    by_section = defaultdict(list)
    for row in shelf.rows(Recital.objects.filter(is_published=True, section__is_published=True)):
        by_section[row["section_id"]].append(row)
    for pk, section in sections.items():
        shelf.add(reverse("assembly_recitals:section", args=[section.slug]), _version(section.name, by_section[pk]))
        for row in by_section[pk]:
            shelf.add(reverse("assembly_recitals:recital", args=[section.slug, row["slug"]]), _version(row, section.name))


def _dialogues(shelf, levels):
    from apps.conversational_dialogue.models import Dialogue, DialogueLevel

    shelf.source = "Conversational Dialogue"
    wanted = {level.pk: level for level in DialogueLevel.objects.filter(is_published=True, name__in=levels)}
    by_level = defaultdict(list)
    for row in shelf.rows(Dialogue.objects.filter(is_published=True, level_id__in=wanted)):
        by_level[row["level_id"]].append(row)
    for pk, level in wanted.items():
        shelf.add(reverse("conversational_dialogue:level", args=[level.slug]), _version(by_level[pk]))
        for row in by_level[pk]:
            shelf.add(reverse("conversational_dialogue:dialogue", args=[level.slug, row["slug"]]), _version(row))


def _reference(shelf):
    from apps.reference_library.models import LibraryArticle, LibraryAttachment, LibraryCategory

    shelf.source = "Reference Library"
    categories = {category.pk: category for category in LibraryCategory.objects.all()}
    articles = shelf.rows(LibraryArticle.objects.filter(is_published=True))
    extras = defaultdict(list)
    for row in shelf.rows(LibraryAttachment.objects.filter(article__is_published=True)):
        extras[row["article_id"]].append(row)
    outline = _version([(row["id"], row["title"]) for row in articles])
    for category in categories.values():
        shelf.add(reverse("reference_library:category", args=[category.slug]), outline)
    for row in articles:
        shelf.add(reverse("reference_library:article", args=[row["slug"]]), _version(row, extras[row["id"]]))


def _quick_words(shelf, levels):
    from apps.quick_words.models import QuickWord

    shelf.source = "Quick Words"
    for row in shelf.rows(QuickWord.objects.filter(is_published=True, level__in=[*levels, ""])):
        shelf.add(reverse("quick_words:word_detail", args=[row["slug"]]), _version(row))


def build(levels, tools):
    """The Shelf for these levels and these open tools."""
    shelf = Shelf()
    _front_pages(shelf, tools)
    if "echospell:hub" in tools:
        _echospell(shelf, levels)
    if "learning_modules:hub" in tools:
        _modules(shelf, levels)
    if "book:home" in tools:
        _lessons(shelf, "academy", "44 Academy")
    if "tricks:home" in tools:
        _lessons(shelf, "tricks", "Tricks to Sound Fluent")
    if "assembly_recitals:hub" in tools:
        _recitals(shelf)
    if "conversational_dialogue:hub" in tools:
        _dialogues(shelf, levels)
    if "reading_club:hub" in tools:
        _reading_club(shelf, levels)
    if "reference_library:home" in tools:
        _reference(shelf)
    if "quick_words:hub" in tools:
        _quick_words(shelf, levels)
    return shelf


def catalog(levels, tools):
    """build's pages and videos, kept for ten minutes: everyone on a level
    shares them."""
    key = "offline-catalog-" + _version(sorted(levels), sorted(tools))
    found = cache.get(key)
    if found is None:
        shelf = build(levels, tools)
        found = {"pages": shelf.pages, "videos": shelf.video_refs}
        cache.set(key, found, CACHE_SECONDS)
    return found


def levels_for(user):
    """The levels this person's app keeps: their own. Someone with none set
    (an individual learner with no level, for instance) can open every level,
    which won't fit on a device, so theirs keeps the shared tools only."""
    from apps.accounts.access import accessible_levels

    levels = accessible_levels(user)
    if levels is None:
        return [user.level] if user.level else []
    return list(levels)


def _library(user, tools):
    """A school's own books differ from school to school, so they're not
    in the shared list."""
    if "diction_library:hub" not in tools:
        return []
    from apps.diction_library.models import LibraryChapter
    from apps.diction_library.views import openable_items

    items = list(openable_items(user).values("id", "slug", "updated_at"))
    chapters = defaultdict(list)
    for row in LibraryChapter.objects.filter(item_id__in=[item["id"] for item in items]).values():
        chapters[row["item_id"]].append(row)
    return [{"p": reverse("diction_library:detail", args=[item["slug"]]), "v": _version(item["updated_at"], chapters[item["id"]])}
            for item in items]


def _open_tools(user):
    from apps.learning_tools.views import tools_for

    return {tool["url_name"] for tool in tools_for(user)}


def plan_ends(user):
    """When this person's access to the lessons ends: their own plan's end,
    or their school's. None when it doesn't end: staff, the paywall switched
    off, or an account with no plan to answer to. Only reads; the billing
    rules themselves are apps/billing."""
    from apps.billing.access import is_exempt, subscription_for
    from apps.billing.models import BillingSettings

    if is_exempt(user) or not BillingSettings.load().paywall_enabled:
        return None
    subscription = subscription_for(user)
    return subscription.access_until if subscription else None


def manifest(user):
    """The list one person's app syncs against.

    "offline_days" is how long the app may keep opening lessons with no
    internet after this check-in, and "access_ends" (milliseconds, like a
    browser's clock) is when their plan ends: the app closes its lessons at
    whichever comes first, connected or not. Once their access has ended,
    the app is told so and closes them at once (templates/pwa/sw.js, "access").

    A site update doesn't change a page's version: every learner fetching
    every page after every update would swamp the server, and a page keeps
    working offline because its stylesheets are kept with it. Raise
    OFFLINE_PAGES_VERSION when a change to the pages themselves has to
    reach every device."""
    from apps.billing.access import has_access

    if not has_access(user):
        return {"access": False, "offline_days": 0, "pages": [], "videos": []}
    tools = _open_tools(user)
    found = catalog(levels_for(user), tools)
    round_ = settings.OFFLINE_PAGES_VERSION
    ready = settings.STORAGE_CORS_READY
    return {
        "access": True,
        "offline_days": settings.OFFLINE_ACCESS_DAYS,
        "access_ends": int(ends.timestamp() * 1000) if (ends := plan_ends(user)) else None,
        "need_mb": settings.OFFLINE_MEDIA_NEED_MB,
        "pages": [{"p": page["p"], "v": f"{round_}.{page['v']}" if page["v"] else ""}
                  for page in [*found["pages"], *_library(user, tools)]],
        # Files in the storage bucket, and the videos saved from it, wait
        # until the bucket lets the apps read them (STORAGE_CORS_READY).
        "storage_media": ready,
        "videos": found["videos"] if ready else [],
    }


def may_keep_video(user, ref):
    """Is this one of the videos this person's app keeps?"""
    return ref in catalog(levels_for(user), _open_tools(user))["videos"]
