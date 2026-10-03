"""
Control room > Learning Modules > a lesson item > Photo slides.

Many pictures are uploaded at once (dropped or chosen together), each made
web-sized as it arrives so the slideshow loads quickly on a phone. Then
each slide can be given a caption and, if wanted, a recording that plays as
it opens; slides are put in order by dragging, and removed with a tick.

    /manage/lesson-items/<pk>/slides/
"""

import io
import re

from django.contrib import messages
from django.core.files.base import ContentFile
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from PIL import Image, ImageOps, UnidentifiedImageError

from apps.learning_modules.models import LessonItem, LessonSlide

MAX_SIDE = 2000                    # pixels: sharp on a big screen, light on a phone
MAX_UPLOAD = 25 * 1024 * 1024
MAX_FILES = 80
PICTURES = {"jpg", "jpeg", "png", "webp", "gif"}
SOUNDS = {"mp3", "m4a", "wav", "ogg", "aac"}


def _ext(name):
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def caption_from(name):
    """ "03-red-apple.jpg" or "slide3_red apple.png" → "Red apple": the
    numbers that only set the order, and camera names, are left out."""
    words = re.sub(r"[_\-.]+", " ", name.rsplit(".", 1)[0]).strip()
    words = re.sub(r"^(img|image|dsc|photo|pxl|slide|picture|pic|page)?\s*\d+\s*", "", words, flags=re.I).strip()
    return (words[:1].upper() + words[1:])[:200] if words and not words.isdigit() else ""


def web_sized(upload):
    """(file name, bytes) of the picture, turned the right way up and no
    bigger than MAX_SIDE. A moving GIF is kept exactly as it is."""
    ext = _ext(upload.name)
    raw = upload.read()
    with Image.open(io.BytesIO(raw)) as picture:
        if ext == "gif" and getattr(picture, "is_animated", False):
            return upload.name, raw
        picture = ImageOps.exif_transpose(picture)
        picture.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
        stem = re.sub(r"[^\w\-]+", "-", upload.name.rsplit(".", 1)[0])[:60] or "slide"
        out = io.BytesIO()
        if picture.mode in ("RGBA", "LA", "P") and "transparency" in picture.info or picture.mode in ("RGBA", "LA"):
            picture.convert("RGBA").save(out, format="PNG", optimize=True)
            return f"{stem}.png", out.getvalue()
        picture.convert("RGB").save(out, format="JPEG", quality=86, optimize=True, progressive=True)
        return f"{stem}.jpg", out.getvalue()


def _upload(request, item):
    files = request.FILES.getlist("images")
    if not files:
        messages.error(request, "Choose the pictures to upload.")
        return
    if len(files) > MAX_FILES:
        messages.error(request, f"Upload up to {MAX_FILES} pictures at a time.")
        return
    use_names = bool(request.POST.get("captions_from_names"))
    order = (item.slides.order_by("-order").values_list("order", flat=True).first() or -1) + 1
    added, skipped = 0, []
    for upload in sorted(files, key=lambda f: _natural(f.name)) if request.POST.get("sort_by_name") else files:
        if _ext(upload.name) not in PICTURES or upload.size > MAX_UPLOAD:
            skipped.append(upload.name)
            continue
        try:
            name, data = web_sized(upload)
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
            skipped.append(upload.name)
            continue
        slide = LessonSlide(lesson_item=item, order=order, caption=caption_from(upload.name) if use_names else "")
        slide.image.save(name, ContentFile(data), save=True)
        order += 1
        added += 1
    if added:
        messages.success(request, f"{added} picture{'' if added == 1 else 's'} added to the slideshow.")
    if skipped:
        messages.error(request, "These couldn't be used (JPG, PNG, WebP or GIF up to 25 MB): " + ", ".join(skipped[:8])
                       + (f" and {len(skipped) - 8} more" if len(skipped) > 8 else "") + ".")


def _natural(name):
    """ "slide2" before "slide10" """
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", name)]


@transaction.atomic
def _save(request, item):
    slides = {str(s.pk): s for s in item.slides.all()}
    removing = set(request.POST.getlist("delete"))
    order = [pk for pk in request.POST.get("order", "").split(",") if pk in slides and pk not in removing]
    order += [pk for pk in slides if pk not in order and pk not in removing]
    for n, pk in enumerate(order):
        slide = slides[pk]
        slide.order = n
        slide.caption = request.POST.get(f"caption_{pk}", slide.caption).strip()[:200]
        sound = request.FILES.get(f"audio_{pk}")
        old_sound = slide.audio_file.name if slide.audio_file else ""
        if request.POST.get(f"no_audio_{pk}") and slide.audio_file:
            slide.audio_file = ""
        if sound and _ext(sound.name) in SOUNDS and sound.size <= MAX_UPLOAD:
            slide.audio_file.save(sound.name, sound, save=False)
        slide.save()
        if old_sound and old_sound != (slide.audio_file.name if slide.audio_file else ""):
            slide.audio_file.storage.delete(old_sound)
    for pk in removing:
        if pk in slides:
            slides[pk].delete()
    gone = len(removing & set(slides))
    messages.success(request, "Slideshow saved." + (f" {gone} picture{'' if gone == 1 else 's'} removed." if gone else ""))


def manage(request, pk):
    from .views import _base_context

    item = get_object_or_404(LessonItem.objects.select_related("day__week__term__module"), pk=pk)
    if request.method == "POST":
        if request.POST.get("do") == "upload":
            _upload(request, item)
        else:
            _save(request, item)
        return redirect(reverse("manage:lesson_slides", args=[item.pk]))
    return render(request, "manage/lesson_slides.html", _base_context(
        request, "lesson-items",
        item=item,
        slides=list(item.slides.all()),
        back=reverse("manage:edit", args=["lesson-items", item.pk]),
        preview=_lesson_page(item),
    ))


def _lesson_page(item):
    """Where learners see this lesson item."""
    day = item.day
    week = day.week
    return reverse("learning_modules:day_detail", kwargs={
        "module_slug": week.term.module.slug, "term_slug": week.term.slug,
        "week_slug": week.slug, "day_name": day.day_name,
    }) + f"#item-{item.pk}"
