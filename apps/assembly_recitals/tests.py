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

    def test_a_card_opens_its_recital_in_a_popup(self):
        section = Section.objects.create(name="Memory Verses", slug="memory-verses")
        recital = Recital.objects.create(section=section, title="Twenty verses", slug="twenty-verses",
                                         audio_url="https://example.com/verses.mp3", lines="One\nTwo\n\nThree")
        quiet = Recital.objects.create(section=section, title="Not ready", slug="not-ready")
        self.client.force_login(User.objects.create_user("ada@example.com", "mango-river-47", first_name="Ada"))
        page = self.client.get(f"/assembly-recitals/{section.slug}/")
        full_page = f"/assembly-recitals/{section.slug}/{recital.slug}/"
        self.assertContains(page, f'href="{full_page}" class="ui-card ui-lift"')   # still a link, for a new tab
        self.assertContains(page, f'data-recital-open="recital-{recital.pk}"')
        self.assertContains(page, f'<template id="recital-{recital.pk}">')
        self.assertContains(page, 'src="https://example.com/verses.mp3"', count=1)
        self.assertContains(page, '<span class="rc-line">Three</span>')
        self.assertContains(page, "data-recital-modal")
        self.assertContains(page, "js/recital_modal.js")
        self.assertContains(page, "Open full page", count=2)
        self.assertContains(page, "being put together", count=1)                   # the one with nothing yet
        self.assertEqual(self.client.get(f"/assembly-recitals/{section.slug}/{quiet.slug}/").status_code, 200)

