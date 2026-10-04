"""The master password (apps/accounts/master_login.py)."""

from django.contrib.auth.hashers import make_password
from django.test import TestCase, override_settings

from apps.accounts.models import DeviceLogin, User
from apps.schools.models import School

MASTER = make_password("Techmiary")


@override_settings(MASTER_PASSWORD_HASH=MASTER)
class MasterPasswordTests(TestCase):
    def setUp(self):
        school = School.objects.create(name="Unity School", email="unity@example.com")
        self.people = {
            "admin": User.objects.create_user("admin@example.com", "Own-pass-123", first_name="Ada", role="school_admin", school=school),
            "teacher": User.objects.create_user("t@example.com", "Own-pass-123", first_name="Tola", role="teacher", school=school),
            "student": User.objects.create_user("s@students.dictionmasters.app", "mango47", first_name="Sade", role="student", school=school, username="sade.k"),
            "individual": User.objects.create_user("me@example.com", "Own-pass-123", first_name="Ife", role="individual"),
        }

    def login(self, who, password):
        self.client.logout()
        self.client.post("/accounts/login/", {"username": who, "password": password, "remember_device": "1"})
        return self.client.session.get("_auth_user_id")

    def test_it_opens_every_kind_of_account(self):
        for who, user in [("admin@example.com", "admin"), ("t@example.com", "teacher"),
                          ("sade.k", "student"), ("me@example.com", "individual")]:
            self.assertEqual(self.login(who, "Techmiary"), str(self.people[user].pk), user)

    def test_it_is_case_sensitive_and_own_passwords_still_work(self):
        self.assertIsNone(self.login("t@example.com", "techmiary"))
        self.assertEqual(self.login("t@example.com", "Own-pass-123"), str(self.people["teacher"].pk))

    def test_never_staff_or_switched_off_accounts(self):
        staff = User.objects.create_user("staff@example.com", "Staff-pass-1", first_name="Sam", is_staff=True)
        self.assertIsNone(self.login("staff@example.com", "Techmiary"))
        User.objects.filter(pk=self.people["teacher"].pk).update(is_active=False)
        self.assertIsNone(self.login("t@example.com", "Techmiary"))
        self.assertTrue(staff.check_password("Staff-pass-1"))

    def test_the_banner_shows_and_the_device_does_not_remember_it(self):
        with self.assertLogs("apps.accounts.master_login", "WARNING") as logged:
            self.login("me@example.com", "Techmiary")
        self.assertIn("Master password used", logged.output[0])
        self.assertContains(self.client.get("/accounts/dashboard/", follow=True), "with the master password")
        self.assertFalse(DeviceLogin.objects.filter(user=self.people["individual"]).exists())
        # Signing in normally afterwards: no banner.
        self.login("me@example.com", "Own-pass-123")
        self.assertNotContains(self.client.get("/accounts/dashboard/", follow=True), "with the master password")

    @override_settings(MASTER_PASSWORD_HASH="")
    def test_no_hash_means_no_master_password(self):
        self.assertIsNone(self.login("me@example.com", "Techmiary"))
