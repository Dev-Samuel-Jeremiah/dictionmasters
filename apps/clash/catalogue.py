"""
The rules of Diction Clash, in one place: modes, difficulty tiers and
question types. Changing how the game plays — a tier's time limit, which
question types it uses, what a streak is worth — means editing this file,
not the engine.
"""

from dataclasses import dataclass

from apps.echospell.models import LEVEL_NAME_CHOICES

LEVELS = [value for value, _ in LEVEL_NAME_CHOICES]  # Pre-Level, Level 1 … Level 12

# ---------------------------------------------------------------------------
# Question types
# ---------------------------------------------------------------------------

MEANING_TO_WORD = "meaning_to_word"
WORD_TO_MEANING = "word_to_meaning"
FILL_GAP = "fill_gap"
IPA_TO_WORD = "ipa_to_word"
WORD_TO_IPA = "word_to_ipa"
MISSPELLING = "misspelling"
UNSCRAMBLE = "unscramble"
HEAR_CHOOSE = "hear_choose"
HEAR_SPELL = "hear_spell"

TYPE_LABELS = {
    MEANING_TO_WORD: "Which word means this?",
    WORD_TO_MEANING: "What does this word mean?",
    FILL_GAP: "Fill the gap",
    IPA_TO_WORD: "Read the transcription",
    WORD_TO_IPA: "Choose the transcription",
    MISSPELLING: "Spot the correct spelling",
    UNSCRAMBLE: "Unscramble the word",
    HEAR_CHOOSE: "Listen and choose",
    HEAR_SPELL: "Listen and spell",
}

# Answered by typing rather than by choosing. There is deliberately no
# typed-transcription question: the game runs without JavaScript, so there
# is no tap-to-type phonemic keyboard, and IPA can't fairly be typed
# against the clock without one.
TYPED_TYPES = {UNSCRAMBLE, HEAR_SPELL}
AUDIO_TYPES = {HEAR_CHOOSE, HEAR_SPELL}

# ---------------------------------------------------------------------------
# Difficulty
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Tier:
    slug: str
    label: str
    blurb: str
    levels: tuple
    seconds: int
    multiplier: float
    types: tuple
    # How alike the wrong answers are: "far" picks any other word,
    # "near" picks words of similar length and spelling.
    distractors: str


BEGINNER = Tier(
    slug="beginner",
    label="Beginner",
    blurb="Everyday words, clear choices and plenty of time.",
    levels=tuple(LEVELS[0:4]),        # Pre-Level – Level 3
    seconds=20,
    multiplier=1.0,
    types=(MEANING_TO_WORD, WORD_TO_MEANING, FILL_GAP, UNSCRAMBLE, HEAR_CHOOSE),
    distractors="far",
)
INTERMEDIATE = Tier(
    slug="intermediate",
    label="Intermediate",
    blurb="Harder words, transcriptions and spelling traps.",
    levels=tuple(LEVELS[4:9]),        # Level 4 – Level 8
    seconds=15,
    multiplier=1.5,
    types=(MEANING_TO_WORD, FILL_GAP, IPA_TO_WORD, WORD_TO_IPA, MISSPELLING, HEAR_CHOOSE, HEAR_SPELL),
    distractors="near",
)
EXPERT = Tier(
    slug="expert",
    label="Very difficult",
    blurb="Near-identical sounds, spelling traps, and only seconds to think.",
    levels=tuple(LEVELS[9:]),         # Level 9 – Level 12
    seconds=10,
    multiplier=2.0,
    types=(WORD_TO_IPA, IPA_TO_WORD, MISSPELLING, HEAR_SPELL, FILL_GAP),
    distractors="near",
)

TIERS = {tier.slug: tier for tier in (BEGINNER, INTERMEDIATE, EXPERT)}

# A tier with fewer words than this borrows from the whole library, so a
# thin level never produces a game of the same three words.
MIN_POOL = 12

# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Mode:
    slug: str
    label: str
    icon: str
    blurb: str
    rules: tuple
    rounds: int = 0          # fixed number of questions; 0 = open-ended
    total_seconds: int = 0   # a clock for the whole game; 0 = per-question clock
    lives: int = 0
    wrong_penalty: bool = False
    shows_feedback: bool = True


CLASSIC = Mode(
    slug="classic",
    label="Classic Clash",
    icon="⚔️",
    blurb="Ten questions, a clock on each. Answer fast for bonus points.",
    rules=("10 questions", "A timer on every question", "Speed and streak bonuses"),
    rounds=10,
)
BLITZ = Mode(
    slug="blitz",
    label="60-Second Blitz",
    icon="⚡",
    blurb="As many as you can in one minute. Wrong answers cost you.",
    rules=("60 seconds on the clock", "Unlimited questions", "Wrong answers lose points"),
    total_seconds=60,
    wrong_penalty=True,
    shows_feedback=False,
)
SURVIVAL = Mode(
    slug="survival",
    label="Survival",
    icon="❤️",
    blurb="Three lives. The clock gets shorter the longer you last.",
    rules=("3 lives", "Timer shrinks as you go", "How far can you get?"),
    lives=3,
)

MODES = {mode.slug: mode for mode in (CLASSIC, BLITZ, SURVIVAL)}

# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

BASE_POINTS = 100
SPEED_BONUS_SHARE = 0.5      # up to +50% for answering instantly
BLITZ_PENALTY = 50           # before the tier multiplier
STREAK_BONUSES = ((5, 1.5), (3, 1.2))   # (streak reached, multiplier)

# Survival: every this many correct answers, a second comes off the clock.
SURVIVAL_SPEEDUP_EVERY = 5
SURVIVAL_MIN_SECONDS = 5


def streak_multiplier(streak):
    for reached, multiplier in STREAK_BONUSES:
        if streak >= reached:
            return multiplier
    return 1.0
