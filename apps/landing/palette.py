"""
The site's palette is blue, yellow, white and navy, with their tints and
greys. Any other colour (green, teal, purple, red, pink, orange...) is
moved onto the nearest brand shade of the same contrast, so text stays
readable: greens, teals and purples become blue, reds, pinks and oranges
become gold.

Used by the `palette` template filter for colours that live in the
database (course, module and category colours chosen in the admin).
"""

import colorsys
import math
import re

BLUE_RAMP = ["#0B1A4A", "#0F31AE", "#1846E0", "#3D63E6", "#6E8DEE", "#A9BDF6", "#D6E3FF", "#E7EFFF", "#F2F5FC"]
YELLOW_RAMP = ["#7A5600", "#B07A00", "#E9AE00", "#FFC72C", "#FFD86B", "#FFE9A8", "#FFF5D6", "#FFFAEB"]

NAMED = {
    "green": "#008000", "red": "#FF0000", "purple": "#800080", "orange": "#FFA500",
    "pink": "#FFC0CB", "teal": "#008080", "lime": "#00FF00", "crimson": "#DC143C",
    "tomato": "#FF6347", "violet": "#EE82EE", "magenta": "#FF00FF", "fuchsia": "#FF00FF",
    "olive": "#808000", "maroon": "#800000", "salmon": "#FA8072", "coral": "#FF7F50",
    "brown": "#A52A2A", "darkgreen": "#006400", "darkred": "#8B0000", "seagreen": "#2E8B57",
    "forestgreen": "#228B22", "limegreen": "#32CD32", "orangered": "#FF4500",
    "hotpink": "#FF69B4", "indigo": "#4B0082", "firebrick": "#B22222", "cyan": "#00FFFF",
    "aqua": "#00FFFF", "turquoise": "#40E0D0",
}


def _lin(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _luminance(r, g, b):
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def _rgb(hexcode):
    return tuple(int(hexcode[i:i + 2], 16) for i in (1, 3, 5))


def _family(h, s, l):
    """None when the colour already belongs (blue, yellow, grey, white, black)."""
    if s < 0.15 or l < 0.05 or l > 0.97:
        return None
    deg = h * 360
    if 38 <= deg < 62 or 205 <= deg < 250:
        return None
    if 62 <= deg < 205 or 250 <= deg < 330:
        return BLUE_RAMP
    return YELLOW_RAMP


def remap_rgb(r, g, b):
    """0-255 ints in, 0-255 ints out: the brand shade nearest in contrast."""
    h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    ramp = _family(h, s, l)
    if ramp is None:
        return r, g, b
    want = math.log(_luminance(r / 255, g / 255, b / 255) + 0.05)
    best = min(ramp, key=lambda c: abs(math.log(_luminance(*(v / 255 for v in _rgb(c))) + 0.05) - want))
    return _rgb(best)


_HEX = re.compile(r"#([0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})\b")
_RGB = re.compile(r"rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*(,\s*[\d.]+%?\s*)?\)", re.I)
_NAMED = re.compile(r"(?<![\w-])(" + "|".join(sorted(NAMED, key=len, reverse=True)) + r")(?![\w-])", re.I)


def _hex_sub(m):
    raw = m.group(1)
    if len(raw) in (3, 4):
        full = "".join(c * 2 for c in raw[:3])
        alpha = raw[3] * 2 if len(raw) == 4 else ""
    else:
        full, alpha = raw[:6], raw[6:]
    rgb = tuple(int(full[i:i + 2], 16) for i in (0, 2, 4))
    new = remap_rgb(*rgb)
    if new == rgb:
        return m.group(0)
    out = "#%02X%02X%02X" % new
    return out + alpha.upper() if alpha else out


def _rgb_sub(m):
    rgb = tuple(int(m.group(i)) for i in (1, 2, 3))
    new = remap_rgb(*rgb)
    if new == rgb:
        return m.group(0)
    if m.group(4):
        return "rgba(%d, %d, %d%s)" % (*new, m.group(4).rstrip())
    return "rgb(%d, %d, %d)" % new


def remap_value(text):
    """Remap every colour in a CSS value (or any string of them)."""
    text = _NAMED.sub(lambda m: NAMED[m.group(1).lower()], text)
    text = _HEX.sub(_hex_sub, text)
    return _RGB.sub(_rgb_sub, text)
