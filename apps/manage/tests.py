from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from .registry import screens

User = get_user_model()


class EveryPageOpensTests(TestCase):
    """Every page of the control room opens for an admin: the fixed pages,
    and each screen's list and add form."""

    def setUp(self):
        self.client.force_login(User.objects.create_user(
            email="admin@example.com", password="pw-12345678", first_name="Sam", is_staff=True, is_superuser=True))

    def test_the_fixed_pages(self):
        for url in ("/manage/", "/manage/branding/", "/manage/billing-settings/", "/manage/read-along/",
                    "/manage/echospell-import/", "/manage/search/?q=a"):
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_every_screen(self):
        for key, screen in screens().items():
            self.assertEqual(self.client.get(f"/manage/{key}/").status_code, 200, key)
            if not screen.get("readonly"):
                self.assertEqual(self.client.get(f"/manage/{key}/new/").status_code, 200, f"{key} add form")


@override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class ResultsAndMarkingTests(TestCase):
    """Every attempt in one place, and grading whatever a person has to judge."""

    def setUp(self):
        from apps.assessments.models import Answer, Assessment, Attempt, Question
        from apps.book.models import SoundCategory, Sound
        from apps.echospell.models import Activity, ActivityAttempt, ActivityItem, ActivityResponse, Group, Level
        from apps.tricks.models import TrickActivity, TrickActivityAttempt, TrickActivityItem, TrickActivityResponse

        self.admin = User.objects.create_user(email="admin@example.com", password="pw-12345678", first_name="Sam",
                                              is_staff=True, is_superuser=True)
        self.learner = User.objects.create_user(email="ada@example.com", password="pw-12345678",
                                                first_name="Ada", last_name="Obi")
        voice = SimpleUploadedFile("me.webm", b"voice", content_type="audio/webm")

        # EchoSpell: a read-aloud, sent to the teacher.
        group = Group.objects.create(level=Level.objects.create(name="Level 4", slug="level-4-results"),
                                     number=1, slug="group-1-results")
        read = Activity.objects.create(group=group, kind="read-aloud", title="Read the passage", pass_mark=50)
        line = ActivityItem.objects.create(activity=read, prompt="The cat sat on the mat.")
        self.echo = ActivityAttempt.objects.create(user=self.learner, activity=read, status="awaiting")
        self.echo_line = ActivityResponse.objects.create(attempt=self.echo, item=line, recording=voice)

        # Tricks: two recordings.
        trick = Sound.objects.create(category=SoundCategory.for_tricks(), name="-age Ending")
        say = TrickActivity.objects.create(trick=trick, kind="repeat-after", title="Say it after me", pass_mark=50)
        self.trick = TrickActivityAttempt.objects.create(user=self.learner, activity=say, status="awaiting")
        self.trick_lines = [
            TrickActivityResponse.objects.create(
                attempt=self.trick, item=TrickActivityItem.objects.create(activity=say, prompt=word, order=n),
                recording=SimpleUploadedFile(f"{word}.webm", b"voice", content_type="audio/webm"))
            for n, word in enumerate(["village", "message"])
        ]

        # Assessments: a speaking test waiting for marking.
        test = Assessment.objects.create(title="Speaking check", kind=Assessment.Kind.SPEAKING, pass_mark=60)
        spoken = Question.objects.create(assessment=test, type=Question.Type.SPEAK, prompt="Say: thirty-three", points=5)
        self.exam = Attempt.objects.create(user=self.learner, assessment=test, status=Attempt.Status.AWAITING,
                                           question_order=[spoken.pk])
        self.exam_answer = Answer.objects.create(attempt=self.exam, question=spoken, recording=voice)

        self.client.force_login(self.admin)

    def test_everything_waiting_is_in_one_list(self):
        page = self.client.get("/manage/results/?show=to-mark")
        for what in ("Read the passage", "Say it after me", "Speaking check"):
            self.assertContains(page, what)
        self.assertContains(page, "Ada Obi")
        self.assertEqual(page.context["to_mark"], 3)
        self.assertContains(self.client.get("/manage/"), "Results &amp; marking")

    def test_the_attempt_lists_open_each_attempt(self):
        for screen, source, attempt in (("activity-attempts", "echospell", self.echo),
                                        ("trick-activity-attempts", "trick", self.trick),
                                        ("attempts", "assessment", self.exam)):
            listing = self.client.get(f"/manage/{screen}/")
            self.assertContains(listing, f'href="/manage/results/{source}/{attempt.pk}/"', msg_prefix=screen)
            self.assertNotContains(listing, "view only", msg_prefix=screen)
            page = self.client.get(f"/manage/results/{source}/{attempt.pk}/")
            self.assertContains(page, "<audio", msg_prefix=source)

    def test_marking_recordings(self):
        good, work = self.trick_lines
        # Every recording needs a mark.
        page = self.client.post(f"/manage/results/trick/{self.trick.pk}/", {f"verdict-{good.pk}": "good"})
        self.assertContains(page, "Mark every recording")
        self.client.post(f"/manage/results/trick/{self.trick.pk}/", {
            f"verdict-{good.pk}": "good", f"verdict-{work.pk}": "work", "feedback": "Lovely -idge on village.",
        })
        self.trick.refresh_from_db()
        self.assertEqual((self.trick.status, self.trick.percent, self.trick.passed), ("reviewed", 50, True))
        self.assertEqual(self.trick.teacher_feedback, "Lovely -idge on village.")

        self.client.post(f"/manage/results/echospell/{self.echo.pk}/", {f"verdict-{self.echo_line.pk}": "work"})
        self.echo.refresh_from_db()
        self.assertEqual((self.echo.status, self.echo.percent, self.echo.passed), ("reviewed", 0, False))

    def test_marking_a_speaking_assessment_on_the_rubric(self):
        from apps.assessments.models import RUBRIC_CRITERIA

        marks = {f"{self.exam_answer.pk}-{field}": "4" for field, _ in RUBRIC_CRITERIA}
        self.client.post(f"/manage/results/assessment/{self.exam.pk}/", {**marks, "feedback": "Clear th."})
        self.exam.refresh_from_db()
        self.assertEqual(self.exam.status, "marked")
        self.assertEqual(self.exam.percent, 80)
        self.assertTrue(self.exam.passed)
        self.assertEqual(self.exam.marked_by, self.admin)
        self.assertEqual(self.client.get("/manage/results/?show=to-mark").context["to_mark"], 2)

    def test_learners_cannot_get_in(self):
        self.client.force_login(self.learner)
        self.assertEqual(self.client.get(f"/manage/results/trick/{self.trick.pk}/").status_code, 302)
