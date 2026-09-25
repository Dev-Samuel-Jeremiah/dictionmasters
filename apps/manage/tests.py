from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase, override_settings

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
        from apps.tricks.models import LessonActivity, LessonActivityAttempt, LessonActivityItem, LessonActivityResponse

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
        say = LessonActivity.objects.create(lesson=trick, kind="repeat-after", title="Say it after me", pass_mark=50)
        self.trick = LessonActivityAttempt.objects.create(user=self.learner, activity=say, status="awaiting")
        self.trick_lines = [
            LessonActivityResponse.objects.create(
                attempt=self.trick, item=LessonActivityItem.objects.create(activity=say, prompt=word, order=n),
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
                                        ("trick-activity-attempts", "lesson", self.trick),
                                        ("attempts", "assessment", self.exam)):
            listing = self.client.get(f"/manage/{screen}/")
            self.assertContains(listing, f'href="/manage/results/{source}/{attempt.pk}/"', msg_prefix=screen)
            self.assertNotContains(listing, "view only", msg_prefix=screen)
            page = self.client.get(f"/manage/results/{source}/{attempt.pk}/")
            self.assertContains(page, "<audio", msg_prefix=source)

    def test_marking_recordings(self):
        good, work = self.trick_lines
        # Every recording needs a mark.
        page = self.client.post(f"/manage/results/lesson/{self.trick.pk}/", {f"verdict-{good.pk}": "good"})
        self.assertContains(page, "Mark every recording")
        self.client.post(f"/manage/results/lesson/{self.trick.pk}/", {
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
        self.assertEqual(self.client.get(f"/manage/results/lesson/{self.trick.pk}/").status_code, 302)


class RichTextTests(TestCase):
    """The shared editor's server side: what is stored, what learners see,
    and what speech, marking and search read."""

    def test_sanitizer_removes_scripts_handlers_and_unsafe_links(self):
        from .rich_text import sanitize_rich_text

        dirty = ('<p onclick="x()">Hi<script>alert(1)</script></p>'
                 '<a href="javascript:alert(1)">bad</a><a href="example.com" target="_blank">ok</a>'
                 '<span style="color: red; background: url(x)">c</span>')
        clean = sanitize_rich_text(dirty)
        self.assertNotIn("script", clean)
        self.assertNotIn("onclick", clean)
        self.assertNotIn("javascript", clean)
        self.assertNotIn("url(", clean)
        self.assertIn('<a href="https://example.com" target="_blank" rel="noopener noreferrer">ok</a>', clean)
        self.assertIn('<span style="color: red">c</span>', clean)

    def test_legacy_plain_text_renders_escaped_with_line_breaks(self):
        from .rich_text import sanitize_rich_text

        self.assertEqual(sanitize_rich_text("Tom & Jerry\nsay 2 < 3"), "Tom &amp; Jerry<br>say 2 &lt; 3")

    def test_single_line_editor_value_is_not_escaped_twice(self):
        from .rich_text import clean_rich_text_input, sanitize_rich_text

        # The editor always wraps its HTML, so entities are never mistaken
        # for plain text that needs escaping again.
        for typed in ("<p>Tom &amp; Jerry</p>", "<p>two&nbsp; spaces</p>", "<p>2 &lt; 3</p>"):
            stored = clean_rich_text_input(typed)
            self.assertTrue(stored.startswith("<p>"), stored)
            self.assertNotIn("&amp;amp;", sanitize_rich_text(stored))
            self.assertNotIn("&amp;nbsp;", sanitize_rich_text(stored))
            # Saving again leaves it unchanged.
            self.assertEqual(clean_rich_text_input(stored), stored)

    def test_empty_editor_saves_nothing(self):
        from .rich_text import clean_rich_text_input

        for empty in ("", "   ", "<br>", "<p><br></p>", "<p>&nbsp;</p>", "<div><br></div>"):
            self.assertEqual(clean_rich_text_input(empty), "", empty)
        self.assertEqual(clean_rich_text_input("<hr>"), "<hr>")

    def test_plain_text_submission_is_stored_as_typed(self):
        from .rich_text import clean_rich_text_input, sanitize_rich_text

        stored = clean_rich_text_input("  One\nTwo & more ")
        self.assertEqual(stored, "One\nTwo & more")
        self.assertEqual(sanitize_rich_text(stored), "One<br>Two &amp; more")

    def test_plain_text_for_speech_marking_and_search(self):
        from .rich_text import plain_text

        self.assertEqual(plain_text("<p>Hello <b>wor</b>ld &amp; you</p><ul><li>one</li><li>two</li></ul>"),
                         "Hello world & you\n\none\n\ntwo")
        self.assertEqual(plain_text("Plain & simple"), "Plain & simple")
        self.assertEqual(plain_text(None), "")

    def test_truncation_never_cuts_through_a_tag(self):
        from .rich_text import sanitize_rich_text, truncate_rich_text

        long = "<p>" + "<b>word</b> " * 500 + "</p>"
        cut = truncate_rich_text(long, 400)
        self.assertLessEqual(len(cut), 400)
        self.assertNotIn("<", cut)
        self.assertTrue(cut.startswith("word word"))
        self.assertIn("word word", sanitize_rich_text(cut))
        self.assertEqual(truncate_rich_text("<p><b>short</b></p>", 400), "<p><b>short</b></p>")

    def test_admin_uses_the_editor_only_for_learner_prose(self):
        from django.contrib import admin

        from apps.echospell.models import CardLesson
        from apps.quick_words.models import QuickWord

        from .rich_text import RichTextWidget

        request = RequestFactory().get("/admin/")
        request.user = User.objects.create_superuser(email="root@example.com", password="pw-12345678")
        word_form = admin.site._registry[QuickWord].get_form(request)
        self.assertIsInstance(word_form.base_fields["definition"].widget, RichTextWidget)
        lesson_form = admin.site._registry[CardLesson].get_form(request)
        self.assertNotIsInstance(lesson_form.base_fields["definition"].widget, RichTextWidget)

    def test_rich_text_filters(self):
        from django.template import Context, Template

        out = Template("{% load rich_text %}{{ v|rich_text }}|{{ v|rich_text_plain }}|{{ v|rich_text_inline }}").render(
            Context({"v": "<p>A <em>b</em></p><p>c</p>"}))
        self.assertEqual(out, "<p>A <em>b</em></p><p>c</p>|A b\n\nc|A <em>b</em><br>c")
