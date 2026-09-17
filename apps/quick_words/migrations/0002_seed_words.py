"""The starting word library.

Fifty words a Nigerian primary/secondary learner meets constantly, each
with its British English transcription, a plain-language meaning and a
sentence that shows it in use. Words are matched on spelling, so
re-running this never duplicates a row, and reversing it removes only
the words seeded here.
"""

from django.db import migrations
from django.utils.text import slugify

WORDS = [
    ("achieve", "/əˈtʃiːv/", "To successfully reach a goal through effort.", "She worked hard to achieve excellent results.", "Level 5"),
    ("articulate", "/ɑːˈtɪkjʊlət/", "Able to speak clearly and fluently.", "An articulate teacher models sounds clearly.", "Level 7"),
    ("breathe", "/briːð/", "To take air into the lungs and send it out.", "Breathe deeply and relax your vocal cords.", "Level 3"),
    ("calm", "/kɑːm/", "Not showing nervousness; peaceful.", "The teacher remained calm when the students were noisy.", "Level 3"),
    ("clear", "/klɪə/", "Easy to understand; not confused.", "Please speak in a clear voice.", "Level 2"),
    ("communicate", "/kəˈmjuːnɪkeɪt/", "To share information with others.", "Communicate clearly in both written and spoken English.", "Level 6"),
    ("confidence", "/ˈkɒnfɪdəns/", "The feeling of being certain about your abilities.", "Daily practice builds confidence in speaking.", "Level 5"),
    ("confident", "/ˈkɒnfɪdənt/", "Feeling certain about your own ability.", "Students become more confident through daily practice.", "Level 4"),
    ("correct", "/kəˈrekt/", "Free from errors; right.", "Always correct a student kindly.", "Level 3"),
    ("deliberate", "/dɪˈlɪbərət/", "Done on purpose, with care.", "Every sound must be produced with deliberate care.", "Level 7"),
    ("demonstrate", "/ˈdemənstreɪt/", "To clearly show how something is done.", "The teacher will demonstrate the correct mouth position.", "Level 5"),
    ("develop", "/dɪˈveləp/", "To grow or become better.", "Students develop pronunciation through daily practice.", "Level 4"),
    ("difference", "/ˈdɪfrəns/", "A way in which things are not the same.", "Can you hear the difference between long EE and short I?", "Level 3"),
    ("discipline", "/ˈdɪsɪplɪn/", "Training to obey rules; controlled behaviour.", "Good discipline helps every student learn.", "Level 5"),
    ("dream", "/driːm/", "A hope or ambition.", "Every teacher should dream of a class that speaks clearly.", "Level 2"),
    ("education", "/edjʊˈkeɪʃən/", "The process of teaching and learning.", "Quality education begins with clear communication.", "Level 6"),
    ("excellent", "/ˈeksələnt/", "Extremely good; outstanding.", "The students gave an excellent performance.", "Level 3"),
    ("explain", "/ɪkˈspleɪn/", "To make something clear and easy to understand.", "Always explain the difficult sound before teaching it.", "Level 3"),
    ("fluency", "/ˈfluːənsi/", "The ability to speak a language easily and accurately.", "Fluency needs both accuracy and natural speed.", "Level 6"),
    ("improve", "/ɪmˈpruːv/", "To make or become better.", "You can only improve through consistent daily practice.", "Level 3"),
    ("intonation", "/ɪntəˈneɪʃən/", "The rise and fall of the voice in speaking.", "British English uses falling intonation for wh-questions.", "Level 8"),
    ("knowledge", "/ˈnɒlɪdʒ/", "Facts and skills gained through experience.", "Deep knowledge of the 44 sounds builds real confidence.", "Level 5"),
    ("language", "/ˈlæŋɡwɪdʒ/", "The way humans communicate using words.", "English is the official language of instruction in Nigeria.", "Level 3"),
    ("listen", "/ˈlɪsən/", "To pay attention to a sound.", "Always tell students to listen before they speak.", "Level 2"),
    ("morning", "/ˈmɔːnɪŋ/", "The period from sunrise to noon.", "Every morning we begin with a pronunciation warm-up.", "Level 2"),
    ("natural", "/ˈnætʃərəl/", "Normal; not forced or artificial.", "With practice British pronunciation will feel natural.", "Level 5"),
    ("patience", "/ˈpeɪʃəns/", "The ability to wait without becoming annoyed.", "Teaching pronunciation requires enormous patience.", "Level 5"),
    ("performance", "/pəˈfɔːməns/", "The act of presenting a skill to others.", "A great performance begins with mastery of each sound.", "Level 6"),
    ("position", "/pəˈzɪʃən/", "The place where something is located.", "The position of your tongue determines each sound.", "Level 5"),
    ("practise", "/ˈpræktɪs/", "To do something repeatedly to get better at it.", "Students must practise each sound until it is automatic.", "Level 3"),
    ("precision", "/prɪˈsɪʒən/", "The quality of being exact and accurate.", "Precision separates a good speaker from a great one.", "Level 7"),
    ("pronunciation", "/prənʌnsɪˈeɪʃən/", "The way in which a word is spoken.", "Correct pronunciation is the foundation of communication.", "Level 6"),
    ("quality", "/ˈkwɒlɪti/", "How good something is compared with others.", "The quality of a teacher's voice affects how students learn.", "Level 5"),
    ("reach", "/riːtʃ/", "To arrive at or achieve something.", "Every student can reach a high level of pronunciation.", "Level 2"),
    ("repeat", "/rɪˈpiːt/", "To say or do again.", "Listen to the audio and repeat each word three times.", "Level 2"),
    ("rhythm", "/ˈrɪðəm/", "A strong regular pattern of sound.", "British English has a stress-timed rhythm.", "Level 7"),
    ("school", "/skuːl/", "A place where children are taught.", "Every Nigerian school needs a pronunciation programme.", "Level 1"),
    ("speak", "/spiːk/", "To say words; to use the voice.", "Encourage every student to speak loudly and clearly.", "Level 1"),
    ("stress", "/stres/", "Extra force given to a syllable or word.", "Word stress decides whether a word is a noun or a verb.", "Level 6"),
    ("student", "/ˈstjuːdənt/", "A person who is studying at a school.", "Every student deserves a teacher who models pronunciation.", "Level 2"),
    ("syllable", "/ˈsɪləbəl/", "A unit of pronunciation with one vowel sound.", "Comfortable has three syllables in British English.", "Level 6"),
    ("teacher", "/ˈtiːtʃə/", "A person who teaches at a school.", "A great teacher performs the sound, not just explains it.", "Level 1"),
    ("tongue", "/tʌŋ/", "The muscle in the mouth used for speaking.", "Place your tongue between your teeth for the TH sound.", "Level 3"),
    ("understand", "/ʌndəˈstænd/", "To know the meaning of something.", "Students cannot understand a teacher with unclear speech.", "Level 3"),
    ("village", "/ˈvɪlɪdʒ/", "A small settlement in a rural area.", "Victor visited the village every evening.", "Level 3"),
    ("vocabulary", "/vəˈkæbjʊləri/", "All the words used in a language.", "A rich vocabulary allows more precise explanation.", "Level 6"),
    ("voice", "/vɔɪs/", "The sound made when speaking or singing.", "Your voice is your most powerful teaching tool.", "Level 2"),
    ("vowel", "/ˈvaʊəl/", "A speech sound made with the mouth open.", "British English has twenty vowel sounds.", "Level 4"),
    ("warmth", "/wɔːmθ/", "Friendliness and kindness.", "Warmth in a teacher's voice makes students feel safe.", "Level 5"),
    ("whisper", "/ˈwɪspə/", "To speak very softly using breath.", "Even when you whisper, consonants must stay precise.", "Level 4"),
]


def add_words(apps, schema_editor):
    QuickWord = apps.get_model("quick_words", "QuickWord")
    for word, ipa, definition, example, level in WORDS:
        QuickWord.objects.get_or_create(
            word=word,
            defaults={
                "slug": slugify(word),
                "ipa": ipa,
                "definition": definition,
                "example_sentence": example,
                "level": level,
            },
        )


def remove_words(apps, schema_editor):
    QuickWord = apps.get_model("quick_words", "QuickWord")
    QuickWord.objects.filter(word__in=[w[0] for w in WORDS]).delete()


class Migration(migrations.Migration):

    dependencies = [("quick_words", "0001_initial")]

    operations = [migrations.RunPython(add_words, remove_words)]
