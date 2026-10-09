"""The scheme of work decides what a student sees and may open: only the
week they're in (today first), the weeks before to go back to, nothing
later — and with no scheme this term, an empty page."""

from datetime import date

from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.diction_library.models import LibraryItem
from apps.echospell.models import Group, GroupProgress, Level

from .calendar import weeks_in
from .models import SchemeEntry, SchemeOpened, Term
from .tests import YearTestCase, make
from .timetable import class_week, past_weeks, timetable

User = get_user_model()

TUESDAY_WEEK_1 = date(2026, 9, 8)
TUESDAY_WEEK_2 = date(2026, 9, 15)


class TimetableCase(YearTestCase):
    def setUp(self):
        super().setUp()
        Group.objects.all().delete()
        self.level, _ = Level.objects.update_or_create(name="Level 2", defaults={"is_published": True})
        self.g1, self.g2, self.g3 = [Group.objects.create(level=self.level, number=n, slug=f"t{n}") for n in (1, 2, 3)]
        self.story = LibraryItem.objects.create(title="The Fox", slug="the-fox")
        add = lambda week, day, **kw: SchemeEntry.objects.create(level="Level 2", term=1, week=week, day=day, **kw)
        self.e_g1 = add(1, "monday", kind="group", group=self.g1)
        self.e_story = add(1, "tuesday", kind="library", library_item=self.story)
        self.e_g2 = add(2, "monday", kind="group", group=self.g2)
        self.e_g3 = add(3, "monday", kind="group", group=self.g3)


class StudentViewTests(TimetableCase):
    def test_this_week_today_first(self):
        week = timetable(self.ada, TUESDAY_WEEK_1)
        self.assertEqual((week["state"], week["week"], week["total"]), ("week", 1, 2))
        self.assertEqual([r["title"] for r in week["today_rows"]], ["The Fox"])
        self.assertEqual(week["next"]["title"], "The Fox")

    def test_done_follows_each_tool_and_opening(self):
        GroupProgress.objects.create(user=self.ada, group=self.g1)
        SchemeOpened.objects.create(user=self.ada, entry=self.e_story)
        week = timetable(self.ada, TUESDAY_WEEK_1)
        self.assertEqual(week["done"], 2)
        self.assertIsNone(week["next"])

    def test_the_dashboard_is_the_week(self):
        self.client.force_login(self.ada)
        with self.on(TUESDAY_WEEK_1):
            page = self.client.get("/accounts/dashboard/")
        self.assertTemplateUsed(page, "scheme/home.html")
        self.assertContains(page, "First Term · Week 1 · Tuesday")
        self.assertContains(page, "The Fox")                       # today's lesson
        # No Today / This week lists: one My weeks card instead.
        self.assertNotContains(page, "<h2>Today</h2>", html=False)
        self.assertNotContains(page, "<h2>This week</h2>", html=False)
        self.assertContains(page, 'href="/scheme/weeks/" class="px-card sh-weeks-card"')
        self.assertContains(page, 'href="/accounts/grown-ups/"')
        self.assertContains(page, "This week: 0 of 2 done")
        self.assertNotContains(page, "EchoSpell Group 2")

    def test_no_scheme_this_term_is_an_empty_page(self):
        five = make("five@example.com", role="student", school=self.school, level="Level 5")
        self.client.force_login(five)
        with self.on(TUESDAY_WEEK_1):
            page = self.client.get("/accounts/dashboard/")
        self.assertContains(page, "data-scheme-empty")
        self.assertContains(page, "Your lessons for this term are not ready yet.")
        self.assertNotContains(page, "data-scheme-next")
        self.assertNotContains(page, "sh-practise")

    def test_break_and_holiday(self):
        self.assertEqual(timetable(self.ada, date(2026, 10, 27))["state"], "break")
        self.assertEqual(timetable(self.ada, date(2026, 12, 20))["state"], "holiday")

    def test_past_weeks_never_show_what_is_to_come(self):
        weeks = past_weeks(self.ada, TUESDAY_WEEK_2)
        self.assertEqual([(w["term"], w["week"], w["is_current"]) for w in weeks], [(1, 2, True), (1, 1, False)])
        self.client.force_login(self.ada)
        with self.on(TUESDAY_WEEK_2):
            self.assertContains(self.client.get("/scheme/weeks/1/1/"), "The Fox")
            self.assertEqual(self.client.get("/scheme/weeks/1/3/").status_code, 404)
        # After the term, every week of it can be gone back to.
        self.assertEqual(len(past_weeks(self.ada, date(2026, 12, 20))), 3)

    def test_go_notes_the_opening_and_only_for_reached_weeks(self):
        self.client.force_login(self.ada)
        with self.on(TUESDAY_WEEK_1):
            self.assertRedirects(self.client.get(f"/scheme/go/{self.e_story.pk}/"), "/library/the-fox/",
                                 fetch_redirect_response=False)
            self.assertEqual(self.client.get(f"/scheme/go/{self.e_g2.pk}/").status_code, 404)
        self.assertTrue(SchemeOpened.objects.filter(user=self.ada, entry=self.e_story).exists())


class GateTests(TimetableCase):
    def get(self, user, url, day=TUESDAY_WEEK_1):
        self.client.force_login(user)
        with self.on(day):
            return self.client.get(url)

    def test_only_reached_weeks_open(self):
        self.assertEqual(self.get(self.ada, "/echospell/level-2/t1/").status_code, 200)
        later = self.get(self.ada, "/echospell/level-2/t2/")
        self.assertContains(later, "This comes later", status_code=403)
        self.assertEqual(self.get(self.ada, "/echospell/level-2/t2/", TUESDAY_WEEK_2).status_code, 200)
        self.assertEqual(self.get(self.ada, "/library/the-fox/").status_code, 200)

    def test_hubs_lead_to_my_weeks(self):
        for url in ("/echospell/", "/learning-tools/", "/book/", "/tricks/", "/learning-modules/"):
            self.assertRedirects(self.get(self.ada, url), "/scheme/weeks/", fetch_redirect_response=False, msg_prefix=url)

    def test_what_the_scheme_does_not_schedule_is_open(self):
        for url in ("/assembly-recitals/", "/conversational-dialogue/", "/reading-club/", "/daily-practice/",
                    "/assessments/", "/reference-library/", "/radio/", "/learning-tools/book-scanner/"):
            response = self.get(self.ada, url)
            self.assertNotEqual(response.status_code, 403, url)
            self.assertNotEqual(response.get("Location"), "/scheme/weeks/", url)
        self.client.force_login(self.ada)
        with self.on(TUESDAY_WEEK_1):
            side = self.client.get("/scheme/weeks/")
        self.assertContains(side, "More to explore")
        self.assertContains(side, 'href="/assembly-recitals/"')

    def test_practice_tools_stay_open(self):
        for url in ("/clash/", "/quick-words/", "/book/phonemic-chart/", "/tutor/"):
            self.assertNotEqual(self.get(self.ada, url).status_code, 403, url)

    def test_teachers_individuals_and_students_without_a_school_are_free(self):
        solo = make("solo@example.com", level="Level 2")
        loose = make("loose@example.com", role="student", level="Level 2")
        for user in (self.teacher, solo, loose):
            self.assertEqual(self.get(user, "/echospell/level-2/t3/").status_code, 200, user.email)


class TeacherTests(TimetableCase):
    def test_my_class_shows_the_week_and_each_pupils_share(self):
        GroupProgress.objects.create(user=self.ada, group=self.g1)
        self.client.force_login(self.teacher)
        with self.on(TUESDAY_WEEK_1):
            page = self.client.get("/school/class/")
        self.assertContains(page, "This week's scheme")
        self.assertContains(page, "The Fox")
        self.assertContains(page, "This week: 1 of 2 done")

    def test_a_whole_class_costs_the_same(self):
        with CaptureQueriesContext(connection) as few:
            class_week(self.teacher, "Level 2", [self.ada, self.ben], TUESDAY_WEEK_1)
        many = [make(f"kid{n}@example.com", role="student", school=self.school, level="Level 2") for n in range(10)]
        with CaptureQueriesContext(connection) as lots:
            class_week(self.teacher, "Level 2", [self.ada, self.ben, *many], TUESDAY_WEEK_1)
        self.assertEqual(len(few), len(lots))


class EditorTests(TimetableCase):
    url = "/manage/scheme-of-work/"

    def setUp(self):
        super().setUp()
        self.client.force_login(make("staff@example.com", is_staff=True))
        self.base = {"level": "Level 2", "term": "1"}

    def test_the_timetable_and_adding_to_it(self):
        page = self.client.get(self.url + "?level=Level 2&term=1")
        self.assertContains(page, "EchoSpell Group 1")
        self.assertContains(page, "4 entries this term")
        self.client.post(self.url, {**self.base, "action": "add", "week": "4", "day": "friday", "content": "daily_practice:"})
        self.assertTrue(SchemeEntry.objects.filter(week=4, day="friday", kind="daily_practice").exists())

    def test_filling_the_weeks(self):
        SchemeEntry.objects.all().delete()
        self.client.post(self.url, {**self.base, "action": "fill", "set": "groups", "start_week": "5",
                                    "pace": "week", "day": "monday", "start_at": "2"})
        self.assertEqual(list(SchemeEntry.objects.order_by("week").values_list("week", "group__number")), [(5, 2), (6, 3)])
        self.client.post(self.url, {**self.base, "action": "fill", "set": "groups", "start_week": "1", "pace": "day"})
        self.assertEqual(list(SchemeEntry.objects.filter(week=1).order_by("pk").values_list("day", "group__number")),
                         [("monday", 1), ("tuesday", 2), ("wednesday", 3)])

    def test_moving_removing_and_clearing(self):
        second = SchemeEntry.objects.create(level="Level 2", term=1, week=1, day="monday", kind="group",
                                            group=self.g3, order=5)
        self.client.post(self.url, {**self.base, "action": "up", "entry": second.pk})
        self.assertEqual(list(SchemeEntry.objects.filter(week=1, day="monday").order_by("order")
                              .values_list("pk", flat=True)), [second.pk, self.e_g1.pk])
        self.client.post(self.url, {**self.base, "action": "remove", "entry": second.pk})
        self.assertFalse(SchemeEntry.objects.filter(pk=second.pk).exists())
        self.client.post(self.url, {**self.base, "action": "clear"})
        self.assertFalse(SchemeEntry.objects.filter(level="Level 2", term=1).exists())

    def test_only_staff(self):
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(self.url).status_code, 302)


class SeedDemoTests(TimetableCase):
    def test_every_school_day_of_the_year_is_filled_and_it_can_be_removed(self):
        from io import StringIO

        from django.core.management import call_command

        from apps.assessments.models import Assessment
        from apps.schools.models import School

        Term.objects.all().delete()
        out = StringIO()
        call_command("seed_scheme_demo", "--level", "Level 2", stdout=out)
        terms = list(Term.objects.order_by("starts"))
        self.assertEqual([t.number for t in terms], [1, 2, 3])
        for term in terms:
            for week in range(1, weeks_in(term) + 1):
                days = set(SchemeEntry.objects.filter(level="Level 2", term=term.number, week=week)
                           .values_list("day", flat=True))
                self.assertTrue({"monday", "tuesday", "wednesday", "thursday", "friday"} <= days, (term, week))
        self.assertEqual(Assessment.objects.filter(slug__startswith="demo-scheme-level-2-").count(), 9)
        self.assertEqual(User.objects.filter(school__name="Demo Scheme School", level="Level 2").count(), 3)
        self.assertIn("DemoScheme-2026", out.getvalue())
        # Again: rebuilt, not doubled.
        first = SchemeEntry.objects.count()
        call_command("seed_scheme_demo", "--level", "Level 2", stdout=StringIO())
        self.assertEqual(SchemeEntry.objects.count(), first)
        call_command("seed_scheme_demo", "--level", "Level 2", "--remove", stdout=StringIO())
        self.assertFalse(SchemeEntry.objects.filter(level="Level 2").exists())
        self.assertFalse(School.objects.filter(name="Demo Scheme School").exists())


class TeachingPlanTests(TimetableCase):
    MONDAY_WEEK_1 = date(2026, 9, 7)

    def page(self, user=None, day=None, query=""):
        self.client.force_login(user or self.teacher)
        with self.on(day or self.MONDAY_WEEK_1):
            return self.client.get("/scheme/teach/" + query)

    def test_the_whole_term_with_dates_including_weeks_to_come(self):
        page = self.page()
        self.assertContains(page, "Week 1")
        self.assertContains(page, "7 Sep – 11 Sep")
        self.assertContains(page, "This week")
        self.assertContains(page, "EchoSpell Group 3")                  # Week 3, still to come
        self.assertContains(page, 'href="/echospell/level-2/t3/"')     # open it to prepare
        self.assertContains(page, "Mid-term break: 26 Oct – 30 Oct")

    def test_prepare_for_the_next_school_day(self):
        page = self.page()
        self.assertContains(page, "Prepare for Tuesday 8 September")
        self.assertContains(page, "The Fox")
        # On a Friday, the next school day is Monday.
        self.assertContains(self.page(day=date(2026, 9, 11)), "Prepare for Monday 14 September")

    def test_how_the_class_is_getting_on(self):
        GroupProgress.objects.create(user=self.ada, group=self.g1)
        page = self.page()
        self.assertContains(page, "1 of 2 done")                        # Group 1: Ada, not Ben
        self.assertContains(page, "0 of 2 done")                        # The Fox
        # Weeks to come have no counts yet.
        self.assertEqual(page.content.decode().count(" of 2 done"), 2)

    def test_linked_from_my_class_and_home(self):
        self.client.force_login(self.teacher)
        with self.on(self.MONDAY_WEEK_1):
            self.assertContains(self.client.get("/school/class/"), "data-teaching-plan")
            self.assertContains(self.client.get("/accounts/dashboard/"), "data-teaching-plan")

    def test_only_teachers(self):
        self.assertRedirects(self.page(user=self.ada), "/", fetch_redirect_response=False)

    def test_a_bigger_class_costs_the_same(self):
        from .timetable import term_plan

        with CaptureQueriesContext(connection) as few:
            term_plan(self.teacher, "Level 2", 1, [self.ada, self.ben], self.MONDAY_WEEK_1)
        more = [make(f"k{n}@example.com", role="student", school=self.school, level="Level 2") for n in range(10)]
        with CaptureQueriesContext(connection) as lots:
            term_plan(self.teacher, "Level 2", 1, [self.ada, self.ben, *more], self.MONDAY_WEEK_1)
        self.assertEqual(len(few), len(lots))


class StudentLibraryTests(TimetableCase):
    def test_the_diction_library_is_in_the_sidebar_and_open(self):
        self.client.force_login(self.ada)
        with self.on(TUESDAY_WEEK_1):
            page = self.client.get("/accounts/dashboard/")
            side = page.content.decode()
            side = side[side.index('<nav class="px-side__nav">'):side.index("</nav>", side.index('<nav class="px-side__nav">'))]
            self.assertEqual(side.count('href="/library/"'), 1)
            self.assertEqual(self.client.get("/library/").status_code, 200)
            self.assertEqual(self.client.get("/library/the-fox/").status_code, 200)
            # Everything else the scheme keeps is still kept.
            self.assertContains(self.client.get("/echospell/level-2/t3/"), "This comes later", status_code=403)

    def test_a_student_without_a_school_sees_it_once_too(self):
        loose = make("loose@example.com", role="student", level="Level 2")
        self.client.force_login(loose)
        html = self.client.get("/learning-tools/").content.decode()
        side = html[html.index('<nav class="px-side__nav">'):html.index("</nav>", html.index('<nav class="px-side__nav">'))]
        self.assertEqual(side.count('href="/library/"'), 1)


class SchoolOnlyLibraryTests(TimetableCase):
    """A school's students see only their school's own books."""

    def setUp(self):
        super().setUp()
        self.ours = LibraryItem.objects.create(title="Our school play", slug="our-play", school=self.school)
        self.shared = LibraryItem.objects.create(title="Shared story", slug="shared-story")

    def test_the_library_lists_their_schools_books_only(self):
        self.client.force_login(self.ada)
        with self.on(TUESDAY_WEEK_1):
            hub = self.client.get("/library/")
            self.assertContains(hub, "Our school play")
            self.assertNotContains(hub, "Shared story")
            self.assertNotContains(hub, "The Fox")                    # shared, even though it's on the scheme
            self.assertEqual(self.client.get("/library/our-play/").status_code, 200)
            self.assertEqual(self.client.get("/library/shared-story/").status_code, 404)
            # A shared book on their scheme still opens from its lesson.
            self.assertEqual(self.client.get("/library/the-fox/").status_code, 200)

    def test_search_finds_their_schools_books_only(self):
        from django.test import RequestFactory

        from apps.platform_search.views import _search_items

        request = RequestFactory().get("/")
        request.user = self.ada
        self.assertIn("Our school play", [item["title"] for item in _search_items(request, "play")])
        self.assertNotIn("Shared story", [item["title"] for item in _search_items(request, "story")])

    def test_teachers_still_see_both(self):
        self.client.force_login(self.teacher)
        hub = self.client.get("/library/")
        self.assertContains(hub, "Our school play")
        self.assertContains(hub, "Shared story")
