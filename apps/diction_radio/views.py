from django.contrib.auth.decorators import login_required
from django.db.models import Count, Prefetch, Q
from django.shortcuts import render

from apps.book import read_along
from apps.manage.rich_text import sanitize_rich_text

from .models import RadioEpisode, RadioProgram


def _offer_offline(episode, user):
    """An episode of ours can be saved for listening offline, like any
    recording (apps/videos): a ticket for its "Save" button, and the name its
    copy is kept under (static/js/diction_radio.js). A hosted link can't."""
    from django.contrib.contenttypes.models import ContentType

    from apps.videos import links

    episode.offline_ticket = ""
    if user.is_authenticated and episode.audio_file and not episode.audio_url:
        episode.offline_ticket = links.ticket(episode, user, media=links.AUDIO)
        episode.offline_ref = f"{ContentType.objects.get_for_model(episode).pk}-{episode.pk}-a"


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
            # The transcript highlights along with the episode (static/js/read_along.js).
            "sync": read_along.sync_url(episode) if episode.transcript and episode.audio_source else "",
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
            _offer_offline(episode, request.user)
    return render(request, "diction_radio/home.html", {"programs": programs, "queue": queue})

