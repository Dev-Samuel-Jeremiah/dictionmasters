"""Level gating for every tool, and pages by age band (Phase 3): the rules
in apps/accounts/access.py and what each kind of pupil then sees."""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.diction_library.models import LibraryItem
from apps.learning_modules.models import Day, LearningModule, Term, Week
from apps.learning_tools.models import ToolLevels
from apps.reading_club.models import Book

from .access import age_band, can_use_tool, limit_to_level_list, pack_levels, unpack_levels
from .dashboard_data import todays_lesson

User = get_user_model()


def pupil(level, email=None, **extra):
    return User.objects.create_user(email or f"{level.replace(' ', '').lower()}@example.com", "pw-12345678",
                                    first_name="Ada", role="student", level=level, **extra)


class RuleTests(TestCase):
    def test_age_bands(self):
        bands = {level: age_band(pupil(level))["key"]
                 for level in ("Pre-Level", "Level 2", "Level 3", "Level 6", "Level 7", "Level 12")}
        self.assertEqual(bands, {"Pre-Level": "little", "Level 2": "little", "Level 3": "middle",
                                 "Level 6": "middle", "Level 7": "older", "Level 12": "older"})

    def test_only_students_with_a_level_have_a_band(self):
        teacher = User.objects.create_user("t@example.com", "pw-12345678", first_name="T", role="teacher", level="Level 1")
        solo = User.objects.create_user("s@example.com", "pw-12345678", first_name="S")
        self.assertIsNone(age_band(teacher))
        self.assertIsNone(age_band(solo))
        self.assertIsNone(age_band(pupil("", email="nolevel@example.com")))

    def test_levels_are_stored_in_order_and_level_1_never_matches_level_12(self):
        self.assertEqual(pack_levels(["Level 3", "Pre-Level"]), ",Pre-Level,Level 3,")
        self.assertEqual(unpack_levels(",Level 12,"), ["Level 12"])
        LearningModule.objects.all().delete()
        LearningModule.objects.create(name="Big", levels=",Level 12,")
        LearningModule.objects.create(name="Everyone")
        names = set(limit_to_level_list(LearningModule.objects.all(), pupil("Level 1")).values_list("name", flat=True))
        self.assertEqual(names, {"Everyone"})

    def test_tools_are_held_back_for_students_only(self):
        ToolLevels.objects.create(tool="reference_library:home", levels=",Level 7,")
        teacher = User.objects.create_user("t@example.com", "pw-12345678", first_name="T", role="teacher", level="Level 3")
        self.assertFalse(can_use_tool(pupil("Level 3"), "reference_library:home"))
        self.assertTrue(can_use_tool(pupil("Level 7"), "reference_library:home"))
        self.assertTrue(can_use_tool(teacher, "reference_library:home"))
        self.assertTrue(can_use_tool(pupil("Level 3", email="x@example.com"), "clash:hub"))


class ToolGatingTests(TestCase):
    def setUp(self):
        ToolLevels.objects.create(tool="reference_library:home", levels=",Level 7,Level 8,")

    def test_a_student_outside_the_levels_gets_a_friendly_page(self):
        self.client.force_login(pupil("Level 3"))
        page = self.client.get("/reference-library/")
        self.assertEqual(page.status_code, 403)
        self.assertContains(page, "Not for your level yet", status_code=403)
        self.assertContains(page, 'href="/learning-tools/"', status_code=403)

    def test_a_student_in_the_levels_and_everyone_else_get_in(self):
        teacher = User.objects.create_user("t@example.com", "pw-12345678", first_name="T", role="teacher", level="Level 3")
        solo = User.objects.create_user("s@example.com", "pw-12345678", first_name="S")
        for user in (pupil("Level 7"), teacher, solo):
            self.client.force_login(user)
            self.assertEqual(self.client.get("/reference-library/").status_code, 200, user.email)

    def test_a_held_back_tool_leaves_learn_and_search(self):
        self.client.force_login(pupil("Level 3"))
        shown = [t["url_name"] for s in self.client.get("/learning-tools/").context["sections"] for t in s["tools"]]
        self.assertNotIn("reference_library:home", shown)
        self.assertIn("echospell:hub", shown)
        from apps.platform_search.views import _search_items
        from django.test import RequestFactory

        request = RequestFactory().get("/")
        request.user = User.objects.get(level="Level 3")
        titles = [item["title"] for item in _search_items(request, "Reference")]
        self.assertNotIn("Reference Library", titles)

    def test_the_phonemic_chart_is_told_apart_from_the_44_academy(self):
        ToolLevels.objects.create(tool="book:home", levels=",Level 9,")
        self.client.force_login(pupil("Level 3"))
        self.assertEqual(self.client.get("/book/").status_code, 403)
        self.assertNotEqual(self.client.get("/book/phonemic-chart/").status_code, 403)

    def test_no_levels_ticked_means_open_to_all(self):
        ToolLevels.objects.filter(tool="reference_library:home").update(levels="")
        self.client.force_login(pupil("Level 3"))
        self.assertEqual(self.client.get("/reference-library/").status_code, 200)


class ContentGatingTests(TestCase):
    def setUp(self):
        LearningModule.objects.all().delete()
        self.three = pupil("Level 3")
        self.five = pupil("Level 5")

    def test_modules_for_another_level_are_hidden_and_shut(self):
        LearningModule.objects.create(name="For five", slug="for-five", levels=",Level 5,")
        LearningModule.objects.create(name="For all", slug="for-all")
        self.client.force_login(self.three)
        hub = self.client.get("/learning-modules/")
        self.assertContains(hub, "For all")
        self.assertNotContains(hub, "For five")
        self.assertEqual(self.client.get("/learning-modules/for-five/").status_code, 404)
        self.client.force_login(self.five)
        self.assertEqual(self.client.get("/learning-modules/for-five/").status_code, 200)

    def test_todays_lesson_only_offers_module_days_for_the_learners_level(self):
        from apps.echospell.models import Group

        Group.objects.all().delete()
        module = LearningModule.objects.create(name="For five", levels=",Level 5,")
        Day.objects.create(week=Week.objects.create(term=Term.objects.create(module=module, name="T"), number=1),
                           day_name="monday")
        self.assertEqual(todays_lesson(self.three)["kind"], "daily_practice")
        self.assertEqual(todays_lesson(self.five)["kind"], "modules")

    def test_reading_books_and_library_items_by_level(self):
        Book.objects.create(title="Big book", slug="big-book", levels=",Level 5,")
        LibraryItem.objects.create(title="Big story", slug="big-story", levels=",Level 5,")
        self.client.force_login(self.three)
        self.assertNotContains(self.client.get("/reading-club/"), "Big book")
        self.assertEqual(self.client.get("/reading-club/big-book/").status_code, 404)
        self.assertNotContains(self.client.get("/library/"), "Big story")
        self.assertEqual(self.client.get("/library/big-story/").status_code, 404)
        self.client.force_login(self.five)
        self.assertContains(self.client.get("/reading-club/"), "Big book")
        self.assertEqual(self.client.get("/library/big-story/").status_code, 200)

    def test_staff_tick_levels_in_the_control_room(self):
        staff = User.objects.create_user("staff@example.com", "pw-12345678", first_name="Sam", is_staff=True)
        self.client.force_login(staff)
        module = LearningModule.objects.create(name="Phonics", slug="phonics")
        form = self.client.get(f"/manage/modules/{module.pk}/")
        self.assertContains(form, 'value="Level 5"')
        self.client.post(f"/manage/modules/{module.pk}/", {
            "name": "Phonics", "slug": "phonics", "icon": module.icon, "color": module.color, "order": 0,
            "is_published": "on", "levels": ["Level 6", "Level 5"],
        })
        module.refresh_from_db()
        self.assertEqual(module.levels, ",Level 5,Level 6,")
        self.client.post("/manage/tool-levels/new/", {"tool": "clash:hub", "levels": ["Level 7"]})
        self.assertEqual(ToolLevels.objects.get(tool="clash:hub").levels, ",Level 7,")


class BandPageTests(TestCase):
    def home(self, user):
        self.client.force_login(user)
        return self.client.get("/accounts/dashboard/")

    def test_little_ones_get_two_picture_tiles(self):
        page = self.home(pupil("Level 1"))
        self.assertContains(page, "lh-more--pictures")
        self.assertContains(page, 'class="lh-more__link"', count=2)
        self.assertContains(page, "<b>Grown-ups</b>", html=False)

    def test_the_middle_band_keeps_the_simple_home(self):
        page = self.home(pupil("Level 4"))
        self.assertNotContains(page, "lh-more--pictures")
        self.assertContains(page, 'class="lh-more__link"', count=2)

    def test_older_pupils_get_four_tiles_unless_a_tool_is_held_back(self):
        page = self.home(pupil("Level 9"))
        self.assertContains(page, 'class="lh-more__link"', count=4)
        self.assertContains(page, 'href="/clash/" class="lh-more__link"')
        ToolLevels.objects.create(tool="clash:hub", levels=",Level 12,")
        page = self.home(pupil("Level 9", email="other9@example.com"))
        self.assertContains(page, 'class="lh-more__link"', count=3)
        self.assertNotContains(page, 'href="/clash/" class="lh-more__link"')

    def test_learn_by_band(self):
        self.client.force_login(pupil("Level 1"))
        little = self.client.get("/learning-tools/")
        self.assertEqual([s["key"] for s in little.context["sections"]], ["courses", "practise"])
        self.assertNotContains(little, "Spelling and phonics by level")
        self.assertNotContains(little, "The Etiquette Advantage")

        self.client.force_login(pupil("Level 4"))
        middle = self.client.get("/learning-tools/")
        self.assertContains(middle, 'class="lt-short"')
        self.assertIn("read", [s["key"] for s in middle.context["sections"]])

        teacher = User.objects.create_user("t@example.com", "pw-12345678", first_name="T", role="teacher", level="Level 1")
        self.client.force_login(teacher)
        full = self.client.get("/learning-tools/")
        self.assertNotContains(full, "lt-short")
        self.assertContains(full, "Spelling and phonics by level")
        self.assertIn("teachers", [s["key"] for s in full.context["sections"]])
