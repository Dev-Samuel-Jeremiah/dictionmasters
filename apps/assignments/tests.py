"""Teacher assignments: setting work for a class, done worked out from the
work itself, the pupil's home and bell, and who may see what."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.assessments.models import Assessment, Attempt
from apps.book.models import ACADEMY, Sound, SoundCategory, WordBankEntry
from apps.echospell.models import Group, GroupProgress, Level
from apps.learning_modules.models import Day, DayProgress, LearningModule, Term as ModuleTerm, Week
from apps.notifications import reminders
from apps.notifications.models import Notification
from apps.scheme.models import Session
from apps.schools.models import School, SchoolClass
from apps.tricks.models import LessonProgress

from . import progress
from .forms import work_choices
from .models import Assignment

User = get_user_model()


def person(email, **extra):
    return User.objects.create_user(email, "mango-river-47", first_name=email.split("@")[0].title(), **extra)


class AssignmentCase(TestCase):
    def setUp(self):
        self.session = Session.objects.create(name="2026/2027")
        self.school = School.objects.create(name="Unity", email="u@example.com")
        self.admin = person("head@example.com", role="school_admin", school=self.school)
        self.g1 = SchoolClass.objects.create(school=self.school, session=self.session, grade="primary_1", name="A")
        self.g3 = SchoolClass.objects.create(school=self.school, session=self.session, grade="primary_3", name="A")
        self.tola = person("tola@example.com", role="teacher", school=self.school)
        self.g1.teachers.add(self.tola)
        self.other = person("other@example.com", role="teacher", school=self.school)
        self.g3.teachers.add(self.other)
        self.ada = person("ada@example.com", role="student", school=self.school, level="Level 1", school_class=self.g1)
        self.bo = person("bo@example.com", role="student", school=self.school, level="Level 1", school_class=self.g1)
        level1, _ = Level.objects.update_or_create(name="Level 1", defaults={"is_published": True})
        level3, _ = Level.objects.update_or_create(name="Level 3", defaults={"is_published": True})
        self.group = Group.objects.create(level=level1, number=91, slug="as91")
        self.group3 = Group.objects.create(level=level3, number=92, slug="as92")
        self.test = Assessment.objects.create(title="Spelling test", kind="ca", level="Level 1", term=1, is_published=True)
        category = SoundCategory.objects.create(name="Vowels", programme=ACADEMY)
        self.sound = Sound.objects.create(category=category, name="Long a", slug="as-long-a", is_published=True)
        WordBankEntry.objects.create(sound=self.sound, word="cake")
        module = LearningModule.objects.create(name="Speak Up", slug="as-speak-up")
        week = Week.objects.create(term=ModuleTerm.objects.create(module=module, name="First Term"), number=1)
        self.day = Day.objects.create(week=week, day_name="monday")
        self.addCleanup(lambda: [reminders.forget(u.pk) for u in User.objects.all()])

    def set(self, kind, work, classes=None, due=None, **extra):
        field = {"group": "group", "module_day": "module_day", "sound": "lesson", "trick": "lesson", "test": "assessment"}[kind]
        made = Assignment.objects.create(school=self.school, created_by=self.tola, kind=kind,
                                         due_on=due or timezone.localdate() + timedelta(days=5), **{field: work}, **extra)
        made.classes.set(classes or [self.g1])
        return made


class SettingTests(AssignmentCase):
    def test_the_work_list_fits_the_grade(self):
        values = {v for _label, options in work_choices(["Level 1"]) for v, _text in options}
        self.assertIn(f"group:{self.group.pk}", values)
        self.assertNotIn(f"group:{self.group3.pk}", values)
        self.assertNotIn(f"sound:{self.sound.pk}", values)            # the 44 Academy starts at Grade 3
        self.assertIn(f"test:{self.test.pk}", values)
        self.assertIn(f"sound:{self.sound.pk}", {v for _l, o in work_choices(["Level 3"]) for v, _t in o})

    def test_setting_one_tells_the_pupils(self):
        self.client.force_login(self.tola)
        page = self.client.get("/school/assignments/new/")
        self.assertContains(page, "Grade 1 A")
        self.assertNotContains(page, "Grade 3 A")                      # not their class
        due = timezone.localdate() + timedelta(days=3)
        response = self.client.post("/school/assignments/new/", {"classes": [self.g1.pk], "work": f"group:{self.group.pk}",
                                                                 "due_on": due.isoformat(), "note": "Read it twice."})
        made = Assignment.objects.get()
        self.assertRedirects(response, f"/school/assignments/{made.pk}/")
        self.assertEqual((made.kind, made.group, made.created_by, made.note), ("group", self.group, self.tola, "Read it twice."))
        told = Notification.objects.filter(kind="assignment")
        self.assertEqual({n.user for n in told}, {self.ada, self.bo})
        self.assertEqual(told.first().url, f"/echospell/{self.group.level.slug}/{self.group.slug}/")

    def test_work_for_another_grade_is_refused(self):
        self.client.force_login(self.admin)
        page = self.client.post("/school/assignments/new/", {"classes": [self.g1.pk], "work": f"group:{self.group3.pk}",
                                                             "due_on": (timezone.localdate() + timedelta(days=2)).isoformat()})
        self.assertContains(page, "can&#x27;t be set this")
        self.assertFalse(Assignment.objects.exists())

    def test_a_due_date_in_the_past_is_refused(self):
        self.client.force_login(self.tola)
        page = self.client.post("/school/assignments/new/", {"classes": [self.g1.pk], "work": f"test:{self.test.pk}",
                                                             "due_on": (timezone.localdate() - timedelta(days=1)).isoformat()})
        self.assertContains(page, "Choose today or a day after")


class DoneTests(AssignmentCase):
    def test_each_kind_is_done_when_the_work_is(self):
        pupils = [self.ada.pk, self.bo.pk]
        group = self.set("group", self.group)
        GroupProgress.objects.create(user=self.ada, group=self.group)
        self.assertEqual(progress.done_ids(group, pupils), {self.ada.pk})
        day = self.set("module_day", self.day)
        DayProgress.objects.create(user=self.bo, day=self.day)
        self.assertEqual(progress.done_ids(day, pupils), {self.bo.pk})
        test = self.set("test", self.test)
        Attempt.objects.create(user=self.ada, assessment=self.test)                       # started, not handed in
        self.assertEqual(progress.done_ids(test, pupils), set())
        Attempt.objects.create(user=self.bo, assessment=self.test, status=Attempt.Status.SUBMITTED)
        self.assertEqual(progress.done_ids(test, pupils), {self.bo.pk})
        lesson = self.set("sound", self.sound, classes=[self.g3])
        LessonProgress.objects.create(user=self.ada, lesson=self.sound, tabs_seen=[])
        LessonProgress.objects.create(user=self.bo, lesson=self.sound, tabs_seen=["word-bank"])
        self.assertEqual(progress.done_ids(lesson, pupils), {self.bo.pk})

    def test_the_teacher_sees_who_has_done_it(self):
        made = self.set("group", self.group, due=timezone.localdate())
        GroupProgress.objects.create(user=self.ada, group=self.group)
        self.client.force_login(self.tola)
        listed = self.client.get("/school/assignments/")
        self.assertContains(listed, "1 of 2 done")
        page = self.client.get(f"/school/assignments/{made.pk}/")
        self.assertContains(page, "✓ Done")
        self.assertContains(page, "Not yet")
        self.assertContains(page, "Due today")


class WhoTests(AssignmentCase):
    def test_teachers_see_their_own_classes_work_and_admins_all(self):
        made = self.set("group", self.group)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(f"/school/assignments/{made.pk}/").status_code, 404)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(f"/school/assignments/{made.pk}/").status_code, 200)
        self.client.force_login(self.ada)
        self.assertEqual(self.client.get("/school/assignments/").status_code, 302)

    def test_change_and_delete(self):
        made = self.set("group", self.group)
        self.client.force_login(self.tola)
        later = timezone.localdate() + timedelta(days=9)
        self.client.post(f"/school/assignments/{made.pk}/", {"due_on": later.isoformat(), "note": "Take your time."})
        made.refresh_from_db()
        self.assertEqual((made.due_on, made.note), (later, "Take your time."))
        self.assertRedirects(self.client.post(f"/school/assignments/{made.pk}/", {"action": "delete"}), "/school/assignments/")
        self.assertFalse(Assignment.objects.exists())


class PupilTests(AssignmentCase):
    def test_the_home_lists_open_assignments_until_done(self):
        self.set("group", self.group, due=timezone.localdate() + timedelta(days=1))
        self.client.force_login(self.ada)
        home = self.client.get("/accounts/dashboard/")
        self.assertContains(home, "My assignments")
        self.assertContains(home, "Due tomorrow")
        GroupProgress.objects.create(user=self.ada, group=self.group)
        self.assertNotContains(self.client.get("/accounts/dashboard/"), "My assignments")

    def test_reminders_for_the_pupil_and_the_teacher(self):
        self.set("group", self.group, due=timezone.localdate() + timedelta(days=1))
        self.assertIn(f"Due tomorrow: EchoSpell Level 1, Group 91", [r["title"] for r in reminders.for_user(self.ada)])
        self.set("test", self.test, due=timezone.localdate())
        self.assertIn("2 pupils haven't done Spelling test", [r["title"] for r in reminders.for_user(self.tola)])
