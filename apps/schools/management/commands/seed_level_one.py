"""
python manage.py seed_level_one

Sample Level 1 content and test logins, to try the site as a Grade 1
pupil (and a Grade 3 pupil, who also gets the 44 Academy). Safe to run
again: it only adds what's missing and never changes or deletes anything
already there.

Content:
    EchoSpell Level 1, Groups 1-4: Spelling and Vocabulary cards, a
        passage, a dialogue, and three activities each (missing letters,
        rhyme match, sentence builder)
    Conversational Dialogue: three Level 1 dialogues
    Tricks to Sound Fluent and the 44 Academy: two lessons each, with
        words, sentences and a tongue twister
    Diction Library: two stories for the test school (a school's
        students see only their own school's books), with no read-aloud
        made, so seeding never uses the paid voice
The 90 Quick Words, the assembly recitals and the Learning Modules
already on the site are used as they are.

Logins (password Test-2026), at "Level 1 Test School":
    p1.pupil     Grade 1 A student (no 44 Academy)
    p3.pupil     Grade 3 A student (with the 44 Academy)
    p1.teacher   teacher of Grade 1 A
    head@level1-test.example   the school admin
"""

from django.core.management.base import BaseCommand
from django.db import transaction

PASSWORD = "Test-2026"

GROUPS = [
    {"title": "Short a", "spelling": [("cat", "/kæt/", "A small pet that says miaow.", "The cat sat on the mat."),
                                      ("hat", "/hæt/", "You wear it on your head.", "Dad has a red hat."),
                                      ("bag", "/bæɡ/", "You carry things in it.", "My bag is blue."),
                                      ("man", "/mæn/", "A grown-up boy.", "The man can run."),
                                      ("map", "/mæp/", "A picture that shows the way.", "Look at the map.")],
     "vocab": [("jam", "/dʒæm/", "Sweet fruit you put on bread.", "I like jam on toast."),
               ("van", "/væn/", "A small truck.", "The van is fast.")],
     "passage": ("The Cat and the Hat", "A fat cat sat on a mat. A man had a hat. The hat was red. "
                                        "The cat ran to the hat and sat in it! The man said, \"Bad cat!\" "
                                        "The cat had a nap in the hat."),
     "dialogue": [("Ada", "Is that your cat?"), ("Tunde", "Yes, that is my cat."),
                  ("Ada", "What is its name?"), ("Tunde", "Its name is Sam.")],
     "missing": [("c_t", "cat"), ("h_t", "hat"), ("b_g", "bag"), ("m_p", "map")],
     "rhyme": [("cat", "hat", "hat\ncot\ncup"), ("man", "van", "van\npen\npin"), ("bag", "tag", "tag\nbig\nbug")],
     "sentence": ["The cat sat on the mat.", "Dad has a red hat."]},
    {"title": "Short e", "spelling": [("bed", "/bed/", "You sleep in it.", "I go to bed at eight."),
                                      ("hen", "/hen/", "A bird that lays eggs.", "The hen has an egg."),
                                      ("pen", "/pen/", "You write with it.", "My pen is black."),
                                      ("leg", "/leɡ/", "You walk with your legs.", "My leg is strong."),
                                      ("ten", "/ten/", "The number after nine.", "I have ten toes.")],
     "vocab": [("net", "/net/", "You catch fish with it.", "The net is wet."),
               ("web", "/web/", "A spider makes it.", "Look at the web!")],
     "passage": ("Ben and the Red Hen", "Ben has a red hen. The hen sits in a nest. Ben gets an egg. "
                                        "Then Ben gets ten eggs! Ben puts the eggs in a net. \"Well done, hen!\" said Ben."),
     "dialogue": [("Mum", "Where is your pen?"), ("Ben", "It is on my bed."),
                  ("Mum", "Please get it."), ("Ben", "Yes, Mum. Here it is.")],
     "missing": [("b_d", "bed"), ("h_n", "hen"), ("p_n", "pen"), ("l_g", "leg")],
     "rhyme": [("hen", "ten", "ten\ntin\ntan"), ("bed", "red", "red\nrod\nrid"), ("net", "wet", "wet\nwit\nwhat")],
     "sentence": ["The hen has an egg.", "My pen is on the bed."]},
    {"title": "Short i", "spelling": [("pig", "/pɪɡ/", "A farm animal that says oink.", "The pig is pink."),
                                      ("sit", "/sɪt/", "To rest on a chair.", "Please sit down."),
                                      ("big", "/bɪɡ/", "Not small.", "The tree is big."),
                                      ("fish", "/fɪʃ/", "It swims in water.", "The fish can swim."),
                                      ("milk", "/mɪlk/", "A white drink from cows.", "I drink milk.")],
     "vocab": [("lid", "/lɪd/", "The top of a pot or box.", "Put the lid on the pot."),
               ("tin", "/tɪn/", "A metal can.", "The tin is empty.")],
     "passage": ("The Big Pig", "Kim has a big pink pig. The pig likes to dig. It digs and digs in the mud. "
                                "Kim gives the pig some milk. The pig sits and drinks it all. \"What a big pig!\" said Kim."),
     "dialogue": [("Kim", "Can you swim?"), ("Jide", "Yes, I can swim like a fish."),
                  ("Kim", "Is the water big?"), ("Jide", "It is very big, but it is fun.")],
     "missing": [("p_g", "pig"), ("s_t", "sit"), ("f_sh", "fish"), ("m_lk", "milk")],
     "rhyme": [("pig", "big", "big\nbag\nbug"), ("sit", "hit", "hit\nhat\nhot"), ("fish", "dish", "dish\ndash\ndesk")],
     "sentence": ["The pig is pink.", "I can swim like a fish."]},
    {"title": "Short o", "spelling": [("dog", "/dɒɡ/", "A pet that barks.", "The dog can run."),
                                      ("hot", "/hɒt/", "Very warm.", "The tea is hot."),
                                      ("box", "/bɒks/", "You keep things in it.", "The toy is in the box."),
                                      ("top", "/tɒp/", "The highest part.", "The cup is on top."),
                                      ("pot", "/pɒt/", "You cook in it.", "Mum has a big pot.")],
     "vocab": [("log", "/lɒɡ/", "A piece of a tree.", "The frog sat on a log."),
               ("frog", "/frɒɡ/", "A green animal that jumps.", "The frog can hop.")],
     "passage": ("The Dog and the Frog", "A dog sat on a log. A frog hopped on top of the log. "
                                         "\"Hop, hop!\" said the frog. The dog got up and ran. "
                                         "The frog sat in the hot sun on top of the log."),
     "dialogue": [("Tolu", "Where is the dog?"), ("Emeka", "The dog is in the box."),
                  ("Tolu", "Is it hot in there?"), ("Emeka", "No, it is not hot. It is fine.")],
     "missing": [("d_g", "dog"), ("h_t", "hot"), ("b_x", "box"), ("p_t", "pot")],
     "rhyme": [("dog", "log", "log\nleg\nlag"), ("hot", "pot", "pot\npet\npit"), ("top", "mop", "mop\nmap\nmep")],
     "sentence": ["The dog can run.", "The frog sat on a log."]},
]

DIALOGUES = [
    (1, "monday", "Good Morning", "greet, morning, teacher, class",
     "Teacher: Good morning, class!\nClass: Good morning, teacher!\nTeacher: How are you today?\nClass: We are fine, thank you."),
    (2, "monday", "My Name Is", "name, nice, meet",
     "Ada: Hello! What is your name?\nTunde: My name is Tunde. What is your name?\nAda: My name is Ada.\nTunde: Nice to meet you, Ada."),
    (3, "monday", "At the Market", "market, mango, how much",
     "Child: Good afternoon, ma.\nSeller: Good afternoon. What do you want?\nChild: I want two mangoes, please.\nSeller: Here they are. Thank you!"),
]

LESSONS = {
    "tricks": ("Tricks", [
        ("The -ing Ending", "-ing", ["sing", "ring", "king", "swing"], ["The king can sing.", "I can swing on the swing."],
         "Sing a song of swinging kings."),
        ("Soft th", "th", ["thin", "thank", "three", "thumb"], ["Thank you for the three thin sticks.", "My thumb is sore."],
         "Three thin thinkers thinking thick thoughts."),
    ]),
    "academy": ("Short Vowels", [
        ("Short a /æ/", "æ", ["cat", "bat", "hat", "map"], ["The cat sat on the mat.", "Pass me the map."],
         "A fat cat sat on a flat mat."),
        ("Short e /e/", "e", ["bed", "red", "pen", "ten"], ["Ten red pens are on the bed.", "The hen is in the pen."],
         "Ben's red pen fell in the den."),
    ]),
}

STORIES = [
    ("The Little Red Kite", "A short story about a girl, her red kite and a windy day.",
     "Ada had a little red kite. One windy day she ran up the hill. The kite went up, up, up! "
     "\"Look at my kite!\" said Ada. The kite flew over the trees and over the river. Then the wind stopped, "
     "and the kite came down softly into Ada's hands."),
    ("Sam the Busy Ant", "A short story about working together.",
     "Sam was a small ant. Every day he carried food to his home. One day the food was too big. "
     "Sam called his friends. One, two, three, four ants came to help. Together they carried the food home. "
     "\"We can do big things together,\" said Sam."),
]


class Command(BaseCommand):
    help = "Add sample Level 1 content and test logins (safe to run again)."

    @transaction.atomic
    def handle(self, *args, **options):
        made = {}
        self._echospell(made)
        self._dialogues(made)
        self._lessons(made)
        school = self._school(made)
        self._library(school, made)
        for what, n in made.items():
            self.stdout.write(f"  {what}: {n} added")
        self.stdout.write(self.style.SUCCESS(
            f"Done. Sign in with p1.pupil, p3.pupil or p1.teacher (password {PASSWORD}) at {school.name}."))

    def _count(self, made, what, created):
        made[what] = made.get(what, 0) + int(bool(created))

    # ------------------------------------------------------------------ EchoSpell

    def _echospell(self, made):
        from apps.echospell.models import (
            Activity, ActivityItem, CardLesson, Category, Dialogue, DialogueLine, Group, Level, Passage,
        )

        level, _ = Level.objects.get_or_create(name="Level 1", defaults={"is_published": True})
        cats = {}
        for name, kind in (("Spelling", "words"), ("Passage Reading", "passage"), ("Dialogue", "dialogue"),
                           ("Vocabulary", "words")):
            cats[name] = Category.objects.filter(name=name).first() or Category.objects.create(name=name, kind=kind)
            level.categories.add(cats[name])
        for number, spec in enumerate(GROUPS, start=1):
            group, created = Group.objects.get_or_create(level=level, number=number, defaults={"title": spec["title"]})
            self._count(made, "EchoSpell groups", created)
            if not group.title or group.title == f"Group {number}":
                group.title = spec["title"]
                group.save(update_fields=["title"])
            for category, words in (("Spelling", spec["spelling"]), ("Vocabulary", spec["vocab"])):
                for order, (word, ipa, meaning, example) in enumerate(words, start=1):
                    _card, created = CardLesson.objects.get_or_create(
                        group=group, category=cats[category], word=word,
                        defaults={"ipa": ipa, "definition": meaning, "example_sentence": example, "order": order})
                    self._count(made, "word cards", created)
            if not Passage.objects.filter(group=group).exists():
                Passage.objects.create(group=group, title=spec["passage"][0], body=spec["passage"][1])
                self._count(made, "passages", True)
            if not Dialogue.objects.filter(group=group).exists():
                talk = Dialogue.objects.create(group=group, title=f"{spec['title']} talk")
                for order, (speaker, text) in enumerate(spec["dialogue"], start=1):
                    DialogueLine.objects.create(dialogue=talk, speaker=speaker, text=text, order=order)
                self._count(made, "dialogues (EchoSpell)", True)
            activities = [
                ("missing-letters", "Fill the gaps", [{"prompt": p, "answer": a} for p, a in spec["missing"]]),
                ("rhyme-match", "Find the rhyme", [{"prompt": p, "answer": a, "options": o} for p, a, o in spec["rhyme"]]),
                ("sentence-builder", "Build the sentence", [{"answer": a} for a in spec["sentence"]]),
            ]
            for order, (kind, title, items) in enumerate(activities, start=1):
                activity, created = Activity.objects.get_or_create(
                    group=group, kind=kind, title=title, defaults={"order": order, "pass_mark": 70})
                self._count(made, "activities", created)
                if created:
                    for n, item in enumerate(items, start=1):
                        ActivityItem.objects.create(activity=activity, order=n, **item)

    # ------------------------------------------------------- Conversational Dialogue

    def _dialogues(self, made):
        from apps.conversational_dialogue.models import Dialogue, DialogueLevel

        level, _ = DialogueLevel.objects.get_or_create(name="Level 1", defaults={"is_published": True})
        for week, day, title, words, script in DIALOGUES:
            _d, created = Dialogue.objects.get_or_create(
                level=level, title=title,
                defaults={"term": 1, "week": week, "day": day, "target_words": words, "script": script,
                          "is_published": True})
            self._count(made, "conversational dialogues", created)

    # ---------------------------------------------------- Tricks and the 44 Academy

    def _lessons(self, made):
        from apps.book.models import Sound, SoundCategory, SentencePractice, TongueTwister, WordBankEntry

        for programme, (category_name, lessons) in LESSONS.items():
            category = (SoundCategory.objects.filter(programme=programme, name=category_name).first()
                        or SoundCategory.objects.create(programme=programme, name=category_name))
            for order, (name, symbol, words, sentences, twister) in enumerate(lessons, start=1):
                sound, created = Sound.objects.get_or_create(
                    category=category, name=name,
                    defaults={"symbol": symbol, "example_words": ", ".join(words), "order": order, "is_published": True})
                self._count(made, "Tricks lessons" if programme == "tricks" else "44 Academy lessons", created)
                if created:
                    for n, word in enumerate(words, start=1):
                        WordBankEntry.objects.create(sound=sound, word=word, order=n)
                    for n, sentence in enumerate(sentences, start=1):
                        SentencePractice.objects.create(sound=sound, sentence=sentence, order=n)
                    TongueTwister.objects.create(sound=sound, text=twister, order=1)

    # ------------------------------------------------------------ School and logins

    def _school(self, made):
        from apps.accounts.models import User
        from apps.schools.classes import class_of_grade
        from apps.schools.models import School

        school, created = School.objects.get_or_create(name="Level 1 Test School",
                                                       defaults={"email": "school@level1-test.example"})
        self._count(made, "schools", created)
        p1 = class_of_grade(school, "primary_1", name="A")
        p3 = class_of_grade(school, "primary_3", name="A")
        people = [
            ("head@level1-test.example", None, "Head", "school_admin", "", None),
            ("p1.teacher@level1-test.example", "p1.teacher", "Grace", "teacher", "Level 1", None),
            ("p1.pupil@level1-test.example", "p1.pupil", "Ada", "student", "Level 1", p1),
            ("p3.pupil@level1-test.example", "p3.pupil", "Tunde", "student", "Level 3", p3),
        ]
        for email, username, first, role, level, school_class in people:
            if User.objects.filter(email=email).exists():
                continue
            extra = {"school_class": school_class} if school_class else {}
            User.objects.create_user(email, PASSWORD, username=username, first_name=first, last_name="Test",
                                     role=role, school=school, level=level, **extra)
            self._count(made, "logins", True)
        p1.teachers.add(User.objects.get(email="p1.teacher@level1-test.example"))
        return school

    def _library(self, school, made):
        from django.db.models.signals import post_save

        from apps.diction_library import narration
        from apps.diction_library.models import LibraryItem

        # Saving a story would start its read-aloud (paid ElevenLabs voice):
        # not for sample stories. Staff can still tick "Make the read-aloud again".
        post_save.disconnect(sender=LibraryItem, dispatch_uid="dm-library-narration")
        try:
            for title, summary, text in STORIES:
                item, created = LibraryItem.objects.get_or_create(
                    title=title, school=school,
                    defaults={"kind": "story", "summary": summary, "description": text, "is_published": True})
                if created:
                    LibraryItem.objects.filter(pk=item.pk).update(
                        narration_status="off", narration_note="Sample story: no read-aloud made.")
                self._count(made, "library stories", created)
        finally:
            post_save.connect(narration.when_saved, sender=LibraryItem, dispatch_uid="dm-library-narration")
