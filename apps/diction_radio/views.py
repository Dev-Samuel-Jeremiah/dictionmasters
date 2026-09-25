from django.contrib.auth.decorators import login_required
from django.db.models import Count, Prefetch, Q
from django.shortcuts import render

from apps.manage.rich_text import sanitize_rich_text

from .models import RadioEpisode, RadioProgram


@login_required
def home(request):
    programs = list(
        RadioProgram.objects.filter(is_published=True)
        .annotate(published_episode_count=Count("episodes", filter=Q(episodes__is_published=True)))
        .filter(published_episode_count__gt=0)
        .prefetch_related(Prefetch("episodes", queryset=RadioEpisode.objects.filter(is_published=True).order_by("order", "id")))
        .order_by("order", "title")
    )
    queue = [
        {
            "id": episode.pk,
            "title": episode.title,
            "description": sanitize_rich_text(episode.description),
            "transcript": sanitize_rich_text(episode.transcript),
            "program": program.title,
            "programId": program.pk,
            "programSlug": program.slug,
            "cover": program.cover_image.url if program.cover_image else "",
            "src": episode.audio_source,
        }
        for program in programs
        for episode in program.episodes.all()
    ]
    queue_indexes = {item["id"]: index for index, item in enumerate(queue)}
    for program in programs:
        for episode in program.episodes.all():
            episode.queue_index = queue_indexes[episode.pk]
    return render(request, "diction_radio/home.html", {"programs": programs, "queue": queue})

