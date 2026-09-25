"""
Shared admin bits for anything with a video: a thumbnail preview in the
list, and an action to take the thumbnail again (after trimming a video,
or when the first frame turned out to be a dark one).
"""

from django.contrib import admin, messages
from django.utils.html import format_html

from . import video_poster


class VideoPosterAdminMixin:
    actions = ["regenerate_posters"]

    @admin.display(description="Thumbnail")
    def poster_preview(self, obj):
        if obj.video_poster:
            return format_html(
                '<img src="{}" alt="" style="height:44px;border-radius:6px;'
                'box-shadow:0 2px 6px rgba(0,0,0,.25);object-fit:cover;">',
                obj.video_poster.url,
            )
        if obj.video_file or obj.video_url:
            return format_html('<span style="color:#7A5600;">none yet</span>')
        return "—"

    @admin.action(description="Take the video thumbnail again")
    def regenerate_posters(self, request, queryset):
        if not video_poster.thumbnails_available():
            self.message_user(request, "ffmpeg isn't installed on this server, so thumbnails can't be made.", messages.ERROR)
            return
        made = sum(1 for obj in queryset if video_poster.make_poster(obj, replace=True))
        missed = queryset.count() - made
        self.message_user(request, f"New thumbnail for {made} video{'s' if made != 1 else ''}.", messages.SUCCESS)
        if missed:
            self.message_user(request, f"{missed} had no video, or no frame could be read.", messages.WARNING)
