"""The list a learner's app syncs against (catalog.py)."""

from django.contrib.contenttypes.models import ContentType
from django.http import JsonResponse

from apps.billing.access import has_access
from apps.videos import links

from .catalog import levels_for, manifest, may_keep_video
from .models import LessonPack


def offline_manifest(request):
    if not request.user.is_authenticated:
        return JsonResponse({"signed_in": False}, status=401)
    response = JsonResponse(manifest(request.user))
    response["Cache-Control"] = "private, no-store"
    return response


def pack_key(request, pk):
    """The key that opens a lesson pack, for a learner loading it from a flash
    drive: only for that pack's level, and only with a plan running."""
    if not request.user.is_authenticated:
        return JsonResponse({"ok": False, "error": "Sign in first, then load the pack."}, status=401)
    pack = LessonPack.objects.filter(pk=pk, status=LessonPack.Status.READY).first()
    if pack is None:
        return JsonResponse({"ok": False, "error": "That pack has been replaced. Ask for the newest one."}, status=404)
    if not has_access(request.user):
        return JsonResponse({"ok": False, "error": "Your plan has ended, so this pack can't be loaded."}, status=403)
    if not (request.user.is_staff or pack.level in levels_for(request.user)):
        return JsonResponse({"ok": False, "error": f"This pack is for {pack.level}. Ask for your own level's pack."}, status=403)
    response = JsonResponse({"ok": True, "level": pack.level, "key": pack.key})
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
