"""A school admin moving and promoting their teachers and students."""

from django.test import TestCase

from apps.accounts.models import User

from .models import LevelChange, School


class LevelToolsTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="Unity School", email="unity@example.com")
        self.admin = User.objects.create_user("admin@example.com", "pw-12345678", first_name="Ada",
                                              role="school_admin", school=self.school)
        self.client.force_login(self.admin)

    def person(self, name, level="", role="student", school=None, additional=""):
        return User.objects.create_user(f"{name}@example.com", "pw-12345678", first_name=name.title(), role=role,
                                        school=school or self.school, level=level, additional_levels=additional)

    def bulk(self, people, action, level="", role="student"):
        return self.client.post("/school/members/levels/", {"members": [p.pk for p in people], "action": action,
                                                             "level": level, "role": role}, follow=True)

    def levels(self, *people):
        return [User.objects.get(pk=p.pk).level for p in people]

    def test_promote_moves_each_student_up_one_level(self):
        pre, three, top, none = (self.person("pre", "Pre-Level"), self.person("three", "Level 3"),
                                 self.person("top", "Level 12"), self.person("none"))
        response = self.bulk([pre, three, top, none], "promote")
        self.assertEqual(self.levels(pre, three, top, none), ["Level 1", "Level 4", "Level 12", ""])
        self.assertContains(response, "already in Level 12 stayed there")
        self.assertContains(response, "with no level yet was left")
        self.assertEqual(LevelChange.objects.count(), 2)

    def test_undo_puts_a_whole_promotion_back_except_people_moved_since(self):
        a, b = self.person("a", "Level 2"), self.person("b", "Level 5")
        self.bulk([a, b], "promote")
        batch = LevelChange.objects.first().batch
        self.client.post(f"/school/members/{b.pk}/level/", {"levels": ["Level 9"]})     # changed again
        response = self.client.post(f"/school/levels/undo/{batch}/", follow=True)
        self.assertEqual(self.levels(a, b), ["Level 2", "Level 9"])
        self.assertContains(response, "had been moved again since")
        self.assertTrue(LevelChange.objects.filter(batch=batch, undone_at__isnull=False).exists())

    def test_move_teachers_keeps_their_other_levels(self):
        teacher = self.person("tee", "Level 1", role="teacher", additional=",Level 3,Level 6,")
        self.bulk([teacher], "move", "Level 3", role="teacher")
        teacher.refresh_from_db()
        self.assertEqual((teacher.level, teacher.additional_levels_list), ("Level 3", ["Level 6"]))

    def test_a_teacher_can_be_given_several_levels(self):
        teacher = self.person("tee", "Level 4", role="teacher")
        self.client.post(f"/school/members/{teacher.pk}/level/", {"levels": ["Level 2", "Level 4", "Level 7"]})
        teacher.refresh_from_db()
        self.assertEqual(teacher.level, "Level 4")                      # still their main level
        self.assertEqual(teacher.all_levels, ["Level 2", "Level 4", "Level 7"])

    def test_a_student_has_one_level(self):
        student = self.person("stu", "Level 4")
        self.client.post(f"/school/members/{student.pk}/level/", {"levels": ["Level 6", "Level 8"]})
        student.refresh_from_db()
        self.assertEqual((student.level, student.additional_levels), ("Level 6", ""))

    def test_teachers_are_not_promoted_and_other_schools_are_untouched(self):
        other_school = School.objects.create(name="Elsewhere", email="else@example.com")
        outsider = self.person("out", "Level 2", school=other_school)
        teacher = self.person("tee", "Level 2", role="teacher")
        self.bulk([outsider], "promote")
        self.bulk([teacher], "promote", role="teacher")
        self.assertEqual(self.levels(outsider, teacher), ["Level 2", "Level 2"])

    def test_an_unknown_level_is_refused(self):
        student = self.person("stu", "Level 4")
        self.bulk([student], "move", "Level 99")
        self.assertEqual(self.levels(student), ["Level 4"])

    def test_only_school_admins_can_change_levels(self):
        student = self.person("stu", "Level 4")
        teacher = self.person("tee", "Level 4", role="teacher")
        self.client.force_login(teacher)
        self.bulk([student], "promote")
        self.assertEqual(self.levels(student), ["Level 4"])

    def test_the_dashboard_shows_the_tools_and_history(self):
        student = self.person("stu", "Level 4")
        self.bulk([student], "promote")
        response = self.client.get("/school/dashboard/")
        self.assertContains(response, "Promote to next level")
        self.assertContains(response, "Level 4 &rarr; Level 5")
        self.assertContains(response, "Undo")
