import re

from django import template
from django.utils.html import conditional_escape
from django.utils.safestring import mark_safe

from apps.manage.rich_text import _contains_markup, plain_text, sanitize_rich_text

register = template.Library()


@register.filter(name="rich_text")
def rich_text(value):
    """Render sanitized rich text, preserving plain legacy content safely."""
    return mark_safe(sanitize_rich_text(value))


@register.filter(name="rich_text_source")
def rich_text_source(value):
    """Safe, sanitized markup escaped for pre-filling an editor textarea."""
    raw = "" if value is None else str(value)
    if _contains_markup(raw):
        raw = sanitize_rich_text(raw)
    return mark_safe(conditional_escape(raw))


@register.filter(name="rich_text_has_markup")
def rich_text_has_markup(value):
    """Tell the editor whether a textarea value contains sanitized HTML."""
    return _contains_markup(value)


_BLOCK_TAGS = re.compile(r"</?(?:p|div|h[2-4]|blockquote|pre|li|ul|ol|table|thead|tbody|tr|td|th)\b[^>]*>", re.I)


@register.filter(name="rich_text_inline")
def rich_text_inline(value):
    """Sanitized rich text for phrasing-only contexts such as buttons."""
    fragment = sanitize_rich_text(value)
    fragment = _BLOCK_TAGS.sub("<br>", fragment)
    fragment = re.sub(r"(?:<br>\s*){2,}", "<br>", fragment, flags=re.I)
    fragment = re.sub(r"^(?:<br>\s*)+|(?:<br>\s*)+$", "", fragment, flags=re.I)
    return mark_safe(fragment)


@register.filter(name="rich_text_plain")
def rich_text_plain(value):
    """The words only, for snippets, attributes and truncated previews."""
    return plain_text(value)
