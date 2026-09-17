"""
Views for Diction Clash — plain Django pages, no JavaScript.

Answers are ordinary form posts; each option is its own submit button.
When a clock runs out the page reloads itself (a meta refresh timed by the
server), and the server records the miss. The countdown the player sees is
drawn with CSS from the seconds the server says are left.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Max
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from . import catalogue as C
from . import engine as E
from .generator import has_audio, word_pool
from .models import Match

LETTERS = "ABCD"


def _muted(request):
    return request.session.get("clash_muted", False)


@login_required
def hub(request):
    bests = {
        (row["mode"], row["difficulty"]): row["best"]
        for row in Match.objects.filter(user=request.user, status=Match.Status.FINISHED)
        .values("mode", "difficulty").annotate(best=Max("score"))
    }
    tiers = []
    for tier in C.TIERS.values():
        pool = word_pool(tier, request.user)
        tiers.append({
            "tier": tier,
            "words": len(pool),
            "with_audio": sum(1 for w in pool if has_audio(w)),
            # The tier is thin, so it's topped up from the whole library.
            "borrowed": any(w.level not in tier.levels for w in pool),
        })
    return render(request, "clash/hub.html", {
        "modes": list(C.MODES.values()),
        "tiers": tiers,
        "best_rows": [
            {"mode": mode, "scores": [bests.get((mode.slug, tier.slug)) for tier in C.TIERS.values()]}
            for mode in C.MODES.values()
        ],
        "tier_list": list(C.TIERS.values()),
        "active": Match.objects.filter(user=request.user, status=Match.Status.ACTIVE).first(),
        "recent": Match.objects.filter(user=request.user, status=Match.Status.FINISHED)[:6],
        "muted": _muted(request),
    })


@login_required
@require_POST
def start(request):
    # One game at a time: starting afresh closes anything left open.
    for leftover in Match.objects.filter(user=request.user, status=Match.Status.ACTIVE):
        E.finish(leftover)
    try:
        match = E.start_match(request.user, request.POST.get("mode"), request.POST.get("difficulty"))
    except E.ClashUnavailable as reason:
        messages.error(request, str(reason))
        return redirect("clash:hub")
    return redirect("clash:play", match_id=match.pk)


@login_required
@require_POST
def toggle_sound(request):
    request.session["clash_muted"] = not _muted(request)
    target = request.POST.get("next", "")
    return redirect(target if target.startswith("/") else "clash:hub")


def _hud(match, round_=None):
    """The score bar across the top of every in-game page."""
    mode = match.mode_spec
    return {
        "mode": mode,
        "tier": match.tier,
        "score": match.score,
        "streak": match.streak,
        "streak_bonus": C.streak_multiplier(match.streak),
        "lives": range(match.lives),
        "lives_lost": range(max(mode.lives - match.lives, 0)),
        "progress": f"Question {match.answered + (1 if round_ and round_.is_pending else 0)} of {mode.rounds}" if mode.rounds else "",
    }


@login_required
def play(request, match_id):
    match = get_object_or_404(Match, pk=match_id, user=request.user)
    if not match.is_active:
        return redirect("clash:result", match_id=match.pk)
    mode = match.mode_spec

    if request.method == "POST":
        try:
            number = int(request.POST.get("round", "0"))
        except ValueError:
            number = 0
        E.answer(match, number, request.POST.get("answer", ""))
        match.refresh_from_db()
        if not mode.shows_feedback and E.game_over(match):
            E.finish(match)
            return redirect("clash:result", match_id=match.pk)
        return redirect("clash:play", match_id=match.pk)

    if mode.total_seconds and E.game_over(match):
        E.finish(match)
        return redirect("clash:result", match_id=match.pk)

    round_ = E.current_round(match)
    if round_ and round_.is_pending and E.expire_if_due(match, round_):
        round_.refresh_from_db()
        match.refresh_from_db()

    if round_ is not None and not round_.is_pending:
        if mode.shows_feedback and "next" not in request.GET:
            return render(request, "clash/feedback.html", {
                "match": match,
                "round": round_,
                "word": round_.word,
                "game_over": E.game_over(match),
                "hud": _hud(match),
                "muted": _muted(request),
            })
        if E.game_over(match):
            E.finish(match)
            return redirect("clash:result", match_id=match.pk)

    if round_ is None or not round_.is_pending:
        try:
            E.next_round(match)
        except E.ClashUnavailable as reason:
            E.finish(match)
            messages.error(request, str(reason))
            return redirect("clash:hub")
        return redirect("clash:play", match_id=match.pk)

    left = E.time_left(match, round_)
    limit = mode.total_seconds or round_.seconds
    previous = match.rounds.filter(number=round_.number - 1).first() if not mode.shows_feedback else None
    return render(request, "clash/play.html", {
        "match": match,
        "round": round_,
        "options": list(zip(LETTERS, round_.options)),
        "audio": round_.word.audio_source if round_.word and round_.kind in C.AUDIO_TYPES else "",
        "seconds_left": left,
        "limit": limit,
        "start_pct": round(left * 100 / limit) if limit else 0,
        "warn_after": max(left - 5, 0),
        "previous": previous,
        "hud": _hud(match, round_),
        "muted": _muted(request),
    })


@login_required
def result(request, match_id):
    match = get_object_or_404(Match, pk=match_id, user=request.user)
    if match.is_active:
        return redirect("clash:play", match_id=match.pk)
    best_before = E.personal_best(request.user, match.mode, match.difficulty, exclude=match)
    return render(request, "clash/result.html", {
        "match": match,
        "rounds": match.rounds.select_related("word"),
        "best_before": best_before,
        "new_best": match.score > 0 and (best_before is None or match.score > best_before),
        "muted": _muted(request),
    })
