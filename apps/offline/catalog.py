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
from django.core.exceptions import FieldError
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
        self.video_files = []          # (ref, stored file, title): what a lesson pack carries
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
                        ref = f"{ContentType.objects.get_for_model(queryset.model).pk}-{row['id']}"
                        self.video_refs.append(ref)
                        title = row.get("video_caption") or row.get("title") or row.get("name") or "Lesson video"
                        self.video_files.append((ref, row[field.attname], str(title)[:200]))
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
    if "tricks:home" in tools:
        # Tricks one section at a time (every lesson's Word Bank, say).
        from apps.tricks.progress import TAB_CONTENT

        for section in TAB_CONTENT:
            shelf.add(reverse("tricks:section", args=[section]))
    # The tests on offer and their results. Taking a test needs the
    # internet; seeing what there is, and how they did, doesn't.
    from apps.assessments.models import Assessment

    shelf.add(reverse("assessments:hub"))
    shelf.add(reverse("assessments:my_results"))
    for kind in Assessment.Kind.values:
        shelf.add(reverse("assessments:kind_list", args=[kind]))


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
    from apps.tricks.progress import TAB_CONTENT, lessons_in_order

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
    for lesson in lessons:
        version = _version(lesson.name, lesson.symbol, parts[lesson.pk])
        shelf.add(reverse(info["lesson"], args=[lesson.slug]), version)
        # Every tab, empty ones too: the section pages link them all, and an
        # empty one shows (or, in Tricks, sends them to) the lesson's first.
        for tab in TAB_CONTENT:
            shelf.add(reverse(info["lesson_tab"], args=[lesson.slug, tab]), version)
        # Every lesson has an Assessment tab, even before it has activities.
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
    item_count = defaultdict(int)
    for row in shelf.rows(LessonItem.objects.filter(is_published=True, day__in=days)):
        parts[row["day_id"]].append(row)
        item_days[row["id"]] = row["day_id"]
        item_count[row["day_id"]] += 1
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
        url = reverse("learning_modules:day_detail", args=[week.term.module.slug, week.term.slug, week.slug, day.day_name])
        version = _version(parts[day.pk])
        shelf.add(url, version)
        # A day shows one item per screen (?step=N) and ends on ?step=finish
        # (apps/learning_modules/lesson_path.py): each is its own page.
        if item_count[day.pk]:
            for number in range(1, item_count[day.pk] + 1):
                shelf.add(f"{url}?step={number}", version)
            shelf.add(f"{url}?step=finish", version)


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


MAX_CHOSEN_LEVELS = 3


def level_choices(user):
    """The levels this person may choose to keep on a device: for someone who
    can open every level (an admin, an individual learner with no level),
    which won't all fit on one. Empty for a learner whose levels are set:
    theirs are kept, nothing to choose."""
    from apps.accounts.access import LEVEL_ORDER, accessible_levels

    if accessible_levels(user) is not None:
        return []
    return [level for level in LEVEL_ORDER if level != user.level]


def worked_in(user):
    """The EchoSpell levels someone has been working in, most recent first:
    where they left off, and the cards they've opened. Two small lookups,
    asked on every page only by those who can open every level
    (apps/offline/context.py), so a level they start is offline soon."""
    from apps.accounts.access import LEVEL_ORDER
    from apps.echospell.models import CardPosition, GroupStepsSeen

    names = list(CardPosition.objects.filter(user=user).values_list("group__level__name", flat=True)[:1])
    names += list(GroupStepsSeen.objects.filter(user=user).order_by("-updated_at")
                  .values_list("group__level__name", flat=True)[:40])
    return [name for name in dict.fromkeys(names) if name in LEVEL_ORDER][:MAX_CHOSEN_LEVELS]


def levels_for(user, chosen=()):
    """The levels this person's app keeps: their own. Someone who can open
    every level keeps their own (if they have one) and the ones chosen on
    that device's Offline page, up to MAX_CHOSEN_LEVELS; with none chosen,
    the levels they've been working in (worked_in), so EchoSpell works
    offline without their having to find the setting."""
    from apps.accounts.access import LEVEL_ORDER, accessible_levels

    levels = accessible_levels(user)
    if levels is None:
        own = [user.level] if user.level else []
        picked = [level for level in dict.fromkeys(chosen) if level in LEVEL_ORDER] or worked_in(user)
        return own + [level for level in picked if level not in own][:MAX_CHOSEN_LEVELS]
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


def learner_secret(user):
    """The key a learner's pages and waiting progress are sealed with on
    their devices (templates/pwa/sw.js, "learners"): theirs alone, made from
    the site's secret, so it never needs storing and survives a password
    reset. Base64."""
    import base64
    import hmac
    from hashlib import sha256

    raw = hmac.new(settings.SECRET_KEY.encode(), f"dm-offline-learner:{user.pk}".encode(), sha256).digest()
    return base64.b64encode(raw).decode()


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


def access_info(user):
    """Whether this person's app may open saved lessons, for how long with no
    internet, and when their plan ends (see manifest). Sent with the list, and
    with the learner check a single "Save this page" makes (views.learner)."""
    from apps.billing.access import has_access

    if not has_access(user):
        return {"access": False, "offline_days": 0}
    return {
        "access": True,
        "offline_days": settings.OFFLINE_ACCESS_DAYS,
        "access_ends": int(ends.timestamp() * 1000) if (ends := plan_ends(user)) else None,
        # Files in the storage bucket, and the videos saved from it, wait
        # until the bucket lets the apps read them (STORAGE_CORS_READY).
        "storage_media": settings.STORAGE_CORS_READY,
    }


def manifest(user, chosen=()):
    """The list one person's app syncs against: their levels, with `chosen`
    for someone who can open every level (see levels_for).

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
    learner = {"id": user.pk, "secret": learner_secret(user)}
    access = access_info(user)
    if not access["access"]:
        return {**access, "learner": learner, "pages": [], "videos": []}
    tools = _open_tools(user)
    found = catalog(levels_for(user, chosen), tools)
    round_ = settings.OFFLINE_PAGES_VERSION
    return {
        **access,
        "learner": learner,
        "need_mb": settings.OFFLINE_MEDIA_NEED_MB,
        "pages": [{"p": page["p"], "v": f"{round_}.{page['v']}" if page["v"] else ""}
                  for page in [*found["pages"], *_library(user, tools)]],
        "videos": found["videos"] if access["storage_media"] else [],
    }


def may_keep_video(user, ref):
    """Is this one of the videos this person's app keeps? Someone who can open
    every level keeps whichever levels they choose on each device, so any
    lesson video may be theirs."""
    from apps.accounts.access import accessible_levels

    if accessible_levels(user) is None:
        try:
            content_type_id, _sep, pk = ref.partition("-")
            model = ContentType.objects.get_for_id(int(content_type_id)).model_class()
            return model is not None and model.objects.filter(pk=int(pk)).exclude(video_file="").exists()
        except (ValueError, LookupError, FieldError, ContentType.DoesNotExist):
            return False
    return ref in catalog(levels_for(user), _open_tools(user))["videos"]
