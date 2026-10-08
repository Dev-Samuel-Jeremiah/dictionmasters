"""
A full school year of the scheme of work for one level, for trying it out.

    python manage.py seed_scheme_demo                 # Level 1
    python manage.py seed_scheme_demo --level "Level 2"
    python manage.py seed_scheme_demo --remove        # take the demo off again

It makes (or reuses) the 2026/2027 school year with its three terms and
mid-term breaks, then fills every school day of every week for the level:
the Learning Modules days in order, one a school day, then the level's
other content in turn; one extra "any day this week" item each week, Daily
Practice every Friday, and a CA 1, CA 2 and exam each term (made here,
marked "(demo)", three questions each). It also makes "Demo Scheme School"
with a teacher and two pupils on that level, to sign in as.

Running it again rebuilds the level's scheme from scratch. --remove takes
off the level's scheme, the demo tests and the demo school (and its
accounts); the school year is kept.
"""

from datetime import date, datetime, time, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import INTERNAL_EMAIL_DOMAIN, User
from apps.assembly_recitals.models import Recital
from apps.assessments.models import Assessment, Question
from apps.book.models import ACADEMY, TRICKS
from apps.diction_library.models import LibraryItem
from apps.echospell.models import Group
from apps.learning_modules.models import Day
from apps.reading_club.models import Chapter
from apps.schools.models import School
from apps.tricks.progress import lessons_in_order

from ...calendar import week_of, weeks_in
from ...models import SchemeEntry, Session, Term

SESSION = "2026/2027"
TERMS = [  # number, starts, ends, break starts, break ends
    (1, date(2026, 9, 14), date(2026, 12, 11), date(2026, 10, 26), date(2026, 10, 30)),
    (2, date(2027, 1, 11), date(2027, 4, 1), date(2027, 2, 15), date(2027, 2, 19)),
    (3, date(2027, 4, 26), date(2027, 7, 23), date(2027, 6, 7), date(2027, 6, 11)),
]
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday"]
SCHOOL = "Demo Scheme School"
PASSWORD = "DemoScheme-2026"
DEMO_SLUG = "demo-scheme-"
QUESTIONS = [
    ("Which word has the /iː/ sound?", ["sheep", "ship", "shop"], "sheep"),
    ("Which word starts with the /θ/ sound?", ["think", "sink", "tink"], "think"),
    ("Which word rhymes with 'cat'?", ["hat", "hot", "hit"], "hat"),
]


def _monday_of(term, week):
    """The Monday that starts `week` of `term`, the break left out."""
    monday = term.starts - timedelta(days=term.starts.weekday()) + timedelta(weeks=week - 1)
    if term.break_starts and monday >= term.break_starts - timedelta(days=term.break_starts.weekday()):
        monday += timedelta(weeks=1)
    return monday


class Command(BaseCommand):
    help = "Fill a whole school year of the scheme of work for one level, with demo tests and accounts."

    def add_arguments(self, parser):
        parser.add_argument("--level", default="Level 1")
        parser.add_argument("--remove", action="store_true", help="Take the demo off again.")

    @transaction.atomic
    def handle(self, *args, level="Level 1", remove=False, **options):
        slug = level.lower().replace(" ", "-")
        if remove:
            entries, _ = SchemeEntry.objects.filter(level=level).delete()
            tests, _ = Assessment.objects.filter(slug__startswith=f"{DEMO_SLUG}{slug}-").delete()
            school, _ = School.objects.filter(name=SCHOOL).delete()
            self.stdout.write(self.style.SUCCESS(
                f"Removed {level}'s scheme ({entries} rows), the demo tests and the demo school ({school} rows). "
                f"The {SESSION} school year is kept."))
            return

        terms = self._calendar()
        SchemeEntry.objects.filter(level=level).delete()
        module_days = list(Day.objects.filter(is_published=True, week__term__module__is_published=True)
                           .order_by("week__term__module__order", "week__term__module__name", "week__term__order",
                                     "week__term__id", "week__number", "order"))
        rotation = (
            [("group", "group", g) for g in Group.objects.filter(level__name=level, level__is_published=True).order_by("number")]
            + [("sound", "sound", s) for s in lessons_in_order(ACADEMY)]
            + [("trick", "sound", s) for s in lessons_in_order(TRICKS)]
            + [("chapter", "chapter", c) for c in Chapter.objects.filter(is_published=True).order_by("term__book__order", "term__order", "number")]
            + [("recital", "recital", r) for r in Recital.objects.filter(is_published=True).order_by("section__order", "order")]
            + [("library", "library_item", i) for i in LibraryItem.objects.filter(is_published=True, school__isnull=True).order_by("title")]
        )
        if not module_days and not rotation:
            self.stderr.write("There is no content to put on the scheme yet.")
            return

        new, turn, tests = [], 0, 0
        for term in terms:
            ca1, ca2, exam = self._tests(level, slug, term)
            tests += 3
            last = weeks_in(term)
            for week in range(1, last + 1):
                orders = {}

                def add(day, kind, **content):
                    orders[day] = orders.get(day, 0) + 1
                    new.append(SchemeEntry(level=level, term=term.number, week=week, day=day, kind=kind,
                                           order=orders[day], **content))

                for day in WEEKDAYS:
                    if module_days:
                        add(day, "module_day", module_day=module_days.pop(0))
                    elif rotation:
                        kind, field, item = rotation[turn % len(rotation)]
                        turn += 1
                        add(day, kind, **{field: item})
                if rotation:
                    kind, field, item = rotation[turn % len(rotation)]
                    turn += 1
                    add("", kind, **{field: item})
                add("friday", "daily_practice")
                if week == 4:
                    add("thursday", "assessment", assessment=ca1)
                if week == 8:
                    add("thursday", "assessment", assessment=ca2)
                if week == last:
                    add("wednesday", "assessment", assessment=exam)
        SchemeEntry.objects.bulk_create(new)

        teacher, pupils = self._people(level, slug)
        self.stdout.write(self.style.SUCCESS(
            f"{level}: {len(new)} scheme entries over {sum(weeks_in(t) for t in terms)} weeks in {len(terms)} terms, "
            f"and {tests} demo tests."))
        today = timezone.localdate()
        now = next((t for t in terms if t.starts <= today <= t.ends), None)
        if now:
            self.stdout.write(f"Today is {now.term if hasattr(now, 'term') else now}, Week {week_of(now, today)}.")
        self.stdout.write(f"Sign in (password {PASSWORD}): teacher {teacher.username}, "
                          f"pupils {', '.join(p.username for p in pupils)}.")

    def _calendar(self):
        session, _ = Session.objects.get_or_create(name=SESSION)
        terms = []
        for number, starts, ends, break_starts, break_ends in TERMS:
            term, _ = Term.objects.update_or_create(
                session=session, number=number,
                defaults={"starts": starts, "ends": ends, "break_starts": break_starts, "break_ends": break_ends},
            )
            terms.append(term)
        return terms

    def _tests(self, level, slug, term):
        """CA 1, CA 2 and the exam for one term, open from their week to the term's end."""
        tz = timezone.get_current_timezone()
        closes = timezone.make_aware(datetime.combine(term.ends + timedelta(days=7), time.max), tz)
        found = []
        for kind, number, week, title in (("ca", 1, 4, "CA 1"), ("ca", 2, 8, "CA 2"), ("exam", None, weeks_in(term), "Exam")):
            opens = timezone.make_aware(datetime.combine(_monday_of(term, week), time.min), tz)
            test, _ = Assessment.objects.update_or_create(
                slug=f"{DEMO_SLUG}{slug}-t{term.number}-{title.lower().replace(' ', '')}",
                defaults={"title": f"{level} {term.get_number_display()} {title} (demo)", "kind": kind,
                          "level": level, "term": term.number, "ca_number": number, "opens_at": opens,
                          "closes_at": closes, "pass_mark": 50, "is_published": True,
                          "summary": "A sample test made by seed_scheme_demo."},
            )
            if not test.questions.exists():
                for order, (prompt, options, answer) in enumerate(QUESTIONS):
                    Question.objects.create(assessment=test, type=Question.Type.CHOICE, prompt=prompt,
                                            options="\n".join(options), answer=answer, order=order)
            found.append(test)
        return found

    def _people(self, level, slug):
        school, _ = School.objects.get_or_create(name=SCHOOL, defaults={"email": "demo-scheme@example.com"})

        def person(username, first, last, role):
            user = User.objects.filter(username=username).first()
            if user is None:
                user = User.objects.create_user(
                    f"{username}@{INTERNAL_EMAIL_DOMAIN}", PASSWORD, username=username,
                    first_name=first, last_name=last, role=role, school=school, level=level)
            else:
                user.school, user.level, user.role, user.is_active = school, level, role, True
                user.set_password(PASSWORD)
                user.save()
            return user

        teacher = person(f"demo.teacher.{slug}", "Demo", "Teacher", "teacher")
        pupils = [person(f"demo.pupil{n}.{slug}", f"Pupil {n}", "Demo", "student") for n in (1, 2)]
        return teacher, pupils
