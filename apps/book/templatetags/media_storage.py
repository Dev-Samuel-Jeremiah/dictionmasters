"""Template filters describing where an uploaded file lives, used by the
admin's file inputs to show what is already stored before anyone
replaces it."""

import os

from django import template
from django.utils.functional import empty
from storages.backends.s3 import S3Storage

register = template.Library()


def _actual_storage(storage):
    """File fields hold Django's lazy default-storage wrapper, whose own
    type says nothing about where files go — look inside it."""
    wrapped = getattr(storage, "_wrapped", None)
    if wrapped is None:
        return storage
    if wrapped is empty:
        storage._setup()
        wrapped = storage._wrapped
    return wrapped

AUDIO = {".mp3", ".m4a", ".wav", ".ogg", ".oga", ".aac", ".webm", ".flac"}
VIDEO = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".ogv"}
IMAGE = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}


@register.filter
def on_r2(field_file):
    """True when the file is kept in Cloudflare R2 rather than on this server."""
    storage = getattr(field_file, "storage", None)
    return isinstance(_actual_storage(storage), S3Storage)


@register.filter
def media_kind(field_file):
    """audio, video, image or file — from the file's extension. Audio is
    checked first, so a .webm voice recording previews as audio."""
    extension = os.path.splitext(str(getattr(field_file, "name", "") or ""))[1].lower()
    if extension in AUDIO:
        return "audio"
    if extension in VIDEO:
        return "video"
    if extension in IMAGE:
        return "image"
    return "file"


@register.filter
def file_basename(field_file):
    return os.path.basename(str(getattr(field_file, "name", "") or ""))
