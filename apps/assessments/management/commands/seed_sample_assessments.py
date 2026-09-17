"""
Add one ready-made assessment of each type, to learn the admin forms
from and to try the learner experience end to end.

They focus on the sounds Nigerian learners are most often corrected on —
TH, V and the long vowels. An assessment whose slug already exists is
left untouched, so running this again never overwrites your edits.

    python manage.py seed_sample_assessments
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from apps.assessments.models import Assessment, Question

C, T, S, K = Question.Type.CHOICE, Question.Type.TRANSCRIBE, Question.Type.SPELL, Question.Type.SPEAK

SAMPLES = [
    {
        "title": "Tricky sounds — practice quiz",
        "kind": Assessment.Kind.PRACTICE,
        "level": "Level 3",
        "summary": "Warm up on TH, V and long vowels, with an explanation for every answer.",
        "pass_mark": 70,
        "questions": [
            (C, "Which is the correct phonemic transcription of CHURCH?", "", "/ʃɜːʃ/\n/tʃɜːtʃ/\n/tʃɜːʃ/\n/ʃɜːtʃ/", "/tʃɜːtʃ/",
             "CHURCH starts and ends with the CH sound /tʃ/, so both ends need it: /tʃɜːtʃ/."),
            (C, "Which vowel sound is in FATHER?", "FATHER", "/æ/\n/ɑː/\n/ɒ/\n/ʌ/", "/ɑː/",
             "FATHER uses the long AH /ɑː/ — the mouth opens wide, and the R isn't pronounced in British English."),
            (T, "Type the phonemic transcription.", "THINK", "", "/θɪŋk/",
             "THINK is /θɪŋk/ — voiceless TH, short I, then NG and K. Saying 'tink' swaps the TH for a T."),
            (C, "Which word has the long /iː/ sound?", "", "ship\nsheep\nshop\nshape", "sheep",
             "SHEEP holds a long /iː/. SHIP has the short /ɪ/ — hold the vowel longer to tell them apart."),
            (S, "This word is misspelt: RECIEVE. Type it correctly.", "", "", "receive",
             "After C the rule is E before I: receive, ceiling, deceive."),
        ],
    },
    {
        "title": "TH and V — timed test",
        "kind": Assessment.Kind.TIMED,
        "level": "Level 4",
        "summary": "Ten minutes, two attempts. Answers are saved as you go.",
        "time_limit_minutes": 10,
        "max_attempts": 2,
        "pass_mark": 70,
        "instructions": "Work steadily — every question is worth one mark, and blank answers score nothing.",
        "questions": [
            (C, "Which transcription shows the word BATH?", "BATH", "/bæθ/\n/bɑːθ/\n/bɑːð/\n/bæð/", "/bɑːθ/",
             "BATH in British English has the long AH /ɑː/ and a voiceless TH /θ/."),
            (C, "In the word THE, the TH sound is…", "THE", "voiceless /θ/\nvoiced /ð/\na T sound\na D sound", "voiced /ð/",
             "THE uses the voiced TH /ð/ — your throat buzzes. Saying 'de' is the most common error."),
            (T, "Type the phonemic transcription.", "VERY", "", "/ˈveri/",
             "VERY begins with /v/: upper teeth on the lower lip. 'Bery' swaps it for /b/."),
            (T, "Type the phonemic transcription.", "MOTHER", "", "/ˈmʌðə/",
             "MOTHER has the voiced TH /ð/ in the middle and no R sound at the end: /ˈmʌðə/."),
            (C, "Which word begins with the voiceless TH /θ/?", "", "this\nthat\nthree\nthose", "three",
             "THREE starts with /θ/ — air flows over the tongue with no buzz. THIS, THAT and THOSE use /ð/."),
            (S, "Spell the number that comes after two.", "", "", "three", "THREE — T, H, R, E, E."),
        ],
    },
    {
        "title": "Read aloud — TH sounds",
        "kind": Assessment.Kind.SPEAKING,
        "level": "Level 4",
        "summary": "Record yourself reading. Your teacher scores sounds, stress, articulation, pace and rhythm.",
        "pass_mark": 60,
        "instructions": "Read each line clearly at a natural pace. Listen back before you send it.",
        "questions": [
            (K, "Read this tongue twister aloud, slowly and clearly.", "", "", "",
             "Three thin threads were thrown through the cloth."),
            (K, "Read this sentence aloud.", "", "", "",
             "The weather was smooth, so the brothers gathered together."),
            (C, "Before you record: is the TH in THREE voiced or voiceless?", "THREE", "voiced\nvoiceless", "voiceless",
             "THREE uses the voiceless /θ/ — no buzz in the throat."),
        ],
        "prompt_extras": {
            0: "Three thin threads were thrown through the cloth.",
            1: "The weather was smooth, so the brothers gathered together.",
        },
    },
    {
        "title": "EchoSpell placement test",
        "kind": Assessment.Kind.PLACEMENT,
        "summary": "Easy to hard — tells you which EchoSpell level to start at.",
        "time_limit_minutes": 12,
        "pass_mark": 50,
        "instructions": "Some of these will feel hard. That's expected — answer what you can.",
        "questions": [
            (S, "Spell the word: something you drink tea from.", "", "", "cup", "", "Level 1"),
            (C, "Which word rhymes with CAT?", "", "hat\ncup\ndog", "hat", "", "Level 1"),
            (S, "Spell the word: the opposite of night.", "", "", "day", "", "Level 2"),
            (C, "Which word has a silent K?", "", "kite\nknee\nkick", "knee", "", "Level 2"),
            (C, "Which vowel sound is in SHEEP?", "SHEEP", "/ɪ/\n/iː/\n/e/", "/iː/", "", "Level 3"),
            (T, "Type the phonemic transcription.", "CUP", "", "/kʌp/", "", "Level 3"),
            (C, "Where is the stress in COMPUTER?", "COMPUTER", "COM-pu-ter\ncom-PU-ter\ncom-pu-TER", "com-PU-ter", "", "Level 4"),
            (T, "Type the phonemic transcription.", "THINK", "", "/θɪŋk/", "", "Level 4"),
            (T, "Type the phonemic transcription.", "ACHIEVE", "", "/əˈtʃiːv/", "", "Level 5"),
            (C, "Which is the correct transcription of PRONUNCIATION?", "",
             "/prəˌnaʊnsiˈeɪʃən/\n/prəˌnʌnsiˈeɪʃən/\n/prəˌnʌnsɪˈeʃən/", "/prəˌnʌnsiˈeɪʃən/", "", "Level 5"),
        ],
    },
]


class Command(BaseCommand):
    help = "Add one sample assessment of each type (skips any that already exist)."

    @transaction.atomic
    def handle(self, *args, **options):
        for sample in SAMPLES:
            data = dict(sample)
            questions = data.pop("questions")
            extras = data.pop("prompt_extras", {})
            slug = slugify(data["title"])
            if Assessment.objects.filter(slug=slug).exists():
                self.stdout.write(f"  exists   {data['title']}")
                continue

            assessment = Assessment.objects.create(slug=slug, **data)
            for order, row in enumerate(questions, start=1):
                qtype, prompt, word, options, answer, explanation, *rest = row
                if qtype == K:
                    prompt = f"{prompt}\n\n“{extras.get(order - 1, explanation)}”"
                    explanation = ""
                question = Question(
                    assessment=assessment, order=order, type=qtype, prompt=prompt, word=word,
                    options=options, answer=answer, explanation=explanation,
                    points=3 if qtype == K else 1, level=rest[0] if rest else "",
                )
                question.full_clean()
                question.save()
            self.stdout.write(self.style.SUCCESS(f"  added    {assessment.title} ({len(questions)} questions)"))
