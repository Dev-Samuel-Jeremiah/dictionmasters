"""
A Learning Modules day as a guided lesson: its lesson items one per
screen, a Next button, and a day that completes itself.

Each published lesson item is a step, done once it has been opened —
the same rule as the 44 Academy's tabs and EchoSpell's cards. When every
item has been opened, DayProgress is written here, and nowhere else. A
day with no items yet counts as done once opened, so an empty day never
stops a learner moving on. Every week and term is open.
"""

from django.urls import reverse

from .models import DayItemsSeen, DayProgress


def day_url(day):
    week, term = day.week, day.week.term
    return reverse("learning_modules:day_detail", args=[term.module.slug, term.slug, week.slug, day.day_name])


def lesson_path(user, day, items):
    """The day's steps (its published `items`, in order) and where this
    learner stands on each."""
    base = day_url(day)
    row = DayItemsSeen.objects.filter(user=user, day=day).first()
    seen = set(row.items_seen) if row else set()
    steps = [
        {"kind": "item", "key": f"item-{item.pk}", "item_id": item.pk, "title": item.title,
         "url": f"{base}?step={number}", "done": item.pk in seen, "number": number}
        for number, item in enumerate(items, start=1)
    ]
    done = sum(1 for s in steps if s["done"])
    return {
        "steps": steps,
        "done": done,
        "total": len(steps),
        "percent": round(done * 100 / len(steps)) if steps else 100,
        "complete": done == len(steps),
        "next": next((s for s in steps if not s["done"]), None),
        "start_url": f"{base}?step=finish",
        "finish_url": f"{base}?step=finish",
    }


def at_step(path, number):
    """The lesson bar for step `number` (1-based), as EchoSpell's."""
    steps = path["steps"]
    if not 1 <= number <= len(steps):
        return None
    index = number - 1
    later = [s for s in steps[index + 1:] if not s["done"]]
    earlier = [s for s in steps[:index] if not s["done"]]
    return {
        **path,
        "current": steps[index],
        "back": steps[index - 1] if index else None,
        "following": (later or earlier or [None])[0],
    }


def record_item(user, day, item):
    """Note that this lesson item has been opened."""
    row, _ = DayItemsSeen.objects.get_or_create(user=user, day=day)
    if item.pk not in row.items_seen:
        row.items_seen = [*row.items_seen, item.pk]
        row.save(update_fields=["items_seen", "updated_at"])


def award(user, path, day):
    """Write DayProgress once every item has been opened. True the first time."""
    if not path["complete"]:
        return False
    _row, created = DayProgress.objects.get_or_create(user=user, day=day)
    return created
