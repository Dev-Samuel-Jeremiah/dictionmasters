"""Control room access is for Diction Masters staff only (November 2026:
ten teachers had been given it by mistake, and one used it). A school
account can never be staff; only a superuser gives control room access or
changes a staff account; and the change history says which fields changed."""

from django.contrib.admin.models import LogEntry
from django.contrib.admin.sites import site
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import RequestFactory, TestCase

from apps.schools.models import School

User = get_user_model()


class StaffGuardTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="Unity", email="u@example.com")
        self.boss = User.objects.create_superuser("boss@example.com", "pw-12345678", first_name="Boss")
        self.helper = User.objects.create_user("helper@example.com", "pw-12345678", first_name="Helper", is_staff=True)
        self.teacher = User.objects.create_user("tola@example.com", "pw-12345678", first_name="Tola", role="teacher",
                                                school=self.school, level="Level 3", username="tola.t")

    def user_form(self, person, **changes):
        data = {"first_name": person.first_name, "last_name": person.last_name, "username": person.username or "",
                "email": person.email, "role": person.role, "school": person.school_id or "",
                "is_active": "on", "levels_taught": person.all_levels}
        data.update(changes)
        return {k: v for k, v in data.items() if v is not None}

    def test_a_school_account_is_never_staff(self):
        for role in ("teacher", "student", "school_admin"):
            with self.assertRaises(ValidationError):
                User.objects.create_user(f"{role}@example.com", "pw-12345678", first_name="X", role=role,
                                         school=self.school, is_staff=True)
        # Set any other way, it's still refused when saved.
        self.teacher.is_staff = True
        self.teacher.save()
        self.teacher.refresh_from_db()
        self.assertFalse(self.teacher.is_staff)
        User.objects.filter(pk=self.teacher.pk).update(is_staff=False)
        self.teacher.is_superuser = True
        self.teacher.save(update_fields=["is_superuser"])
        self.teacher.refresh_from_db()
        self.assertFalse(self.teacher.is_superuser)

    def test_ticking_staff_on_a_teacher_in_the_control_room_is_refused(self):
        self.client.force_login(self.boss)
        page = self.client.post(f"/manage/users/{self.teacher.pk}/", self.user_form(self.teacher, is_staff="on"))
        self.assertContains(page, "can&#x27;t have control room access")
        self.teacher.refresh_from_db()
        self.assertFalse(self.teacher.is_staff)
        # The box says what it's for.
        self.assertContains(self.client.get(f"/manage/users/{self.teacher.pk}/"), "Control room access (staff)")

    def test_only_a_superuser_gives_staff_or_changes_a_staff_account(self):
        self.client.force_login(self.helper)
        form = self.client.get(f"/manage/users/{self.teacher.pk}/")
        self.assertNotContains(form, 'name="is_staff"')                       # no box to tick
        other = User.objects.create_user("o@example.com", "pw-12345678", first_name="Other")
        self.client.post(f"/manage/users/{other.pk}/", self.user_form(other, is_staff="on"))
        other.refresh_from_db()
        self.assertFalse(other.is_staff)                                      # ignored: not a superuser
        refused = self.client.get(f"/manage/users/{self.boss.pk}/", follow=True)
        self.assertContains(refused, "Only a superuser can change or remove another staff account")
        self.client.post(f"/manage/users/{self.boss.pk}/delete/")
        self.assertTrue(User.objects.filter(pk=self.boss.pk).exists())
        self.client.post("/manage/users/delete-selected/", {"pk": [self.boss.pk], "confirm": "1"})
        self.assertTrue(User.objects.filter(pk=self.boss.pk).exists())
        # A superuser can.
        self.client.force_login(self.boss)
        self.client.post(f"/manage/users/{other.pk}/", self.user_form(other, is_staff="on"))
        other.refresh_from_db()
        self.assertTrue(other.is_staff)

    def test_the_history_says_which_fields_changed(self):
        self.client.force_login(self.boss)
        self.client.post(f"/manage/users/{self.teacher.pk}/",
                         self.user_form(self.teacher, first_name="Tolani", levels_taught=["Level 3", "Level 4"]))
        entry = LogEntry.objects.filter(object_id=str(self.teacher.pk)).latest("action_time")
        self.assertIn("First name", entry.change_message)
        self.assertIn("Levels", entry.change_message)
        self.assertNotIn("Tolani", entry.change_message)                     # names, never values

    def test_the_admin_site_guards_staff_accounts_too(self):
        admin = site._registry[User]
        request = RequestFactory().get("/admin/")
        request.user = self.helper
        self.assertIn("is_staff", admin.get_readonly_fields(request, self.teacher))
        self.assertFalse(admin.has_change_permission(request, self.boss))
        request.user = self.boss
        self.assertNotIn("is_staff", admin.get_readonly_fields(request, self.teacher))
