from django import template
from django.utils.safestring import mark_safe

from apps.echospell import qr

register = template.Library()


@register.simple_tag
def qr_svg(url, size=140):
    """The QR code for `url`, drawn into the page as SVG."""
    return mark_safe(qr.svg(str(url), int(size)))
