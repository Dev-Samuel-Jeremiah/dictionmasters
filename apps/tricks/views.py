"""
Tricks to Sound Fluent — a programme of its own, built on 44 Academy's
lessons. Each trick is a lesson with the same eight tabs, stored in the
same tables as the sounds but in groups marked for this programme
(apps/book/programmes.py), so everything a sound's lesson can do, a
trick's can too, and the two never mix.
"""

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.book import views as book
from apps.book.models import TRICKS, Sound, SoundCategory
from apps.book.programmes import programme_for


@login_required
def home(request):
    total = Sound.objects.in_programme(TRICKS).filter(is_published=True).count()
    return render(request, "tricks/home.html", {
        "programme": programme_for(TRICKS),
        "total_tricks": total,
        "groups": SoundCategory.objects.filter(programme=TRICKS).count(),
        "sections": book.TABS,
    })


@login_required
def lessons(request):
    return book.lesson_list(request, TRICKS)


@login_required
def lesson(request, slug, tab="lens"):
    return book.lesson_detail(request, TRICKS, slug, tab)


@login_required
def sections(request, section=None):
    return book.lesson_sections(request, TRICKS, section)
