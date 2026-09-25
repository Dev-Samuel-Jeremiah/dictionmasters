from django import template

from apps.landing.palette import remap_value

register = template.Library()


@register.filter
def palette(value):
    """A colour from the database, moved onto the site's blue and yellow."""
    return remap_value(str(value)) if value else value
