"""Photo slides on a lesson item: uploaded many at a time in the control
room, shown to children as a slideshow."""

import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image

from apps.accounts.models import User

from .models import Day, LearningModule, LessonItem, LessonSlide, Term, Week

STORAGE = {"default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
           "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}}


def picture(name, size=(800, 600), mode="RGB", fmt="JPEG"):
    out = io.BytesIO()
    Image.new(mode, size, "red").save(out, format=fmt)
    return SimpleUploadedFile(name, out.getvalue(), content_type=f"image/{fmt.lower()}")


@override_settings(STORAGES=STORAGE)
class PhotoSlideTests(TestCase):
    def setUp(self):
        module = LearningModule.objects.create(name="Phonics", is_published=True)
        week = Week.objects.create(term=Term.objects.create(module=module, name="First Term"), number=1)
        self.day = Day.objects.create(week=week, day_name="monday", is_published=True)
        self.item = LessonItem.objects.create(day=self.day, title="Fruits")
        self.staff = User.objects.create_user("staff@example.com", "pw-12345678", first_name="Sam", is_staff=True)
        self.client.force_login(self.staff)
        self.url = f"/manage/lesson-items/{self.item.pk}/slides/"

    def upload(self, *files, **options):
        data = {"do": "upload", "images": list(files), "captions_from_names": "1", "sort_by_name": "1"}
        data.update(options)
        return self.client.post(self.url, data, follow=True)

    def test_many_pictures_upload_in_name_order_with_captions(self):
        self.upload(picture("slide10-banana.jpg"), picture("slide2-orange.jpg"), picture("slide1-red_apple.jpg"))
        self.assertEqual([s.caption for s in self.item.slides.all()],
                         ["Red apple", "Orange", "Banana"])
        self.assertEqual(self.item.kind, "slides")

    def test_big_photos_are_made_web_sized_and_transparent_ones_stay_png(self):
        self.upload(picture("huge.jpg", size=(5000, 3000)), picture("logo.png", mode="RGBA", fmt="PNG"))
        big, logo = self.item.slides.all()
        with Image.open(big.image) as image:
            self.assertEqual(max(image.size), 2000)
        self.assertTrue(logo.image.name.endswith(".png"))

    def test_files_that_are_not_pictures_are_skipped(self):
        response = self.upload(SimpleUploadedFile("notes.pdf", b"%PDF"), picture("cat.jpg"))
        self.assertContains(response, "notes.pdf")
        self.assertEqual(self.item.slides.count(), 1)

    def test_reorder_caption_and_remove(self):
        self.upload(picture("a.jpg"), picture("b.jpg"), picture("c.jpg"))
        a, b, c = self.item.slides.all()
        self.client.post(self.url, {"do": "save", "order": f"{c.pk},{a.pk},{b.pk}", "delete": [b.pk],
                                    f"caption_{c.pk}": "A cat", f"caption_{a.pk}": ""})
        self.assertEqual([(s.pk, s.caption) for s in self.item.slides.all()], [(c.pk, "A cat"), (a.pk, "")])
        self.assertFalse(LessonSlide.objects.filter(pk=b.pk).exists())

    def test_only_staff_manage_slides(self):
        learner = User.objects.create_user("l@example.com", "pw-12345678", first_name="Lee", role="individual")
        self.client.force_login(learner)
        self.upload(picture("a.jpg"))
        self.assertFalse(LessonSlide.objects.exists())

    def test_the_lesson_item_page_links_to_the_slides(self):
        response = self.client.get(f"/manage/lesson-items/{self.item.pk}/")
        self.assertContains(response, "Upload &amp; arrange photos")
        self.assertContains(response, self.url)

    def test_children_see_the_slideshow(self):
        self.upload(picture("red-apple.jpg"), picture("banana.jpg"))
        learner = User.objects.create_user("l@example.com", "pw-12345678", first_name="Lee", role="individual", is_staff=True)
        self.client.force_login(learner)
        page = self.client.get(f"/learning-modules/phonics/first-term/week-1/monday/")
        self.assertContains(page, "data-ps")
        self.assertContains(page, "Red apple")
        self.assertContains(page, "2 pictures")
