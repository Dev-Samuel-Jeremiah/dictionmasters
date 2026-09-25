"""Small, dependency-free rich text support shared by control-room forms.

Rich text is stored as a restricted HTML fragment in the existing text
fields. Keeping the allow-list here means learner pages and admin forms
use the same rules without a database migration or external editor CDN.
"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser

from django import forms


RICH_TEXT_FIELDS = frozenset({
    "body", "overview", "description", "summary", "definition", "example_sentence",
    "instructions", "prompt", "explanation", "feedback", "teacher_feedback",
    "trap_text", "mouth_position_text", "spelling_pattern", "sentence", "text", "notes", "transcript",
    "headline", "message", "hint", "details", "comment",
})

ALLOWED_TAGS = frozenset({
    "a", "b", "blockquote", "br", "code", "del", "div", "em", "h2", "h3", "h4",
    "hr", "i", "li", "mark", "ol", "p", "pre", "s", "span", "strong", "sub", "sup", "strike",
    "table", "tbody", "td", "th", "thead", "tr", "u", "ul", "font",
})
VOID_TAGS = frozenset({"br", "hr"})
DROP_CONTENT_TAGS = frozenset({"script", "style", "iframe", "object", "embed", "svg", "math", "template"})

_COLOR_RE = re.compile(r"^(?:#[0-9a-f]{3,8}|[a-z]{3,20}|(?:rgb|hsl)a?\([0-9.% ,+-]+\))$", re.I)
_SIZE_RE = re.compile(r"^(?:[0-9]{1,2}(?:\.[0-9]+)?(?:px|pt|em|rem|%)|small|medium|large|x-large|xx-large)$", re.I)
_MARGIN_RE = re.compile(r"^(?:[0-9]{1,3}px|[0-9](?:\.[0-9]+)?em)$", re.I)
_SAFE_HREF_SCHEMES = ("http://", "https://", "mailto:", "tel:")


PLAIN_TEXT_MODEL_FIELDS = {
    # These fields are parsed as line-based records or tokenized for live
    # speech highlighting; embedding markup would change their data format.
    ("echospell", "cardlesson", "definition"),
    ("tutor", "tutorpassage", "body"),
}


def is_rich_text_field(field_name: str, model=None) -> bool:
    """Whether a textarea is learner-facing prose rather than structured data."""
    # Formsets add a prefix such as ``questions-0-`` or
    # ``dialogueline_set-2-`` to the model field name.
    field_name = str(field_name).rsplit("-", 1)[-1]
    if model is not None and (model._meta.app_label, model._meta.model_name, field_name) in PLAIN_TEXT_MODEL_FIELDS:
        return False
    return field_name in RICH_TEXT_FIELDS


def _safe_style(style: str) -> str:
    safe = []
    for declaration in style.split(";"):
        if ":" not in declaration:
            continue
        prop, value = (part.strip().lower() for part in declaration.split(":", 1))
        value = re.sub(r"\s+", " ", value)
        if prop in {"color", "background-color"} and _COLOR_RE.fullmatch(value):
            safe.append(f"{prop}: {value}")
        elif prop == "font-size" and _SIZE_RE.fullmatch(value):
            safe.append(f"{prop}: {value}")
        elif prop == "font-family" and value.replace("'", "").replace('"', "") in {
            "georgia, serif", "arial, sans-serif", "times new roman, serif",
            "courier new, monospace", "verdana, sans-serif",
        }:
            safe.append(f"{prop}: {value}")
        elif prop == "font-weight" and value in {"normal", "bold", "400", "500", "600", "700", "800", "900"}:
            safe.append(f"{prop}: {value}")
        elif prop == "font-style" and value in {"normal", "italic"}:
            safe.append(f"{prop}: {value}")
        elif prop in {"text-decoration", "text-decoration-line"} and value in {
            "underline", "line-through", "overline", "none", "underline line-through", "line-through underline"
        }:
            safe.append(f"text-decoration: {value}")
        elif prop == "text-align" and value in {"left", "center", "right", "justify"}:
            safe.append(f"{prop}: {value}")
        elif prop in {"margin-left", "margin-right"} and _MARGIN_RE.fullmatch(value):
            safe.append(f"{prop}: {value}")
    return "; ".join(safe)


def _safe_href(value: str) -> str | None:
    value = value.strip()
    lowered = value.lower()
    if lowered.startswith(_SAFE_HREF_SCHEMES) or value.startswith(("/", "#", "?")):
        return value
    # A domain without a scheme is still a useful link; make it HTTPS.
    if re.match(r"^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?(?::[0-9]+)?(?:/[^\s]*)?$", value, re.I):
        return "https://" + value
    return None


class _RichTextSanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.stack: list[str] = []
        self.drop_depth = 0
        self.saw_markup = False

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        self.saw_markup = True
        if tag in DROP_CONTENT_TAGS:
            self.drop_depth += 1
            return
        if self.drop_depth or tag not in ALLOWED_TAGS:
            return

        attributes = dict(attrs)
        # Normalize deprecated browser output into semantic markup.
        if tag == "strike":
            tag = "s"
        if tag == "font":
            style = _safe_style(attributes.get("style", ""))
            color = attributes.get("color", "")
            if _COLOR_RE.fullmatch(color):
                style = "; ".join(filter(None, [style, f"color: {color}"]))
            face = attributes.get("face", "").replace("'", "").replace('"', "").lower()
            if face in {"georgia", "arial", "times new roman", "courier new", "verdana"}:
                family = {"georgia": "Georgia, serif", "arial": "Arial, sans-serif", "times new roman": "Times New Roman, serif", "courier new": "Courier New, monospace", "verdana": "Verdana, sans-serif"}[face]
                style = "; ".join(filter(None, [style, f"font-family: {family}"]))
            if style:
                self.parts.append(f'<span style="{html.escape(style, quote=True)}">')
                self.stack.append("span")
            return

        rendered = []
        if tag == "a":
            href = _safe_href(attributes.get("href", ""))
            if href:
                rendered.append(f'href="{html.escape(href, quote=True)}"')
            title = attributes.get("title")
            if title:
                rendered.append(f'title="{html.escape(title[:200], quote=True)}"')
            if attributes.get("target") == "_blank":
                rendered.extend(['target="_blank"', 'rel="noopener noreferrer"'])
        else:
            title = attributes.get("title")
            if title and tag in {"span", "div", "p", "td", "th"}:
                rendered.append(f'title="{html.escape(title[:200], quote=True)}"')
            style = _safe_style(attributes.get("style", "")) if tag in {"span", "div", "p", "td", "th", "mark"} else ""
            if style:
                rendered.append(f'style="{html.escape(style, quote=True)}"')

        attr_text = (" " + " ".join(rendered)) if rendered else ""
        self.parts.append(f"<{tag}{attr_text}>")
        if tag not in VOID_TAGS:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag.lower() not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "font":
            tag = "span"
        elif tag == "strike":
            tag = "s"
        if tag in DROP_CONTENT_TAGS and self.drop_depth:
            self.drop_depth -= 1
            return
        if self.drop_depth or tag not in ALLOWED_TAGS or tag in VOID_TAGS or tag not in self.stack:
            return
        # Close intervening tags as well, so malformed pasted markup cannot
        # escape the editor's intended fragment.
        while self.stack:
            current = self.stack.pop()
            self.parts.append(f"</{current}>")
            if current == tag:
                break

    def handle_data(self, data):
        if not self.drop_depth:
            self.parts.append(html.escape(data, quote=False))

    def handle_entityref(self, name):
        if not self.drop_depth:
            self.parts.append(f"&amp;{html.escape(name)};")

    def handle_charref(self, name):
        if not self.drop_depth:
            self.parts.append(f"&amp;#{html.escape(name)};")

    def finish(self):
        while self.stack:
            self.parts.append(f"</{self.stack.pop()}>")
        return "".join(self.parts)




def _contains_markup(value) -> bool:
    if value is None:
        return False
    parser = _RichTextSanitizer()
    try:
        parser.feed(str(value))
        parser.close()
        return parser.saw_markup
    except Exception:
        return False


def sanitize_rich_text(value) -> str:
    """Return a small, safe HTML fragment; plain-text newlines become breaks."""
    if value is None:
        return ""
    raw = str(value)
    sanitizer = _RichTextSanitizer()
    try:
        sanitizer.feed(raw)
        sanitizer.close()
        cleaned = sanitizer.finish()
    except Exception:
        # Malformed markup must degrade to escaped text, never to raw HTML.
        return html.escape(raw, quote=False).replace("\r\n", "<br>").replace("\n", "<br>")
    if not sanitizer.saw_markup:
        return html.escape(raw, quote=False).replace("\r\n", "<br>").replace("\n", "<br>")
    return cleaned


class RichTextWidget(forms.Textarea):
    """A textarea that safely upgrades to the local editor in the browser."""

    def __init__(self, attrs=None):
        attrs = dict(attrs or {})
        classes = attrs.get("class", "").split()
        if "dm-rich-text-source" not in classes:
            classes.append("dm-rich-text-source")
        attrs["class"] = " ".join(classes)
        super().__init__(attrs)

    def get_context(self, name, value, attrs):
        rich = is_rich_text_field(name)
        has_markup = _contains_markup(value) if rich else False
        if rich and has_markup:
            value = sanitize_rich_text(value)
        context = super().get_context(name, value, attrs)
        context["widget"]["attrs"]["data-rich-text"] = "true" if rich else "false"
        context["widget"]["attrs"]["data-rich-text-initial-html"] = "true" if has_markup else "false"
        return context

    def value_from_datadict(self, data, files, name):
        value = super().value_from_datadict(data, files, name)
        return sanitize_rich_text(value) if is_rich_text_field(name) else value
