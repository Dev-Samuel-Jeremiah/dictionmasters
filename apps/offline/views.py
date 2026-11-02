"""The list a learner's app syncs against (catalog.py)."""

from django.http import JsonResponse

from .catalog import manifest


def offline_manifest(request):
    if not request.user.is_authenticated:
        return JsonResponse({"signed_in": False}, status=401)
    response = JsonResponse(manifest(request.user))
    response["Cache-Control"] = "private, no-store"
    return response
