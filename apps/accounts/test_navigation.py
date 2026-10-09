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


class TidyMenuTests(TestCase):
    """Each link once: the sidebar's own groups, the folded course and tool
    lists, and an account menu with account things only."""

    def sidebar(self, user):
        self.client.force_login(user)
        page = self.client.get("/learning-tools/" if not user.is_school_admin else "/scheme/term-dates/", follow=True)
        html = page.content.decode()
        return html[html.index('<nav class="px-side__nav">'):html.index("</nav>", html.index('<nav class="px-side__nav">'))]

    def test_a_learner_gets_the_main_links_and_folded_lists(self):
        side = self.sidebar(User.objects.create_user("solo@example.com", "mango7", first_name="Solo"))
        self.assertIn('data-side-fold="courses"', side)
        self.assertIn('data-side-fold="tools"', side)
        self.assertNotIn("Teaching</p>", side)
        self.assertEqual(side.count('href="/daily-practice/"'), 1)        # the Practice tab, not again in tools

    def test_a_teacher_gets_a_teaching_group(self):
        teacher = User.objects.create_user("t@example.com", "mango7", first_name="T", role="teacher", level="Level 1")
        side = self.sidebar(teacher)
        for url in ("/school/class/", "/scheme/teach/", "/scheme/reports/", "/assessments/marking/"):
            self.assertEqual(side.count(f'href="{url}"'), 1, url)

    def test_a_school_admin_gets_the_school_group(self):
        from apps.schools.models import School

        admin = User.objects.create_user("h@example.com", "mango7", first_name="H", role="school_admin",
                                         school=School.objects.create(name="Unity", email="u@example.com"))
        side = self.sidebar(admin)
        for url in ("/scheme/school/", "/scheme/term-dates/", "/scheme/reports/", "/scheme/promote/"):
            self.assertEqual(side.count(f'href="{url}"'), 1, url)
        self.assertNotIn("data-side-fold", side)

    def test_the_account_menu_has_account_things_only(self):
        self.client.force_login(User.objects.create_user("kid@example.com", "mango7", first_name="Kid"))
        html = self.client.get("/learning-tools/").content.decode()
        panel = html[html.index('class="account-menu__panel"'):]
        panel = panel[:panel.index("</nav>")]
        self.assertIn('href="/accounts/grown-ups/"', panel)
        self.assertIn('href="/accounts/password/change/"', panel)
        for gone in ('href="/assessments/results/"', 'href="/learning-tools/"', 'href="/accounts/dashboard/"'):
            self.assertNotIn(gone, panel)

    def test_the_school_dashboard_folds_and_puts_the_school_year_first(self):
        from apps.schools.models import School

        school = School.objects.create(name="Unity", email="u@example.com")
        self.client.force_login(User.objects.create_user("h@example.com", "mango7", first_name="H",
                                                         role="school_admin", school=school))
        page = self.client.get("/school/dashboard/")
        self.assertContains(page, 'id="school-year"')
        self.assertContains(page, 'class="sd2-section sd2-fold"', count=3)
        self.assertContains(page, 'id="join" open')                   # nobody yet: open
        self.assertContains(page, "js/fold_open.js")
