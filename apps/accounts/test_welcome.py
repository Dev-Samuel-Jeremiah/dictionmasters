"""The welcome email a new account gets."""

from django.core import mail
from django.test import RequestFactory, TestCase

from apps.accounts.models import User
from apps.accounts.welcome import send_welcome
from apps.schools.models import School


class WelcomeEmailTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="Unity School", email="unity@example.com")
        self.request = RequestFactory().get("/")

    def welcome(self, user):
        with self.captureOnCommitCallbacks(execute=True):
            sent = send_welcome(self.request, user)
        return sent

    def test_each_role_gets_its_own_welcome(self):
        admin = User.objects.create_user("admin@example.com", "x-Pass-1234", first_name="Ada", role="school_admin", school=self.school)
        teacher = User.objects.create_user("t@example.com", "x-Pass-1234", first_name="Tola", role="teacher", school=self.school, level="Level 3")
        learner = User.objects.create_user("me@example.com", "x-Pass-1234", first_name="Ife", role="individual")
        for user in (admin, teacher, learner):
            self.assertTrue(self.welcome(user))
        self.assertEqual([m.to for m in mail.outbox], [["admin@example.com"], ["t@example.com"], ["me@example.com"]])
        admin_mail, teacher_mail, learner_mail = mail.outbox
        self.assertIn("Unity School", admin_mail.subject)
        self.assertIn(self.school.code, admin_mail.body)                    # the code to share
        self.assertIn("Lesson Notes to Audio", teacher_mail.body)
        self.assertIn("Level 3", teacher_mail.body)
        self.assertIn("free trial", learner_mail.body)
        html = learner_mail.alternatives[0][0]
        self.assertIn("/accounts/password/forgot/", html)

    def test_no_email_for_an_account_without_an_inbox(self):
        student = User.objects.create_user("s@students.dictionmasters.app", "mango47", first_name="Sade",
                                           role="student", school=self.school, username="sade.k")
        self.assertFalse(self.welcome(student))
        self.assertEqual(mail.outbox, [])

    def test_signing_up_sends_the_welcome(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post("/accounts/register/individual/", {
                "first_name": "Chioma", "last_name": "Obi", "email": "chioma@example.com",
                "password1": "River-gate-77", "password2": "River-gate-77", "start": "trial",
            })
        self.assertTrue(User.objects.filter(email="chioma@example.com").exists())
        self.assertEqual([m.to for m in mail.outbox], [["chioma@example.com"]])
        self.assertEqual(mail.outbox[0].subject, "Welcome to Diction Masters")
