"""The list a learner's app syncs against (catalog.py)."""

from django.contrib.contenttypes.models import ContentType
from django.http import JsonResponse

from apps.accounts.access import can_see_level
from apps.billing.access import has_access
from apps.videos import links

from .catalog import access_info, learner_secret, manifest, may_keep_video
from .models import LessonPack


def learner_info(request):
    """The signed-in person, as their app keeps them (templates/pwa/sw.js,
    "learners"): their number and key, their name for the offline sign-in
    screen, and who on this device may sign in there by tapping their name.
    That's the accounts remembered on the device's switcher
    (apps/accounts/switcher.py), but not one whose password has changed
    since. Admins too: offline that opens only the lessons kept on the
    device (the control room and admin pages are never kept), and back
    online the site asks for their password as it always does. The app
    forgets everyone else's key when they sign out, so their lessons stay
    locked until they sign in online again."""
    from apps.accounts import switcher

    user = request.user
    device = [row.user_id for row in switcher.device_accounts(request) if not row.password_changed]
    return {
        "id": user.pk,
        "secret": learner_secret(user),
        "name": user.get_full_name() or user.login_name,
        "initials": f"{user.first_name[:1]}{user.last_name[:1]}".upper() or user.login_name[:1].upper(),
        "device": device,
    }


def offline_manifest(request):
    if not request.user.is_authenticated:
        return JsonResponse({"signed_in": False}, status=401)
    # Levels chosen on this device's Offline page (someone who can open
    # every level): templates/pwa/sw.js sends them.
    chosen = [level for level in request.GET.get("levels", "").split(",") if level]
    found = manifest(request.user, chosen)
    found["learner"] = learner_info(request)
    response = JsonResponse(found)
    response["Cache-Control"] = "private, no-store"
    return response


def learner(request):
    """Who is signed in on this device, for the app's per-learner stores: their
    number, their key, and a fresh security token to send waiting progress
    with (signing in renews the token, so older progress would be refused).
    With their access (catalog.access_info), for a page saved on its own
    ("Save this page for offline"), which keeps the same rules as a download."""
    from django.middleware.csrf import get_token

    if not request.user.is_authenticated:
        return JsonResponse({"ok": False}, status=401)
    response = JsonResponse({"ok": True, **learner_info(request), **access_info(request.user),
                             "token": get_token(request)})
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
    if not can_see_level(request.user, pack.level):
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
