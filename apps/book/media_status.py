"""A small changelist column showing where an object's audio and video
live, for any admin whose model uses the AudioContent / VideoContent
mixins."""

from django.utils.html import format_html, format_html_join

from .templatetags.media_storage import on_r2


def _pill(kind, label, css):
    return (css, f"{kind} {label}")


def media_pills(obj):
    pills = []
    for kind, file_attr, url_attr in (("Audio", "audio_file", "audio_url"), ("Video", "video_file", "video_url")):
        stored = getattr(obj, file_attr, None)
        link = getattr(obj, url_attr, "")
        if stored:
            pills.append(_pill(kind, "on R2" if on_r2(stored) else "on server",
                               "media-pill--r2" if on_r2(stored) else "media-pill--local"))
        elif link:
            pills.append(_pill(kind, "link", "media-pill--link"))

    if not pills:
        return format_html('<span class="media-pill media-pill--none">No media</span>')
    return format_html_join("", '<span class="media-pill {}">{}</span>', pills)
