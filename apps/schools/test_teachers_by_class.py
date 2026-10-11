"""Phase C of classes: teachers work by the classes they teach, and the
end of the year moves classes up a grade (apps/schools/classes.py)."""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.access import is_pupil_of, pupils_of
from apps.assessments.models import Assessment, Attempt
from apps.assessments.views import can_mark, markable
from apps.scheme.models import Session

from . import classes
from .models import LevelChange, School, SchoolClass

User = get_user_model()


def person(email, **extra):
    return User.objects.create_user(email, "mango-river-47", first_name=email.split("@")[0].title(), **extra)


class ClassesCase(TestCase):
    def setUp(self):
        self.year = Session.objects.create(name="2026/2027")
        self.school = School.objects.create(name="Unity", email="u@example.com")
        self.admin = person("head@example.com", role="school_admin", school=self.school)
        self.gold = SchoolClass.objects.create(school=self.school, session=self.year, grade="primary_3", name="Gold")
        self.blue = SchoolClass.objects.create(school=self.school, session=self.year, grade="primary_3", name="Blue")
        self.ada = self.pupil("ada@example.com", self.gold)
        self.bo = self.pupil("bo@example.com", self.blue)
        self.tola = person("tola@example.com", role="teacher", school=self.school)
        self.gold.teachers.add(self.tola)

    def pupil(self, email, school_class):
        return person(email, role="student", school=self.school, level=school_class.level, school_class=school_class)


class TeacherTests(ClassesCase):
    def test_a_teacher_sees_only_the_classes_they_teach(self):
        self.assertEqual(list(pupils_of(self.tola)), [self.ada])          # not Blue, though it's Level 3 too
        self.assertTrue(is_pupil_of(self.tola, self.ada))
        self.assertFalse(is_pupil_of(self.tola, self.bo))
        taught = classes.class_ids_for([self.tola])
        with self.assertNumQueries(0):                                  # the weekly email's way: no queries
            self.assertTrue(is_pupil_of(self.tola, self.ada, taught[self.tola.pk]))

    def test_a_teacher_with_no_class_has_no_pupils(self):
        self.gold.teachers.remove(self.tola)
        self.assertFalse(pupils_of(self.tola).exists())

    def test_their_levels_follow_their_classes(self):
        self.tola.refresh_from_db()
        self.assertEqual((self.tola.level, self.tola.additional_levels), ("Level 3", ""))
        jss = SchoolClass.objects.create(school=self.school, session=self.year, grade="jss_1")
        jss.teachers.add(self.tola)
        self.tola.refresh_from_db()
        self.assertEqual((self.tola.level, self.tola.additional_levels), ("Level 3", ",Level 7,"))

    def test_a_new_teacher_joins_their_levels_classes(self):
        grace = person("grace@example.com", role="teacher", school=self.school, level="Level 3")
        self.assertEqual(set(grace.teaching_classes.all()), {self.gold, self.blue})
        musa = person("musa@example.com", role="teacher", school=self.school, level="Level 8")
        self.assertEqual([c.display_name for c in musa.teaching_classes.all()], ["JSS 2"])   # made for them

    def test_marking_follows_the_class(self):
        test = Assessment.objects.create(title="CA", kind="ca", level="Level 3", term=1)
        mine = Attempt.objects.create(user=self.ada, assessment=test, status=Attempt.Status.AWAITING)
        theirs = Attempt.objects.create(user=self.bo, assessment=test, status=Attempt.Status.AWAITING)
        self.assertEqual(list(markable(self.tola)), [mine])
        self.assertTrue(can_mark(self.tola, mine))
        self.assertFalse(can_mark(self.tola, theirs))

    def test_my_class_switches_between_classes(self):
        self.blue.teachers.add(self.tola)
        self.client.force_login(self.tola)
        page = self.client.get("/school/class/")
        self.assertContains(page, "All my classes")
        self.assertContains(page, f'href="?class={self.blue.pk}"')
        one = self.client.get(f"/school/class/?class={self.gold.pk}")
        self.assertEqual([r["pupil"] for r in one.context["rows"]], [self.ada])
        self.assertEqual(self.client.get(f"/school/class/{self.bo.pk}/").status_code, 200)
        self.blue.teachers.remove(self.tola)
        self.assertEqual(self.client.get(f"/school/class/{self.bo.pk}/").status_code, 404)


class PromotionTests(ClassesCase):
    def setUp(self):
        super().setUp()
        self.sss = SchoolClass.objects.create(school=self.school, session=self.year, grade="sss_3")
        self.cy = self.pupil("cy@example.com", self.sss)

    def test_within_the_year_ticked_students_move_up_and_sss_3_graduates(self):
        outcome = classes.promote(self.admin, self.school, [self.ada, self.cy])
        self.ada.refresh_from_db(), self.bo.refresh_from_db(), self.cy.refresh_from_db()
        self.assertEqual((self.ada.school_class.display_name, self.ada.level), ("Primary 4 Gold", "Level 4"))
        self.assertEqual(self.ada.school_class.session, self.year)
        self.assertEqual(self.bo.school_class, self.blue)                       # not ticked: stays
        self.assertFalse(self.cy.is_active)                                     # graduated
        self.assertEqual((len(outcome.promoted), len(outcome.graduated), len(outcome.stayed)), (1, 1, 1))
        self.assertIsNone(outcome.year)

    def test_into_the_next_year_classes_carry_over_with_their_teachers(self):
        later = Session.objects.create(name="2027/2028")
        self.assertEqual(classes.school_year(self.school), self.year)          # adding a year moves nobody
        outcome = classes.promote(self.admin, self.school, [self.ada])
        self.assertEqual(outcome.year, later)
        self.assertEqual(classes.school_year(self.school), later)
        names = {c.display_name for c in classes.this_year(self.school)}
        self.assertEqual(names, {"Primary 3 Gold", "Primary 3 Blue", "Primary 4 Gold", "SSS 3"})
        self.ada.refresh_from_db(), self.bo.refresh_from_db()
        self.assertEqual((self.ada.school_class.display_name, self.ada.school_class.session), ("Primary 4 Gold", later))
        self.assertEqual((self.bo.school_class.display_name, self.bo.school_class.session), ("Primary 3 Blue", later))
        # Tola stays with Primary 3 Gold, now next year's: Ada has moved on, so she isn't theirs.
        self.assertEqual([c.session for c in self.tola.teaching_classes.filter(session=later)], [later])
        self.assertFalse(pupils_of(self.tola).filter(pk=self.ada.pk).exists())

    def test_undo_puts_everyone_back_exactly(self):
        outcome = classes.promote(self.admin, self.school, [self.ada, self.cy])
        restored, skipped = classes.undo(self.admin, outcome.batch)
        self.assertEqual((len(restored), skipped), (2, []))               # Ada and Cy; Bo never moved
        self.ada.refresh_from_db(), self.cy.refresh_from_db()
        self.assertEqual((self.ada.school_class, self.ada.level), (self.gold, "Level 3"))
        self.assertTrue(self.cy.is_active)
        self.assertEqual(LevelChange.objects.filter(batch=outcome.batch, undone_at__isnull=True).count(), 0)

    def test_the_dashboards_undo_uses_classes_too(self):
        outcome = classes.promote(self.admin, self.school, [self.ada])
        self.client.force_login(self.admin)
        page = self.client.get("/school/dashboard/")
        self.assertContains(page, "Primary 3 Gold")
        self.client.post(f"/school/levels/undo/{outcome.batch}/")
        self.ada.refresh_from_db()
        self.assertEqual(self.ada.school_class, self.gold)

    def test_the_promote_page(self):
        self.client.force_login(self.admin)
        page = self.client.get("/scheme/promote/")
        self.assertContains(page, "Primary 3 Gold → Primary 4 Gold")
        self.assertContains(page, "SSS 3 → Graduates")
        self.assertContains(page, "The classes stay in this school year")
        self.client.post("/scheme/promote/", {"students": [self.ada.pk]})
        self.ada.refresh_from_db()
        self.assertEqual(self.ada.school_class.display_name, "Primary 4 Gold")
