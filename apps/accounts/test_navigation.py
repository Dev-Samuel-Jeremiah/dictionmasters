"""A Back button on every page but home, and nothing locked: any module
term or week, reading club term or 44 Academy lesson opens."""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.book.models import Sound, SoundCategory, WordBankEntry
from apps.learning_modules.models import Day, LearningModule, Term, Week
from apps.reading_club.models import Book, Chapter, Term as BookTerm

User = get_user_model()
BACK = 'class="px-back__btn" data-history-back'


class BackButtonTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("solo@example.com", "mango7", first_name="Ada", is_staff=True)
        self.client.force_login(self.user)

    def test_inner_pages_have_back_home_does_not(self):
        for url in ("/learning-tools/", "/echospell/", "/accounts/grown-ups/", "/assessments/"):
            self.assertContains(self.client.get(url, follow=True), BACK, msg_prefix=url)
        self.assertNotContains(self.client.get("/accounts/dashboard/"), BACK)

    def test_signed_out_pages_have_none(self):
        self.client.logout()
        self.assertNotContains(self.client.get("/accounts/login/"), BACK)

    def test_the_control_room_has_one_too(self):
        page = self.client.get("/manage/calendar/")
        self.assertContains(page, "&larr; Back</a>")
        self.assertNotContains(self.client.get("/manage/"), "&larr; Back</a>")


class NothingLockedTests(TestCase):
    def setUp(self):
        self.learner = User.objects.create_user("learner@example.com", "mango7", first_name="Ife",
                                                role="student", level="Level 1")
        self.client.force_login(self.learner)

    def test_any_module_term_and_week(self):
        LearningModule.objects.all().delete()
        module = LearningModule.objects.create(name="Sounds", slug="sounds")
        first = Term.objects.create(module=module, name="First Term", order=1)
        second = Term.objects.create(module=module, name="Second Term", order=2)
        for term in (first, second):
            Day.objects.create(week=Week.objects.create(term=term, number=1), day_name="monday")
        Day.objects.create(week=Week.objects.create(term=first, number=2), day_name="monday")
        self.assertEqual(self.client.get("/learning-modules/sounds/second-term/").status_code, 200)
        self.assertEqual(self.client.get("/learning-modules/sounds/first-term/week-2/monday/").status_code, 200)
        self.assertEqual(self.client.get("/learning-modules/sounds/second-term/week-1/monday/").status_code, 200)
        self.assertNotContains(self.client.get("/learning-modules/sounds/"), "Complete the term before")

    def test_any_reading_club_term(self):
        book = Book.objects.create(title="The Drum", slug="the-drum")
        BookTerm.objects.create(book=book, name="First Term", order=1)
        later = BookTerm.objects.create(book=book, name="Second Term", order=2)
        Chapter.objects.create(term=later, number=1, title="The end")
        self.assertEqual(self.client.get("/reading-club/the-drum/second-term/").status_code, 200)

    def test_any_44_academy_lesson(self):
        sounds = SoundCategory.objects.create(name="Long vowels")
        first = Sound.objects.create(category=sounds, name="Sheep", order=1)
        second = Sound.objects.create(category=sounds, name="Shoe", order=2)
        for sound in (first, second):
            WordBankEntry.objects.create(sound=sound, word=sound.name.lower())
        self.assertEqual(self.client.get(f"/book/44-academy/{second.slug}/").status_code, 200)
