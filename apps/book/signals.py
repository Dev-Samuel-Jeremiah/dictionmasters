"""
Keep video thumbnails, and read-along timings, in step with the media.

Every model with a video gets the same treatment: save a video and its
poster is made in the background; change the video and the old poster is
thrown away and a new one made. A poster an admin uploaded by hand is
left alone — only posters we made are replaced.
"""

from django.db.models.signals import post_init, post_save

from . import read_along, video_poster

STASH = "_dm_video_source"


def _source(instance):
    file_name = instance.video_file.name if instance.video_file else ""
    return f"{file_name}|{instance.video_url}"


def remember_video(sender, instance, **kwargs):
    try:
        instance.__dict__[STASH] = _source(instance)
    except Exception:      # a deferred queryset has no video fields loaded
        pass


def refresh_poster(sender, instance, **kwargs):
    if not video_poster.thumbnails_available():
        return
    try:
        now = _source(instance)
    except Exception:
        return
    before = instance.__dict__.get(STASH)
    instance.__dict__[STASH] = now

    changed = before is not None and before != now
    if changed and instance.video_poster:
        # The poster belongs to the old video: drop it and take a new one.
        old = instance.video_poster.name
        sender.objects.filter(pk=instance.pk).update(video_poster="")
        instance.video_poster = ""
        instance.video_poster.storage.delete(old) if old else None

    video_poster.poster_in_background(instance)


def connect():
    for model in video_poster.video_models():
        post_init.connect(remember_video, sender=model, dispatch_uid="dm-video-remember")
        post_save.connect(refresh_poster, sender=model, dispatch_uid="dm-video-poster")

    # A recording is measured the moment it is saved, so the words are
    # ready before a learner opens the lesson.
    for model in read_along.read_along_models():
        post_save.connect(read_along.measure_when_saved, sender=model, dispatch_uid="dm-read-along-measure")
