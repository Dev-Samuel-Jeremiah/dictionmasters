"""Create original, clearly labelled demo content for Diction Library and Diction Radio.

For local testing, point Django at SQLite and disable R2 for this command:
    DJANGO_DB=sqlite R2_ACCOUNT_ID= R2_BUCKET_NAME= R2_ACCESS_KEY_ID= R2_SECRET_ACCESS_KEY= \\
      python manage.py seed_demo_content

Audio samples are generated locally with espeak-ng and ffmpeg. Existing demo
slugs are left untouched, so this command is safe to run again.
"""

import shutil
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.diction_library.models import LibraryItem
from apps.diction_radio.models import RadioEpisode, RadioProgram


PROGRAMS = [
    {
        "slug": "demo-diction-in-a-minute",
        "title": "Diction in a Minute",
        "tagline": "Small practice. Clearer speech.",
        "description": "Short, friendly pronunciation lessons with a clear model and time to practise aloud. Demo narration is computer-generated for playback testing.",
        "presenter": "Sample voice",
        "order": 10,
        "episodes": [
            {
                "slug": "demo-think-three-and-thank-you",
                "title": "Think, Three and Thank You",
                "description": "Meet the quiet, unvoiced TH sound and practise it in everyday words.",
                "script": "Welcome to Diction in a Minute. Today we are practising the unvoiced TH sound.\n\nLet the tip of your tongue rest gently between your teeth. Push a little air out. Do not add a T sound.\n\nListen: think. Three. Thank you.\n\nNow you try: three thoughtful thinkers.\n\nKeep the air moving, and keep the sound light. Well done. You have been listening to Diction Radio.",
                "transcript": "Welcome to Diction in a Minute. Today we are practising the unvoiced TH sound. Let the tip of your tongue rest gently between your teeth. Push a little air out. Do not add a T sound. Listen: think. Three. Thank you. Now you try: three thoughtful thinkers. Keep the air moving, and keep the sound light. Well done. You have been listening to Diction Radio.",
                "order": 10,
            },
            {
                "slug": "demo-v-and-w-clear-difference",
                "title": "V and W: Hear the Difference",
                "description": "A simple lip position helps distinguish V from W.",
                "script": "This is Diction in a Minute. Let us make V and W easy to hear.\n\nFor V, place your top teeth lightly on your bottom lip and let your voice buzz: very, vivid, voice.\n\nFor W, round your lips without touching your teeth: water, window, wonderful.\n\nListen again: vine, wine. Vest, west.\n\nTry this sentence: Wendy gave Victor a warm welcome. Make each sound clear. Excellent practice.",
                "transcript": "For V, place your top teeth lightly on your bottom lip and let your voice buzz: very, vivid, voice. For W, round your lips without touching your teeth: water, window, wonderful. Listen: vine, wine; vest, west. Try: Wendy gave Victor a warm welcome.",
                "order": 20,
            },
        ],
    },
    {
        "slug": "demo-storytime-at-dusk",
        "title": "Storytime at Dusk",
        "tagline": "Original short stories, read aloud.",
        "description": "Settle in for original, family-friendly stories read aloud at an easy pace. Demo narration is computer-generated for playback testing.",
        "presenter": "Sample voice",
        "order": 20,
        "episodes": [
            {
                "slug": "demo-the-kite-that-would-not-hurry",
                "title": "The Kite That Would Not Hurry",
                "description": "A gentle story about patience, listening and a windy afternoon.",
                "script": "The Kite That Would Not Hurry.\n\nOn Saturday, Kemi carried a bright yellow kite to the field. The wind was blowing, but the kite stayed on the grass. Kemi ran faster. The kite still would not rise.\n\nHer grandfather smiled. Listen to the wind first, he said. Kemi held the string and waited. A quiet gust lifted the kite into the blue sky.\n\nKemi laughed. The kite had not needed a faster runner. It had needed the right moment. On the way home, she let her little brother hold the string too.",
                "transcript": "On Saturday, Kemi carried a bright yellow kite to the field. The wind was blowing, but the kite stayed on the grass. Kemi ran faster. The kite still would not rise. Her grandfather smiled. Listen to the wind first, he said. Kemi held the string and waited. A quiet gust lifted the kite into the blue sky. The kite had needed the right moment. On the way home, she let her little brother hold the string too.",
                "order": 10,
            },
            {
                "slug": "demo-mina-and-the-moonlit-market",
                "title": "Mina and the Moonlit Market",
                "description": "Mina discovers that a helpful neighbour can make a long day brighter.",
                "script": "Mina and the Moonlit Market.\n\nMina helped her mother close their little stall at the market. The evening rain had made the road shine like a ribbon. One basket remained, filled with oranges.\n\nA neighbour called Mr Bello was walking home. Mina offered him an orange for his walk. He thanked her, then helped carry the heavy basket.\n\nTogether they crossed the market square beneath the moon. Mina's mother said, A small kindness can light the whole road. Mina smiled, and the last orange went home with Mr Bello.",
                "transcript": "Mina helped her mother close their little stall at the market. The evening rain had made the road shine like a ribbon. One basket remained, filled with oranges. A neighbour called Mr Bello was walking home. Mina offered him an orange for his walk. He thanked her, then helped carry the heavy basket. Together they crossed the market square beneath the moon. Mina's mother said, a small kindness can light the whole road.",
                "order": 20,
            },
        ],
    },
    {
        "slug": "demo-speak-with-confidence",
        "title": "Speak with Confidence",
        "tagline": "Warm-ups for clear, confident speaking.",
        "description": "Short guided exercises for breath, pace, expression and speaking clearly in front of others. Demo narration is computer-generated for playback testing.",
        "presenter": "Sample voice",
        "order": 30,
        "episodes": [
            {
                "slug": "demo-a-calm-breath-before-speaking",
                "title": "A Calm Breath Before Speaking",
                "description": "A brief breathing and posture routine before reading or presenting.",
                "script": "Welcome to Speak with Confidence. Before you begin, let your shoulders relax. Sit or stand tall, with both feet resting comfortably.\n\nBreathe in gently through your nose. Let the air out slowly. Again, breathe in, and breathe out.\n\nChoose one thought you want your listener to remember. Say it once, slowly and clearly. Pause. Then say it again with a little more energy.\n\nYou do not need to rush. Your voice has room. Take a calm breath, and begin.",
                "transcript": "Relax your shoulders. Sit or stand tall, with both feet comfortable. Breathe in gently through your nose and let the air out slowly. Choose one thought you want your listener to remember. Say it slowly and clearly. Pause. Your voice has room. Take a calm breath, and begin.",
                "order": 10,
            },
            {
                "slug": "demo-stress-the-words-that-matter",
                "title": "Stress the Words That Matter",
                "description": "Practise giving important words more energy while keeping a natural rhythm.",
                "script": "In this speaking warm-up, we will use word stress to help our meaning stand out.\n\nSay this sentence: I would like to borrow your book.\n\nNow give borrow a little more energy: I would like to borrow your book.\n\nNow stress your: I would like to borrow your book.\n\nThe words that matter can change with what you want to say. Keep the other words light, and let your important word shine. Try it once more in your own voice.",
                "transcript": "Say: I would like to borrow your book. Give borrow a little more energy. Now stress your. The words that matter can change with what you want to say. Keep the other words light, and let your important word shine.",
                "order": 20,
            },
        ],
    },
]

LIBRARY_ITEMS = [
    {
        "slug": "demo-clear-speech-starter",
        "title": "The Clear Speech Starter",
        "kind": LibraryItem.Kind.BOOK,
        "summary": "A short printable starter guide to clear sounds, careful listening and confident practice.",
        "description": "A demo reader for Diction Library.\n\nStart with one sound at a time. Listen to the model, notice where your lips and tongue move, and say the word slowly. Then use it in a sentence.\n\nPractice words: think, three, voice, window, sheep, ship.\n\nA helpful routine: listen, repeat, record yourself, and try once more.",
        "filename": "clear-speech-starter.txt",
        "content": "THE CLEAR SPEECH STARTER\n\nA Diction Masters demo reader\n\nStart with one sound at a time. Listen to the model, notice where your lips and tongue move, and say the word slowly. Then use it in a sentence.\n\nPractice words: think, three, voice, window, sheep, ship.\n\nA helpful routine: listen, repeat, record yourself, and try once more.\n",
    },
    {
        "slug": "demo-the-kite-that-would-not-hurry",
        "title": "The Kite That Would Not Hurry",
        "kind": LibraryItem.Kind.STORY,
        "summary": "An original short story about patience, listening and sharing.",
        "description": "On Saturday, Kemi carried a bright yellow kite to the field. The wind was blowing, but the kite stayed on the grass. Kemi ran faster. The kite still would not rise.\n\nHer grandfather smiled. Listen to the wind first, he said. Kemi held the string and waited. A quiet gust lifted the kite into the blue sky.\n\nKemi laughed. The kite had not needed a faster runner. It had needed the right moment. On the way home, she let her little brother hold the string too.",
        "filename": "the-kite-that-would-not-hurry.txt",
        "content": "THE KITE THAT WOULD NOT HURRY\n\nOn Saturday, Kemi carried a bright yellow kite to the field. The wind was blowing, but the kite stayed on the grass. Kemi ran faster. The kite still would not rise.\n\nHer grandfather smiled. Listen to the wind first, he said. Kemi held the string and waited. A quiet gust lifted the kite into the blue sky.\n\nKemi laughed. The kite had not needed a faster runner. It had needed the right moment. On the way home, she let her little brother hold the string too.\n",
    },
    {
        "slug": "demo-first-listening-practice",
        "title": "Listen and Practise: The TH Sound",
        "kind": LibraryItem.Kind.AUDIO,
        "summary": "A short guided TH pronunciation track. Sample audio is synthesised for feature testing.",
        "description": "Listen to the short model and practise along. The same track is part of the Diction in a Minute radio programme.",
        "filename": "listen-practise-th.mp3",
        "radio_episode_slug": "demo-think-three-and-thank-you",
    },
    {
        "slug": "demo-diction-radio-video-preview",
        "title": "Diction Radio: Video Preview",
        "kind": LibraryItem.Kind.VIDEO,
        "summary": "A short branded video with a spoken sample track to check Library video playback.",
        "description": "Demo video generated locally for testing. It is not a published lesson.",
        "filename": "diction-radio-video-preview.mp4",
        "video_sample": True,
    },
    {
        "slug": "demo-weekly-listening-challenge",
        "title": "Weekly Listening Challenge",
        "kind": LibraryItem.Kind.OTHER,
        "summary": "A five-minute listening and speaking routine for the week.",
        "description": "1. Choose an episode from Diction Radio.\n2. Listen once without pausing.\n3. Read the transcript and mark three words you want to practise.\n4. Listen again and repeat each phrase.\n5. Record yourself and notice one improvement.",
    },
]


class Command(BaseCommand):
    help = "Add original sample books, stories and speech audio for Diction Library and Diction Radio."

    def add_arguments(self, parser):
        parser.add_argument(
            "--allow-r2", action="store_true",
            help="Use configured Cloudflare R2 storage for demo media files.",
        )

    def handle(self, *args, **options):
        if settings.PRODUCTION:
            raise CommandError("Demo content is disabled in production.")
        if settings.R2_CONFIGURED and not options["allow_r2"]:
            raise CommandError(
                "R2 is configured. Use --allow-r2 to upload demo media to the configured bucket, "
                "or set the R2 environment values to empty strings to keep the files local."
            )
        espeak = shutil.which("espeak-ng")
        ffmpeg = shutil.which("ffmpeg")
        if not espeak or not ffmpeg:
            raise CommandError("Local demo audio generation needs espeak-ng and ffmpeg installed.")

        with tempfile.TemporaryDirectory(prefix="diction-radio-demo-") as scratch:
            audio_paths = self._generate_audio(Path(scratch), espeak, ffmpeg)
            audio_paths["__video_sample__"] = self._generate_video(
                Path(scratch), ffmpeg, audio_paths["demo-think-three-and-thank-you"]
            )
            self._seed(audio_paths)

    def _generate_audio(self, scratch, espeak, ffmpeg):
        paths = {}
        for program in PROGRAMS:
            for episode in program["episodes"]:
                wav_path = scratch / f"{episode['slug']}.wav"
                mp3_path = scratch / f"{episode['slug']}.mp3"
                subprocess.run(
                    [espeak, "-v", "en-gb", "-s", "140", "-p", "48", "-w", str(wav_path), episode["script"]],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                subprocess.run(
                    [ffmpeg, "-y", "-loglevel", "error", "-i", str(wav_path), "-codec:a", "libmp3lame", "-b:a", "64k", str(mp3_path)],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                paths[episode["slug"]] = mp3_path
        return paths

    def _generate_video(self, scratch, ffmpeg, audio_path):
        output = scratch / "diction-radio-video-preview.mp4"
        font = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
        text_filter = (
            f"drawtext=fontfile={font}:text='DICTION MASTERS':fontcolor=0xe4b866:fontsize=64:"
            "x=(w-text_w)/2:y=(h-text_h)/2-25,"
            f"drawtext=fontfile={font}:text='LISTEN  LEARN  SPEAK':fontcolor=white:fontsize=28:"
            "x=(w-text_w)/2:y=(h-text_h)/2+65"
        )
        subprocess.run(
            [ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi", "-i",
             "color=c=0x14213d:s=1280x720:r=24:d=8", "-i", str(audio_path),
             "-vf", text_filter, "-t", "8", "-c:v", "libx264", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(output)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return output

    @transaction.atomic
    def _seed(self, audio_paths):
        for program_data in PROGRAMS:
            program_values = {key: program_data[key] for key in ("title", "tagline", "description", "presenter", "order")}
            program, created = RadioProgram.objects.get_or_create(slug=program_data["slug"], defaults=program_values)
            self.stdout.write(f"{'Added' if created else 'Kept'} radio programme: {program.title}")
            for episode_data in program_data["episodes"]:
                episode_values = {
                    "program": program,
                    "title": episode_data["title"],
                    "description": episode_data["description"],
                    "transcript": episode_data["transcript"],
                    "order": episode_data["order"],
                }
                episode, episode_created = RadioEpisode.objects.get_or_create(
                    slug=episode_data["slug"], defaults=episode_values
                )
                if episode_created:
                    with audio_paths[episode_data["slug"]].open("rb") as source:
                        episode.audio_file.save(f"{episode.slug}.mp3", File(source), save=False)
                    episode.full_clean()
                    episode.save()
                self.stdout.write(f"  {'Added' if episode_created else 'Kept'} episode: {episode.title}")

        for item_data in LIBRARY_ITEMS:
            values = {key: item_data[key] for key in ("title", "kind", "summary", "description")}
            item, created = LibraryItem.objects.get_or_create(slug=item_data["slug"], defaults=values)
            if "filename" in item_data and (created or not item.file):
                if "radio_episode_slug" in item_data:
                    file_path = audio_paths[item_data["radio_episode_slug"]]
                elif item_data.get("video_sample"):
                    file_path = audio_paths["__video_sample__"]
                else:
                    file_path = None
                if file_path:
                    with file_path.open("rb") as source:
                        item.file.save(item_data["filename"], File(source), save=False)
                else:
                    item.file.save(item_data["filename"], ContentFile(item_data["content"].encode("utf-8")), save=False)
                item.save()
            self.stdout.write(f"{'Added' if created else 'Kept'} library item: {item.title}")
