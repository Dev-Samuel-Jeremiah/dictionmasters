"""
Screenshots and screen recording in the apps (apps/landing/capture.py):
blocked for everyone, except staff and admins while the control room's
switch is on. Schools, teachers and students are never allowed.
"""

import re

from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.test import TestCase

from .capture import may_capture
from .models import ScreenProtection

User = get_user_model()


def capture_on(html):
    """What a page tells the app: the screen_capture.js tag's data-capture."""
    found = re.search(r'screen_capture\.js[^"]*"\s+data-capture="(\w+)"', html)
    return found.group(1) if found else None


class ScreenCaptureTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(email="boss@example.com", password="pw-12345678", first_name="Boss",
                                              is_staff=True)
        self.people = {
            role: User.objects.create_user(email=f"{role}@example.com", password="pw-12345678", first_name=role.title(),
                                           role=role)
            for role in ("school_admin", "teacher", "student", "individual")
        }

    def switch(self, on):
        protection = ScreenProtection.load()
        protection.staff_may_capture = on
        protection.save()

    def test_blocked_for_everyone_until_switched_on(self):
        self.assertFalse(ScreenProtection.load().staff_may_capture)
        self.assertFalse(may_capture(self.staff))
        for person in self.people.values():
            self.assertFalse(may_capture(person))

    def test_on_only_ever_reaches_staff_and_admins(self):
        self.switch(True)
        self.assertTrue(may_capture(self.staff))
        for role, person in self.people.items():
            self.assertFalse(may_capture(person), role)
        from django.contrib.auth.models import AnonymousUser

        self.assertFalse(may_capture(AnonymousUser()))
        self.assertFalse(may_capture(None))

    def test_pages_tell_the_app(self):
        self.client.force_login(self.staff)
        self.assertEqual(capture_on(self.client.get("/privacy/").content.decode()), "block")
        self.switch(True)
        self.assertEqual(capture_on(self.client.get("/privacy/").content.decode()), "allow")
        self.assertEqual(capture_on(self.client.get("/manage/").content.decode()), "allow")
        self.assertEqual(capture_on(self.client.get("/admin/").content.decode()), "allow")
        self.client.force_login(self.people["student"])
        self.assertEqual(capture_on(self.client.get("/privacy/").content.decode()), "block")
        self.client.logout()
        self.assertEqual(capture_on(self.client.get("/privacy/").content.decode()), "block")

    def test_the_control_room_switch(self):
        self.client.force_login(self.staff)
        page = self.client.get("/manage/screen-protection/")
        self.assertContains(page, "Screenshots and screen recording are blocked")
        self.assertContains(page, "Let staff and admins record")
        page = self.client.post("/manage/screen-protection/", {"staff_may_capture": "on"}, follow=True)
        self.assertTrue(ScreenProtection.load().staff_may_capture)
        self.assertContains(page, "Staff and admins can take screenshots")
        self.assertContains(page, "Block again")
        self.client.post("/manage/screen-protection/", {"staff_may_capture": "off"})
        self.assertFalse(ScreenProtection.load().staff_may_capture)
        self.assertEqual(LogEntry.objects.filter(object_repr="Screen protection").count(), 2)
        self.assertContains(self.client.get("/manage/"), "/manage/screen-protection/")

    def test_nobody_else_can_switch_it(self):
        for person in self.people.values():
            self.client.force_login(person)
            self.client.post("/manage/screen-protection/", {"staff_may_capture": "on"})
            self.assertFalse(ScreenProtection.load().staff_may_capture)
