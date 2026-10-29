"""
A faint watermark with the signed-in person's name across every page
(templates/base.html), so a screenshot or screen recording of a lesson
shows who made it.

A website can't stop the computer's own screenshot and recording tools; the
apps block them where the system allows (desktop/ and mobile/:
blockScreenCapture). This is the deterrent for everywhere else: browsers,
iPhones, Linux. It's an SVG tile repeated over the page, under nothing that
can be clicked (pointer-events: none), and light enough to read through.

    {% load watermark %}{% watermark user %}
"""

from urllib.parse import quote

from django import template
from django.utils import timezone
from django.utils.html import escape, format_html

register = template.Library()

TILE_WIDTH, TILE_HEIGHT = 380, 220


@register.simple_tag
def watermark(user):
    if not getattr(user, "is_authenticated", False):
        return ""
    who = " · ".join(part for part in (user.get_full_name(), user.login_name) if part)
    when = timezone.localdate().strftime("%-d %b %Y")
    text = escape(f"{who} · {when}")
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{TILE_WIDTH}" height="{TILE_HEIGHT}">'
        f'<text x="50%" y="50%" text-anchor="middle" dominant-baseline="middle" '
        f'transform="rotate(-24 {TILE_WIDTH // 2} {TILE_HEIGHT // 2})" '
        f'font-family="system-ui, -apple-system, Segoe UI, Roboto, sans-serif" font-size="14" font-weight="600" '
        f'fill="rgb(120,124,140)" fill-opacity="0.16">{text}</text></svg>'
    )
    return format_html(
        '<div class="dm-watermark" aria-hidden="true" style="background-image: url(&quot;data:image/svg+xml,{}&quot;)"></div>',
        quote(svg, safe=""),
    )
