"""The list a learner's app syncs against (catalog.py)."""

from django.contrib.contenttypes.models import ContentType
from django.http import JsonResponse

from apps.billing.access import has_access
from apps.videos import links

from .catalog import manifest, may_keep_video


def offline_manifest(request):
    if not request.user.is_authenticated:
        return JsonResponse({"signed_in": False}, status=401)
    response = JsonResponse(manifest(request.user))
    response["Cache-Control"] = "private, no-store"
    return response


def video_ticket(request, ref):
    """A fresh ticket for the next video an app saves by itself. Tickets last
    minutes and the list takes hours, so each is asked for as its turn comes."""
    if not request.user.is_authenticated:
        return JsonResponse({"ok": False}, status=401)
    if not (has_access(request.user) and may_keep_video(request.user, ref)):
        return JsonResponse({"ok": False}, status=404)
    content_type_id, _sep, pk = ref.partition("-")
    video = ContentType.objects.get_for_id(int(content_type_id)).get_object_for_this_type(pk=int(pk))
    title = getattr(video, "video_caption", "") or getattr(video, "title", "") or "Lesson video"
    response = JsonResponse({"ok": True, "id": ref, "ticket": links.ticket(video, request.user), "title": str(title)[:200]})
    response["Cache-Control"] = "private, no-store"
    return response
