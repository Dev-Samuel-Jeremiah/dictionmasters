"""
How a match is played — every rule that touches the score.

The server owns the clock. A round records when it was shown; when an
answer arrives the server works out how long it took. The countdown on
the page is only a picture of that, and an answer that arrives after the
clock (plus a couple of seconds' grace for the network) counts as out of
time, however the page was manipulated.
"""

import random
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.echospell.marking import answers_match

from . import catalogue as C
from .generator import build_round, library_ready
from .models import Match, Round

GRACE = timedelta(seconds=2)


class ClashUnavailable(Exception):
    """The game can't be played — the message says why, for the player."""


def start_match(user, mode_slug, tier_slug):
    mode, tier = C.MODES.get(mode_slug), C.TIERS.get(tier_slug)
    if mode is None or tier is None:
        raise ClashUnavailable("Choose a game mode and a difficulty.")
    if not library_ready(tier, user):
        raise ClashUnavailable("There aren't enough words in the library to play yet.")

    now = timezone.now()
    return Match.objects.create(
        user=user,
        mode=mode.slug,
        difficulty=tier.slug,
        seed=random.getrandbits(62),
        lives=mode.lives,
        ends_at=now + timedelta(seconds=mode.total_seconds) if mode.total_seconds else None,
    )


def seconds_per_round(match):
    """The clock for one question. Survival takes a second off for every
    few answers you get right, down to a floor."""
    seconds = match.tier.seconds
    if match.mode == C.SURVIVAL.slug:
        seconds = max(C.SURVIVAL_MIN_SECONDS, seconds - match.correct // C.SURVIVAL_SPEEDUP_EVERY)
    return seconds


def current_round(match):
    return match.rounds.order_by("-number").first()


def next_round(match):
    used = set(match.rounds.values_list("word_id", flat=True))
    fields = build_round(match, match.rounds.count() + 1, used)
    if fields is None:
        raise ClashUnavailable("Couldn't build a question from the library.")
    return Round.objects.create(
        match=match,
        number=match.rounds.count() + 1,
        seconds=0 if match.mode_spec.total_seconds else seconds_per_round(match),
        **fields,
    )


def time_left(match, round_=None):
    """Whole seconds left on whichever clock applies — the game's in a
    blitz, the question's otherwise."""
    now = timezone.now()
    if match.ends_at:
        return max(0, int((match.ends_at - now).total_seconds()))
    if round_ and round_.seconds:
        return max(0, int((round_.shown_at + timedelta(seconds=round_.seconds) - now).total_seconds()))
    return None


def _question_expired(round_, at):
    return bool(round_.seconds) and at > round_.shown_at + timedelta(seconds=round_.seconds) + GRACE


def game_over(match):
    mode = match.mode_spec
    if mode.total_seconds:
        return timezone.now() >= match.ends_at
    if mode.lives:
        return match.lives == 0
    return match.answered >= mode.rounds


def _score(match, round_, correct, at):
    tier, mode = match.tier, match.mode_spec
    if not correct:
        match.streak = 0
        match.wrong += 1
        if mode.lives:
            match.lives = max(0, match.lives - 1)
        if mode.wrong_penalty:
            penalty = round(C.BLITZ_PENALTY * tier.multiplier)
            round_.points = -min(penalty, match.score)   # never below zero
        return

    match.correct += 1
    match.streak += 1
    match.best_streak = max(match.best_streak, match.streak)
    base = C.BASE_POINTS * tier.multiplier
    bonus = 0
    if round_.seconds:
        remaining = max(0.0, round_.seconds - (at - round_.shown_at).total_seconds())
        bonus = base * C.SPEED_BONUS_SHARE * remaining / round_.seconds
    round_.points = round((base + bonus) * C.streak_multiplier(match.streak))


@transaction.atomic
def answer(match, round_number, given):
    """Mark an answer to the round on screen. Answering a round that's
    already been answered, or isn't the current one, changes nothing —
    so a double-click or a resent form can't score twice."""
    round_ = match.rounds.select_for_update().filter(number=round_number).first()
    if round_ is None or not round_.is_pending or round_ != current_round(match):
        return None

    at = timezone.now()
    if match.ends_at and at > match.ends_at + GRACE:
        return None                                   # blitz already over

    given = str(given or "").strip()[:255]
    round_.given = given
    round_.answered_at = at
    if _question_expired(round_, at):
        round_.timed_out = True
        correct = False
    elif round_.is_typed:
        correct = answers_match(given, round_.answer)
    else:
        correct = given == round_.answer and given in round_.options

    round_.is_correct = correct
    _score(match, round_, correct, at)
    match.score += round_.points
    round_.save()
    match.save()
    return round_


@transaction.atomic
def expire_if_due(match, round_):
    """Record a question left unanswered past its clock as a miss."""
    if round_ is None or not round_.is_pending or not _question_expired(round_, timezone.now()):
        return False
    round_.timed_out = True
    round_.is_correct = False
    round_.answered_at = round_.shown_at + timedelta(seconds=round_.seconds)
    _score(match, round_, False, round_.answered_at)
    match.score += round_.points
    round_.save()
    match.save()
    return True


@transaction.atomic
def finish(match):
    if not match.is_active:
        return match
    # A blitz ends mid-question; the question nobody saw through isn't a miss.
    match.rounds.filter(is_correct__isnull=True).delete()
    match.status = Match.Status.FINISHED
    match.finished_at = timezone.now()
    match.save()
    return match


def personal_best(user, mode, difficulty, exclude=None):
    finished = Match.objects.filter(user=user, mode=mode, difficulty=difficulty, status=Match.Status.FINISHED)
    if exclude is not None:
        finished = finished.exclude(pk=exclude.pk)
    return finished.order_by("-score").values_list("score", flat=True).first()
