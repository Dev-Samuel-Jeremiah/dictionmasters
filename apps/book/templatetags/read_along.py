from django import template
from django.utils.html import format_html

from apps.book import read_along

register = template.Library()


@register.simple_tag
def read_along_sync(obj):
    """` data-ra-sync="…"`: where the read-along script fetches the measured
    word timings for this passage, dialogue, lesson or chapter."""
    url = read_along.sync_url(obj)
    return format_html(' data-ra-sync="{}"', url) if url else ""
