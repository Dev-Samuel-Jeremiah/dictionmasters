"""Signing up with an email that's already taken: always a clear message,
never a server error — including a sign-up sent twice at once."""

from unittest import mock

from django.test import TestCase

from apps.accounts.models import User
from apps.schools.models import School


class DuplicateSignUpTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="Unity School", email="unity@example.com")
        self.form = {"school_code": self.school.code, "level": "Level 1", "first_name": "Havila", "last_name": "Sandra",
                     "email": "glendalebritish@gmail.com", "password1": "Basicone2026", "password2": "Basicone2026"}

    def join(self, **changes):
        return self.client.post("/accounts/join/", {**self.form, **changes})

    def test_the_same_email_again_is_a_clear_message(self):
        self.assertEqual(self.join().status_code, 302)                     # the first one joins
        self.client.logout()
        response = self.join()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already exists with this email")
        self.assertEqual(User.objects.filter(email__iexact="glendalebritish@gmail.com").count(), 1)

    def test_the_same_email_in_capitals_is_caught_too(self):
        self.join()
        self.client.logout()
        response = self.join(email="GlendaleBritish@Gmail.com")
        self.assertContains(response, "already exists with this email")

    def test_a_sign_up_sent_twice_at_once_does_not_crash(self):
        """Both requests pass the email check before either is saved: the
        second meets the first's account only when saving."""
        User.objects.create_user("glendalebritish@gmail.com", "Basicone2026", first_name="Havila",
                                 role="teacher", school=self.school)
        real_filter = User.objects.filter

        def as_if_not_yet_saved(*args, **kwargs):
            if kwargs.get("email__iexact"):
                return User.objects.none()
            return real_filter(*args, **kwargs)

        with mock.patch.object(User.objects, "filter", side_effect=as_if_not_yet_saved):
            response = self.join()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already exists with this email")
        self.assertEqual(User.objects.filter(email="glendalebritish@gmail.com").count(), 1)
