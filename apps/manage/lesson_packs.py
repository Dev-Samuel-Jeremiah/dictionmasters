"""
The control room's Lesson packs page: build each level's pack (its pictures,
recordings and videos in one encrypted file, apps/offline/packs.py) and
download it, to copy to a flash drive for schools with weak internet.

A build runs as its own process (manage.py build_lesson_pack), so a level of
several gigabytes doesn't hold up the page, and survives the web server
restarting. The page shows how far it has got.
"""

import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.echospell.models import LEVEL_NAME_CHOICES
from apps.offline.models import LessonPack
from apps.offline.packs import new_key
from apps.schools.grades import label_for_level

from .views import _base_context, staff_only

LEVELS = [value for value, _label in LEVEL_NAME_CHOICES]
WORKING = (LessonPack.Status.QUEUED, LessonPack.Status.BUILDING)


def start_build(pack):
    """Run the build in its own process, which carries on after this request."""
    subprocess.Popen(
        [sys.executable, str(Path(settings.BASE_DIR) / "manage.py"), "build_lesson_pack", str(pack.pk)],
        cwd=settings.BASE_DIR, start_new_session=True,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


@staff_only
def lesson_packs(request):
    latest = {}
    for pack in LessonPack.objects.order_by("-created_at"):
        latest.setdefault(pack.level, {}).setdefault(pack.status in WORKING and "working" or pack.status, pack)
    rows = []
    for level in LEVELS:
        found = latest.get(level, {})
        rows.append({"level": level, "label": label_for_level(level), "ready": found.get(LessonPack.Status.READY),
                     "working": found.get("working"), "failed": found.get(LessonPack.Status.FAILED)})
    return render(request, "manage/lesson_packs.html", _base_context(
        request, "lesson-packs", rows=rows, busy=any(row["working"] for row in rows),
    ))


@staff_only
@require_POST
def build_pack(request):
    level = request.POST.get("level", "")
    if level not in LEVELS:
        messages.error(request, "Choose a level.")
    elif LessonPack.objects.filter(level=level, status__in=WORKING).exists():
        messages.info(request, f"{level}'s pack is already being built.")
    else:
        pack = LessonPack.objects.create(level=level, key=new_key(), created_by=request.user)
        start_build(pack)
        messages.success(request, f"Building {level}'s pack. This page shows how far it has got.")
    return redirect("manage:lesson_packs")
