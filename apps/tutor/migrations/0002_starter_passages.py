"""A first shelf of passages, one or two per level, so the tutor is
ready to use the day it goes live. Staff can edit or replace them."""

from django.db import migrations

PASSAGES = [
    ("My Red Hat", "Pre-Level", "A short first reading.",
     "I have a red hat. My hat is on the bed. The cat sat on my hat! Get up, cat. "
     "Now my hat is flat. I will fix it. Look, my hat is big and red again."),
    ("The Big Bus", "Level 1", "Getting to school.",
     "Every morning, Ada and her brother wait for the big yellow bus. The bus stops at the gate. "
     "They climb up the steps and find a seat by the window.\n\n"
     "Ada waves to her mother. Her brother counts the cars on the road. \"Three red cars!\" he says. "
     "Soon they are at school, happy and ready to learn."),
    ("Thank You, Grandmother", "Level 2", "Visiting the village.",
     "On Thursday, Tunde visited his grandmother in the village. She lives in a small house with a very "
     "old mango tree beside it.\n\n"
     "Grandmother gave him a bowl of hot pepper soup and three ripe mangoes. \"Thank you, Grandmother,\" "
     "Tunde said. \"This is the best soup in the whole world.\" She laughed and told him stories until "
     "the stars came out."),
    ("The Village Market", "Level 3", "Colours, voices and things to buy.",
     "The village market is busiest on Saturday mornings. Traders arrive before sunrise to arrange their "
     "vegetables, fabrics and baskets of fruit.\n\n"
     "Voices fill the air as buyers and sellers agree on prices. A woman sells fresh fish beside a man with "
     "bright blue cloth. Children weave between the stalls, carrying bags that are almost as big as they are.\n\n"
     "By midday the sun is hot, and most of the vegetables have gone. The traders count their money, pack "
     "their things and think about next week."),
    ("The Clever Tortoise", "Level 4", "A folk tale.",
     "Long ago, the animals of the forest decided to hold a great feast in the sky. The birds lent their "
     "feathers to Tortoise so that he could fly with them.\n\n"
     "Before they left, Tortoise announced that everyone should take a new name for the journey. He chose "
     "the name \"All of You\". When the food arrived, the hosts said, \"This feast is for all of you.\" "
     "Tortoise smiled and ate nearly everything.\n\n"
     "The angry birds took back their feathers, and Tortoise had to jump. He landed on the hard ground, "
     "and that, the story says, is why his shell is cracked to this very day."),
    ("Saving Water", "Level 5", "Why every drop matters.",
     "Water is one of the most valuable things we have, yet it is easy to waste. A tap left running while "
     "we brush our teeth can throw away several litres every minute.\n\n"
     "There are many simple ways to save water. We can collect rainwater in clean containers and use it to "
     "wash vegetables or water the garden. We can fix dripping taps quickly and take shorter baths.\n\n"
     "When everybody in a community makes small changes, the difference is enormous. Saving water today "
     "means there will be enough for the families who come after us."),
    ("The Inventor's Workshop", "Level 6", "Thinking through a problem.",
     "Chiamaka had always been fascinated by the way things worked. Her father's workshop, full of wires, "
     "batteries and broken radios, was her favourite place in the world.\n\n"
     "One evening, the electricity failed while her brother was revising for his examinations. Chiamaka "
     "thought carefully about the problem. Using an old battery, a small bulb and some wire, she built a "
     "reading lamp that could be charged during the day.\n\n"
     "Her brother finished his revision, and the next morning her teacher asked her to show the whole "
     "class. \"Every invention begins with a problem,\" her teacher said, \"and with someone brave enough "
     "to think about it differently.\""),
    ("Voices of the River", "Level 8", "A descriptive passage.",
     "The river moves slowly through the valley, gathering the thoughts of every village it passes. At dawn "
     "the fishermen push their canoes into the silver water, their voices drifting across the surface like "
     "smoke.\n\n"
     "Throughout the day the river is never silent. Women gather at its banks to wash clothes and exchange "
     "news, while children practise their swimming in the shallow bends. Even the birds seem to rehearse "
     "their songs above its gentle current.\n\n"
     "Although the river has witnessed floods and droughts, celebrations and farewells, it continues its "
     "journey with remarkable patience. Perhaps that is the river's greatest lesson: whatever happens, "
     "keep moving thoughtfully forward."),
]


def add(apps, schema_editor):
    TutorPassage = apps.get_model("tutor", "TutorPassage")
    for order, (title, level, summary, body) in enumerate(PASSAGES):
        TutorPassage.objects.get_or_create(
            title=title, defaults={"level": level, "summary": summary, "body": body, "order": order},
        )


def remove(apps, schema_editor):
    TutorPassage = apps.get_model("tutor", "TutorPassage")
    TutorPassage.objects.filter(title__in=[p[0] for p in PASSAGES], sessions__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [("tutor", "0001_initial")]
    operations = [migrations.RunPython(add, remove)]
