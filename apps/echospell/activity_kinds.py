"""
The catalogue of EchoSpell activity types.

An activity's *kind* is what the learner is asked to do ("transcribe
this word", "spot the silent letter"). Its *mode* is how the answer is
given and marked. Many kinds share a mode — Transcription and Dictation
are both typed answers — so templates and the marker only ever branch
on the five modes, and adding a new exercise type is one entry here
rather than a new model, view and template.

Modes:
  typed   free text, marked against the answer (alternatives with "|")
  choice  one option from a list
  sort    drag each prompt into the bucket it belongs to
  order   drag shuffled words into the right sequence
  record  read/say it aloud and record — marked by a teacher, not code
"""

from dataclasses import dataclass, field

MODE_TYPED = "typed"
MODE_CHOICE = "choice"
MODE_SORT = "sort"
MODE_ORDER = "order"
MODE_RECORD = "record"

MODE_LABELS = {
    MODE_TYPED: "Typed answer",
    MODE_CHOICE: "Multiple choice",
    MODE_SORT: "Drag into boxes",
    MODE_ORDER: "Drag into order",
    MODE_RECORD: "Record your voice",
}

AUTO_MARKED_MODES = {MODE_TYPED, MODE_CHOICE, MODE_SORT, MODE_ORDER}


@dataclass(frozen=True)
class ActivityKind:
    slug: str
    label: str
    mode: str
    icon: str
    summary: str
    instructions: str
    prompt_help: str
    answer_help: str
    placeholder: str = ""
    options_help: str = ""
    needs_audio: bool = False
    # False where the audio *is* the question, so showing the word
    # would give the answer away.
    uses_prompt: bool = True
    uses_image: bool = False
    tags: tuple = field(default_factory=tuple)

    @property
    def mode_label(self):
        return MODE_LABELS[self.mode]

    @property
    def is_auto_marked(self):
        return self.mode in AUTO_MARKED_MODES

    @property
    def activity_fields(self):
        """Fields on the activity itself that this kind actually uses,
        out of those that aren't relevant to every kind."""
        return ["buckets"] if self.mode == MODE_SORT else []

    @property
    def item_fields(self):
        """Fields on each question that this kind actually uses."""
        used = ["hint"]
        if self.uses_prompt:
            used.append("prompt")
        if self.mode != MODE_RECORD:
            used.append("answer")
        if self.mode == MODE_CHOICE:
            used.append("options")
        if self.needs_audio:
            used += ["audio_file", "audio_url"]
        if self.uses_image:
            used.append("image")
        return used


KINDS = [
    # ---- typed answers --------------------------------------------------
    ActivityKind(
        slug="transcription",
        label="Transcription",
        mode=MODE_TYPED,
        icon="🔤",
        summary="See a word, type its phonemic transcription.",
        instructions="Read each word, then type its phonemic transcription.",
        prompt_help="The word as it is spelt, e.g. achieve",
        answer_help="The transcription, e.g. /əˈtʃiːv/ — slashes optional",
        placeholder="/…/",
        tags=("phonemics", "writing"),
    ),
    ActivityKind(
        slug="dictation",
        label="Spelling dictation",
        mode=MODE_TYPED,
        icon="🎧",
        summary="Listen to a word, type how it is spelt.",
        instructions="Listen to each word, then type it exactly as it is spelt.",
        prompt_help="Leave blank to reveal nothing — the audio is the question",
        answer_help="The correctly spelt word",
        placeholder="Type what you hear",
        needs_audio=True,
        uses_prompt=False,
        tags=("listening", "spelling"),
    ),
    ActivityKind(
        slug="missing-letters",
        label="Missing letters",
        mode=MODE_TYPED,
        icon="✏️",
        summary="Fill the gaps in a part-spelt word.",
        instructions="Fill in the missing letters and type the whole word.",
        prompt_help="The word with gaps, e.g. b_tt_r",
        answer_help="The complete word, e.g. butter",
        placeholder="Type the whole word",
        tags=("spelling",),
    ),
    ActivityKind(
        slug="word-scramble",
        label="Puzzle — word scramble",
        mode=MODE_TYPED,
        icon="🧩",
        summary="Unscramble jumbled letters into a word.",
        instructions="Unscramble the letters and type the word they spell.",
        prompt_help="The scrambled letters, e.g. tbrteu",
        answer_help="The word, e.g. butter",
        placeholder="Type the word",
        tags=("spelling", "puzzle"),
    ),
    ActivityKind(
        slug="syllable-count",
        label="Syllable count",
        mode=MODE_TYPED,
        icon="🔢",
        summary="Count the syllables in a word.",
        instructions="Say each word aloud, then type how many syllables it has.",
        prompt_help="The word, e.g. beautiful",
        answer_help="The number of syllables, e.g. 3",
        placeholder="0",
        tags=("rhythm",),
    ),
    ActivityKind(
        slug="spelling-fix",
        label="Correct the spelling",
        mode=MODE_TYPED,
        icon="🩹",
        summary="Rewrite a misspelt word correctly.",
        instructions="Each word below is spelt wrongly. Type the correct spelling.",
        prompt_help="The misspelt word, e.g. recieve",
        answer_help="The correct spelling, e.g. receive",
        placeholder="Correct spelling",
        tags=("spelling",),
    ),
    ActivityKind(
        slug="word-to-sentence",
        label="Use it in a sentence",
        mode=MODE_TYPED,
        icon="📝",
        summary="Write your own sentence using the word.",
        instructions="Write one sentence of your own using each word.",
        prompt_help="The word the sentence must use",
        answer_help="Leave blank — any sentence that uses the word is accepted",
        placeholder="Write your sentence",
        tags=("writing",),
    ),
    # ---- multiple choice ------------------------------------------------
    ActivityKind(
        slug="listen-choose",
        label="Listen and choose",
        mode=MODE_CHOICE,
        icon="🎧",
        summary="Hear a word, pick it from a list.",
        instructions="Listen to each clip, then choose the word you heard.",
        prompt_help="Leave blank — the audio is the question",
        answer_help="The word that was said (must match one option)",
        options_help="The words to choose from — one per line",
        needs_audio=True,
        uses_prompt=False,
        tags=("listening",),
    ),
    ActivityKind(
        slug="minimal-pairs",
        label="Minimal pairs",
        mode=MODE_CHOICE,
        icon="👂",
        summary="Tell two near-identical words apart by ear.",
        instructions="These words sound almost the same. Listen, then choose the one you heard.",
        prompt_help="Leave blank — the audio is the question",
        answer_help="The word that was said, e.g. sheep",
        options_help="The pair, one per line, e.g.\nship\nsheep",
        needs_audio=True,
        uses_prompt=False,
        tags=("listening", "phonemics"),
    ),
    ActivityKind(
        slug="odd-one-out",
        label="Odd one out",
        mode=MODE_CHOICE,
        icon="🔍",
        summary="Find the word whose sound doesn't match.",
        instructions="Three words share a sound and one does not. Choose the odd one out.",
        prompt_help="Optional — the sound they share, e.g. the /iː/ sound",
        answer_help="The word that does not belong",
        options_help="All the words, one per line",
        tags=("phonemics",),
    ),
    ActivityKind(
        slug="stress-placement",
        label="Word stress",
        mode=MODE_CHOICE,
        icon="📈",
        summary="Choose the syllable that carries the stress.",
        instructions="Say each word aloud, then choose the syllable you say most strongly.",
        prompt_help="The word, e.g. banana",
        answer_help="The stressed syllable, e.g. na",
        options_help="The syllables, one per line, e.g.\nba\nna\nna",
        tags=("rhythm",),
    ),
    ActivityKind(
        slug="silent-letter",
        label="Silent letters",
        mode=MODE_CHOICE,
        icon="🤫",
        summary="Spot the letter that isn't pronounced.",
        instructions="Each word has a letter you do not say. Choose it.",
        prompt_help="The word, e.g. knee",
        answer_help="The silent letter, e.g. k",
        options_help="The letters to choose from, one per line",
        tags=("phonemics", "spelling"),
    ),
    ActivityKind(
        slug="homophones",
        label="Homophones",
        mode=MODE_CHOICE,
        icon="👯",
        summary="Pick the right spelling for the sentence.",
        instructions="These words sound the same. Choose the spelling that fits each sentence.",
        prompt_help="The sentence with a gap, e.g. They left ___ bags at home.",
        answer_help="The correct word, e.g. their",
        options_help="The spellings to choose from, one per line",
        tags=("spelling", "meaning"),
    ),
    ActivityKind(
        slug="rhyme-match",
        label="Rhyme match",
        mode=MODE_CHOICE,
        icon="🎵",
        summary="Choose the word that rhymes.",
        instructions="Choose the word that rhymes with the one shown.",
        prompt_help="The word to rhyme with, e.g. cat",
        answer_help="The rhyming word, e.g. hat",
        options_help="The words to choose from, one per line",
        tags=("phonemics",),
    ),
    ActivityKind(
        slug="sound-to-symbol",
        label="Sound to symbol",
        mode=MODE_CHOICE,
        icon="🔣",
        summary="Match a word to the phonemic symbol inside it.",
        instructions="Choose the phonemic symbol for the sound you hear in each word.",
        prompt_help="The word, e.g. sheep",
        answer_help="The symbol, e.g. /iː/",
        options_help="The symbols to choose from, one per line",
        tags=("phonemics",),
    ),
    ActivityKind(
        slug="picture-word",
        label="Picture and word",
        mode=MODE_CHOICE,
        icon="🖼️",
        summary="Look at a picture, choose the word.",
        instructions="Look at each picture, then choose the word that names it.",
        prompt_help="Optional caption — upload the picture on the item",
        answer_help="The word the picture shows",
        options_help="The words to choose from, one per line",
        uses_image=True,
        tags=("vocabulary",),
    ),
    # ---- drag and drop --------------------------------------------------
    ActivityKind(
        slug="sound-sort",
        label="Sound sort",
        mode=MODE_SORT,
        icon="🗂️",
        summary="Drag each word into the box for its sound.",
        instructions="Drag each word into the box for the sound it contains.",
        prompt_help="The word to be sorted, e.g. sheep",
        answer_help="The box it belongs in — must match one of the boxes above",
        tags=("phonemics", "drag"),
    ),
    ActivityKind(
        slug="sentence-builder",
        label="Sentence builder",
        mode=MODE_ORDER,
        icon="🧱",
        summary="Drag jumbled words into a sentence.",
        instructions="Drag the words into the right order to build each sentence.",
        prompt_help="Optional hint shown above the words",
        answer_help="The finished sentence — its words are shuffled for the learner",
        tags=("grammar", "drag"),
    ),
    ActivityKind(
        slug="listen-and-number",
        label="Listen and number",
        mode=MODE_ORDER,
        icon="🧮",
        summary="Hear some words, put them in the order they were said.",
        instructions="Listen to the audio, then tap the words in the order you hear them — the first word you tap is number 1.",
        prompt_help="Leave blank — the audio is the question",
        answer_help="The words in the order they are said, one per line, e.g.\nsheep\nship\nshop",
        needs_audio=True,
        uses_prompt=False,
        tags=("listening", "drag"),
    ),
    # ---- recording ------------------------------------------------------
    ActivityKind(
        slug="read-aloud",
        label="Read aloud",
        mode=MODE_RECORD,
        icon="🎙️",
        summary="Read a passage aloud and record it for marking.",
        instructions="Read the passage aloud clearly, record yourself, then send it to your teacher.",
        prompt_help="The passage or sentence to read aloud",
        answer_help="Not used — a teacher marks the recording",
        tags=("speaking",),
    ),
    ActivityKind(
        slug="repeat-after",
        label="Listen and repeat",
        mode=MODE_RECORD,
        icon="🔁",
        summary="Listen to a model, then record yourself saying it.",
        instructions="Listen to each clip, then record yourself saying the same thing.",
        prompt_help="What the learner should say",
        answer_help="Not used — a teacher marks the recording",
        needs_audio=True,
        tags=("speaking", "listening"),
    ),
    ActivityKind(
        slug="tongue-twister",
        label="Tongue twister",
        mode=MODE_RECORD,
        icon="🌀",
        summary="Say a tricky line three times and record it.",
        instructions="Say each tongue twister three times, clearly, then record your best try.",
        prompt_help="The tongue twister",
        answer_help="Not used — a teacher marks the recording",
        tags=("speaking",),
    ),
]

BY_SLUG = {kind.slug: kind for kind in KINDS}

ACTIVITY_KIND_CHOICES = [
    (kind.slug, f"{kind.icon}  {kind.label} — {kind.mode_label}") for kind in KINDS
]


# Every field the admin form can lock. Anything here that a kind does
# not list in activity_fields/item_fields is greyed out for that kind.
LOCKABLE_ACTIVITY_FIELDS = ["buckets"]
LOCKABLE_ITEM_FIELDS = ["prompt", "answer", "options", "hint", "image", "audio_file", "audio_url"]


def get_kind(slug):
    """The spec for a kind slug, or None if it has been retired."""
    return BY_SLUG.get(slug)


def field_visibility():
    """Which fields each kind uses, for the admin form to lock the rest.

    Shape: {kind_slug: {"activity": [...], "item": [...], "label": str}}
    """
    return {
        kind.slug: {
            "activity": kind.activity_fields,
            "item": kind.item_fields,
            "label": kind.label,
        }
        for kind in KINDS
    }
