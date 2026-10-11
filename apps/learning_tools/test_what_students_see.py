"""What each grade's students see: the 44 Academy from Grade 3 (Level 3)
up, menus that leave out what a student can't open, and the control
room's What students see grid that changes it."""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.access import can_use_tool, tool_levels
from apps.schools.models import School

from .middleware import tool_for_path
from .models import ToolLevels

User = get_user_model()


def person(email, **extra):
    return User.objects.create_user(email, "mango-river-47", first_name=email.split("@")[0].title(), **extra)


class GradeToolsCase(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="Unity", email="u@example.com")
        self.p2 = person("p2@example.com", role="student", school=self.school, level="Level 2")
        self.p3 = person("p3@example.com", role="student", school=self.school, level="Level 3")
        self.tiny = person("tiny@example.com", role="student", school=self.school, level="Pre-Level")


class The44AcademyTests(GradeToolsCase):
    def test_it_starts_at_primary_3(self):
        kept = tool_levels()
        self.assertFalse(can_use_tool(self.tiny, "book:home", kept))
        self.assertFalse(can_use_tool(self.p2, "book:home", kept))
        self.assertTrue(can_use_tool(self.p3, "book:home", kept))
        self.assertTrue(can_use_tool(person("ss3@example.com", role="student", school=self.school, level="Level 12"),
                                     "book:home", kept))

    def test_its_pages_are_closed_below_primary_3(self):
        self.client.force_login(self.p2)
        for url in ("/book/", "/book/44-academy/"):
            self.assertEqual(self.client.get(url).status_code, 403, url)
        self.assertEqual(self.client.get("/book/phonemic-chart/").status_code, 200)    # a tool of its own
        self.assertIsNone(tool_for_path("/book/read-along/abc123/"))                  # audio books' timings
        self.client.force_login(self.p3)
        self.assertEqual(self.client.get("/book/").status_code, 200)

    def test_only_students_are_held_back(self):
        for who in (person("solo@example.com", role="individual", level="Level 1"),
                    person("tola@example.com", role="teacher", school=self.school, level="Level 1")):
            self.client.force_login(who)
            self.assertEqual(self.client.get("/book/").status_code, 200, who.role)

    def test_menus_and_learn_leave_it_out(self):
        self.client.force_login(self.p2)
        home = self.client.get("/accounts/dashboard/")
        self.assertNotContains(home, 'href="/book/"')
        self.assertContains(home, 'href="/tricks/"')                                  # everything else is there
        learn = self.client.get("/learning-tools/").context["sections"]
        self.assertNotIn("book:home", [t["url_name"] for section in learn for t in section["tools"]])
        self.client.force_login(self.p3)
        self.assertContains(self.client.get("/accounts/dashboard/"), 'href="/book/"')


class GridTests(GradeToolsCase):
    url = "/manage/what-students-see/"

    def setUp(self):
        super().setUp()
        self.client.force_login(person("staff@example.com", is_staff=True))

    def test_the_grid_shows_tools_by_grade(self):
        page = self.client.get(self.url)
        self.assertContains(page, "<span>Grade 3</span>", html=True)
        self.assertContains(page, "<span>Pre-School</span>", html=True)
        self.assertContains(page, 'name="book:home|Level 3" checked')
        self.assertNotContains(page, 'name="book:home|Level 2" checked')
        self.assertContains(page, 'name="clash:hub|Level 1" checked')
        self.assertNotContains(page, "lesson_audio:hub|")                            # teachers' own tool
        self.assertContains(self.client.get("/manage/"), 'href="/manage/what-students-see/"')

    def ticks(self, **chosen):
        """Every box as it is now, changed by {tool: [levels]}."""
        page = self.client.get(self.url)
        data = {}
        for row in page.context["table"]:
            name = row["tool"]["url_name"]
            for cell in row["cells"]:
                if (cell["level"] in chosen[name]) if name in chosen else cell["open"]:
                    data[f"{name}|{cell['level']}"] = "on"
        return data

    def test_unticking_a_grade_keeps_the_tool_from_it(self):
        everyone_but_pre = [f"Level {n}" for n in range(1, 13)]
        self.client.post(self.url, self.ticks(**{"reference_library:home": everyone_but_pre}))
        self.assertFalse(can_use_tool(self.tiny, "reference_library:home", tool_levels()))
        self.assertTrue(can_use_tool(self.p2, "reference_library:home", tool_levels()))

    def test_every_box_ticked_removes_the_limit(self):
        every = ["Pre-Level"] + [f"Level {n}" for n in range(1, 13)]
        self.client.post(self.url, self.ticks(**{"book:home": every}))
        self.assertFalse(ToolLevels.objects.filter(tool="book:home").exists())
        self.assertTrue(can_use_tool(self.p2, "book:home", tool_levels()))

    def test_a_tool_cant_be_closed_to_every_grade(self):
        page = self.client.post(self.url, self.ticks(**{"clash:hub": []}), follow=True)
        self.assertContains(page, "Keep at least one grade ticked for Diction Clash")
        self.assertTrue(can_use_tool(self.p2, "clash:hub", tool_levels()))
