"""A recital section's page: its recitals, straight after the title."""

from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import Recital, Section

User = get_user_model()


class SectionPageTests(TestCase):
    def test_a_section_shows_its_recitals_and_not_every_other_section(self):
        section = Section.objects.create(name="Memory Verses", slug="memory-verses")
        other = Section.objects.create(name="Food Items", slug="food-items")
        Recital.objects.create(section=section, title="Twenty verses", slug="twenty-verses")
        self.client.force_login(User.objects.create_user("ada@example.com", "mango-river-47", first_name="Ada"))
        page = self.client.get(f"/assembly-recitals/{section.slug}/")
        self.assertContains(page, "Twenty verses")
        self.assertContains(page, 'href="/assembly-recitals/"')                  # the way back to every section
        self.assertNotContains(page, other.name)
        self.assertContains(self.client.get("/assembly-recitals/"), other.name)  # the sections page keeps them
