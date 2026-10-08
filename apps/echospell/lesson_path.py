"""
An EchoSpell group as a guided lesson: one step per screen, a Next
button, and completion that is earned rather than ticked.

The steps, in the order the group page lists them:

  1. each card type that has something in it for this group (its words,
     its passage or its dialogue) — done once opened;
  2. each activity that has questions — done once passed; a recorded
     activity (read aloud and the like) counts once it has been sent,
     since a teacher marks it later and the child isn't kept waiting.

When every step is done the group is complete: GroupProgress is written
here, and nowhere else. It is the same rule as the 44 Academy's lessons
(apps/tricks/progress.py). A group with nothing in it yet counts as done
once opened, so an empty group never stops a learner moving on.
"""

from django.db.models import Count
from django.urls import reverse

from .activity_kinds import MODE_RECORD
from .models import Activity, ActivityAttempt, CardLesson, Dialogue, GroupProgress, GroupStepsSeen, Passage


def _cards_with_content(level, group):
    """The level's card types that have something in them for this group."""
    words = set(CardLesson.objects.filter(group=group, is_published=True).values_list("category_id", flat=True))
    has_passage = Passage.objects.filter(group=group).exists()
    has_dialogue = Dialogue.objects.filter(group=group).exists()
    return [
        c for c in level.categories.all()
        if (has_passage if c.kind == "passage" else has_dialogue if c.kind == "dialogue" else c.pk in words)
    ]


def _activity_done(activity, tried):
    marked = [a for a in tried if a.status != a.STATUS_AWAITING]
    sent = any(a.status == a.STATUS_AWAITING for a in tried)
    return any(a.passed for a in marked) or (activity.mode == MODE_RECORD and sent)


def lesson_path(user, level, group):
    """The group's steps and where this learner stands on each."""
    seen_row = GroupStepsSeen.objects.filter(user=user, group=group).first()
    seen = set(seen_row.cards_seen) if seen_row else set()

    steps = []
    for category in _cards_with_content(level, group):
        steps.append({
            "kind": "card", "key": f"card-{category.pk}", "title": category.name, "icon": category.icon,
            "url": reverse("echospell:card_detail", args=[level.slug, group.slug, category.slug]),
            "done": category.pk in seen,
        })

    activities = list(
        Activity.objects.filter(group=group, is_published=True)
        .annotate(item_count=Count("items")).filter(item_count__gt=0).order_by("order", "id")
    )
    attempts = {}
    for attempt in ActivityAttempt.objects.filter(user=user, activity__in=activities):
        attempts.setdefault(attempt.activity_id, []).append(attempt)
    for activity in activities:
        steps.append({
            "kind": "activity", "key": f"activity-{activity.pk}", "title": activity.title, "icon": activity.icon,
            "url": reverse("echospell:activity_detail", args=[level.slug, group.slug, activity.slug]),
            "done": _activity_done(activity, attempts.get(activity.pk, [])),
        })

    for number, step in enumerate(steps, start=1):
        step["number"] = number
    done = sum(1 for s in steps if s["done"])
    return {
        "steps": steps,
        "done": done,
        "total": len(steps),
        "percent": round(done * 100 / len(steps)) if steps else 100,
        "complete": done == len(steps),
        "next": next((s for s in steps if not s["done"]), None),
        "start_url": reverse("echospell:group_detail", args=[level.slug, group.slug]),
        "finish_url": reverse("echospell:group_detail", args=[level.slug, group.slug]) + "#finish",
    }


def at_step(path, key):
    """The lesson bar for one step: where it sits, and where Back and
    Next go. Next is the next unfinished step after this one (then any
    unfinished one before it), or the finish screen."""
    steps = path["steps"]
    index = next((i for i, s in enumerate(steps) if s["key"] == key), None)
    if index is None:
        return None
    later = [s for s in steps[index + 1:] if not s["done"]]
    earlier = [s for s in steps[:index] if not s["done"]]
    following = (later or earlier or [None])[0]
    return {
        **path,
        "current": steps[index],
        "back": steps[index - 1] if index else None,
        "following": following,
    }


def record_card(user, group, category):
    """Note that this card type has been opened."""
    row, _ = GroupStepsSeen.objects.get_or_create(user=user, group=group)
    if category.pk not in row.cards_seen:
        row.cards_seen = [*row.cards_seen, category.pk]
        row.save(update_fields=["cards_seen", "updated_at"])


def award(user, path, group):
    """Write GroupProgress once every step is done. Returns True the first
    time, so the page can say so."""
    if not path["complete"]:
        return False
    _row, created = GroupProgress.objects.get_or_create(user=user, group=group)
    return created
