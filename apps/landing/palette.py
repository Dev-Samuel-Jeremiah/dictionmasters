"""
The site's palette is blue, yellow and white. Every other colour is moved
onto the nearest shade of it with the same contrast, so text stays readable:

- white and blues stay as they are, and yellows snap to the brand yellows;
- greys, black, beige and cream become blue-greys (black becomes navy);
- other dark or strong colours (green, red, purple, brown...) become blue;
- pale warm colours (pink, peach...) become pale yellow.

Used by the `palette` template filter for colours that live in the
database (course, module and category colours chosen in the admin).
"""

import colorsys
import math
import re

BLUE_RAMP = ["#0B1A4A", "#0F31AE", "#1846E0", "#3D63E6", "#6E8DEE", "#A9BDF6", "#D6E3FF", "#E7EFFF", "#F2F5FC"]
BLUE_GREY_RAMP = ["#0B1A4A", "#2A3560", "#55607E", "#8A93AE", "#A9B1C8", "#C9D0E2", "#E3E8F4", "#F2F5FC"]
YELLOW_RAMP = ["#E9AE00", "#FFC72C", "#FFD86B", "#FFE9A8", "#FFF5D6", "#FFFAEB"]
KEEP = {c.upper() for c in BLUE_RAMP + BLUE_GREY_RAMP + YELLOW_RAMP + ["#FFFFFF", "#ECEEF3"]}

NAMED = {
    "green": "#008000", "red": "#FF0000", "purple": "#800080", "orange": "#FFA500",
    "pink": "#FFC0CB", "teal": "#008080", "lime": "#00FF00", "crimson": "#DC143C",
    "tomato": "#FF6347", "violet": "#EE82EE", "magenta": "#FF00FF", "fuchsia": "#FF00FF",
    "olive": "#808000", "maroon": "#800000", "salmon": "#FA8072", "coral": "#FF7F50",
    "brown": "#A52A2A", "darkgreen": "#006400", "darkred": "#8B0000", "seagreen": "#2E8B57",
    "forestgreen": "#228B22", "limegreen": "#32CD32", "orangered": "#FF4500",
    "hotpink": "#FF69B4", "indigo": "#4B0082", "firebrick": "#B22222", "cyan": "#00FFFF",
    "aqua": "#00FFFF", "turquoise": "#40E0D0", "black": "#000000", "gray": "#808080",
    "grey": "#808080", "silver": "#C0C0C0", "darkgray": "#A9A9A9", "darkgrey": "#A9A9A9",
    "lightgray": "#D3D3D3", "lightgrey": "#D3D3D3", "dimgray": "#696969", "dimgrey": "#696969",
    "gainsboro": "#DCDCDC", "beige": "#F5F5DC", "tan": "#D2B48C", "wheat": "#F5DEB3",
    "chocolate": "#D2691E", "sienna": "#A0522D", "peru": "#CD853F", "khaki": "#F0E68C",
}


def _lin(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _luminance(r, g, b):
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def _rgb(hexcode):
    return tuple(int(hexcode[i:i + 2], 16) for i in (1, 3, 5))


def _ramp(r, g, b):
    """None when the colour already belongs (white, blue, bright yellow)."""
    if "#%02X%02X%02X" % (r, g, b) in KEEP:
        return None
    h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    lum = _luminance(r / 255, g / 255, b / 255)
    deg = h * 360
    if l > 0.97:
        # near-white: pure or bluish stays; a cream or pink tint becomes white
        return None if s < 0.3 or 205 <= deg < 250 else ["#FFFFFF", "#F2F5FC"]
    if 205 <= deg < 250 and s >= 0.12 and l >= 0.05:
        return None
    if 38 <= deg < 62 and s >= 0.6 and lum >= 0.35:
        return YELLOW_RAMP
    if l < 0.05 or s < 0.15 or (l > 0.85 and s < 0.6):
        return BLUE_GREY_RAMP
    if (deg < 70 or deg >= 300) and lum >= 0.35:
        return YELLOW_RAMP
    return BLUE_RAMP


def remap_rgb(r, g, b):
    """0-255 ints in, 0-255 ints out: the palette shade nearest in contrast."""
    ramp = _ramp(r, g, b)
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
