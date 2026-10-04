"""Forgotten and changed passwords, for every kind of account."""

import re

from django.core import mail
from django.core.cache import cache
from django.test import TestCase

from apps.accounts.models import PasswordHelpRequest, User
from apps.schools.models import School


class PasswordTests(TestCase):
    def setUp(self):
        cache.clear()
        self.school = School.objects.create(name="Unity School", email="unity@example.com")
        self.teacher = User.objects.create_user("teacher@example.com", "Old-pass-word-1", first_name="Tola",
                                                role="teacher", school=self.school)
        self.student = User.objects.create_user("sade@students.dictionmasters.app", "mango47", first_name="Sade",
                                                role="student", school=self.school, username="sade.k")
        self.admin = User.objects.create_user("admin@example.com", "Admin-pass-99", first_name="Ada",
                                              role="school_admin", school=self.school)

    def forgot(self, who):
        return self.client.post("/accounts/password/forgot/", {"who": who})

    def link_in(self, message):
        return re.search(r"https?://[^\s]+/accounts/password/reset/[^\s]+/", message.body).group(0)

    def test_someone_with_an_email_resets_by_link_and_is_logged_in(self):
        self.assertRedirects(self.forgot("TEACHER@example.com"), "/accounts/password/forgot/sent/")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["teacher@example.com"])
        link = self.link_in(mail.outbox[0]).split("://", 1)[1].split("/", 1)[1]
        page = self.client.get("/" + link, follow=True)              # Django swaps the token for a session key
        self.assertContains(page, "Choose a new password")
        response = self.client.post(page.redirect_chain[-1][0], {"new_password1": "River-gate-77", "new_password2": "River-gate-77"})
        self.assertEqual(response.status_code, 302)
        self.teacher.refresh_from_db()
        self.assertTrue(self.teacher.check_password("River-gate-77"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.teacher.pk)
        # The link works once.
        self.client.logout()
        again = self.client.get("/" + link, follow=True)
        self.assertContains(again, "This link has expired")

    def test_a_student_without_an_email_asks_their_school_admin(self):
        self.assertRedirects(self.forgot("Sade.K"), "/accounts/password/forgot/sent/")
        self.assertEqual(len(mail.outbox), 0)
        request = PasswordHelpRequest.objects.get(user=self.student)
        self.assertEqual(request.school, self.school)
        self.forgot("sade.k")                                          # asking again doesn't pile up
        self.assertEqual(PasswordHelpRequest.objects.count(), 1)
        self.client.force_login(self.admin)
        self.assertContains(self.client.get("/school/dashboard/"), "1 person needs a new password")
        # The admin resets it: the request is answered.
        from apps.schools import logins

        logins.reset(self.admin, self.student)
        request.refresh_from_db()
        self.assertIsNotNone(request.resolved_at)
        self.assertNotContains(self.client.get("/school/dashboard/"), "needs a new password")

    def test_the_answer_is_the_same_whether_or_not_an_account_exists(self):
        self.assertRedirects(self.forgot("nobody@example.com"), "/accounts/password/forgot/sent/")
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(PasswordHelpRequest.objects.exists())

    def test_requests_are_limited(self):
        for _ in range(4):
            self.forgot("teacher@example.com")
        self.assertEqual(len(mail.outbox), 3)                          # three emails an hour for one account

    def test_a_weak_new_password_is_refused(self):
        self.forgot("teacher@example.com")
        link = self.link_in(mail.outbox[0]).split("://", 1)[1].split("/", 1)[1]
        page = self.client.get("/" + link, follow=True)
        response = self.client.post(page.redirect_chain[-1][0], {"new_password1": "12345678", "new_password2": "12345678"})
        self.assertEqual(response.status_code, 200)
        self.teacher.refresh_from_db()
        self.assertTrue(self.teacher.check_password("Old-pass-word-1"))

    def test_signed_in_people_change_their_password_and_stay_logged_in(self):
        self.client.force_login(self.teacher)
        response = self.client.post("/accounts/password/change/", {
            "old_password": "Old-pass-word-1", "new_password1": "Sunrise-lake-42", "new_password2": "Sunrise-lake-42"})
        self.assertEqual(response.status_code, 302)
        self.teacher.refresh_from_db()
        self.assertTrue(self.teacher.check_password("Sunrise-lake-42"))
        self.assertEqual(self.client.get("/accounts/password/change/").status_code, 200)   # still signed in
        wrong = self.client.post("/accounts/password/change/", {
            "old_password": "nope", "new_password1": "Another-one-55", "new_password2": "Another-one-55"})
        self.assertEqual(wrong.status_code, 200)

    def test_the_login_page_and_menu_link_to_them(self):
        self.assertContains(self.client.get("/accounts/login/"), "/accounts/password/forgot/")
        self.client.force_login(self.teacher)
        self.assertContains(self.client.get("/accounts/password/change/"), "Change your password")

    def test_staff_can_set_a_password_in_the_control_room(self):
        loner = User.objects.create_user("loner@students.dictionmasters.app", "pw-12345678", first_name="Lone",
                                         role="individual", username="lone.r")
        PasswordHelpRequest.objects.create(user=loner)
        staff = User.objects.create_user("staff@example.com", "Staff-pass-11", first_name="Sam", is_staff=True)
        self.client.force_login(staff)
        form = self.client.get(f"/manage/users/{loner.pk}/")
        self.assertContains(form, "Set a new password")
        data = {"first_name": "Lone", "last_name": "", "username": "lone.r", "email": loner.email,
                "role": "individual", "is_active": "on", "set_password": "kiwi-tree-9"}
        self.client.post(f"/manage/users/{loner.pk}/", data)
        loner.refresh_from_db()
        self.assertTrue(loner.check_password("kiwi-tree-9"))
        self.assertIsNotNone(PasswordHelpRequest.objects.get(user=loner).resolved_at)
