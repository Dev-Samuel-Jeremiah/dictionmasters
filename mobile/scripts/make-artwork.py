"""
Draws the app icon and splash screen artwork into mobile/resources/.

    python3 scripts/make-artwork.py

You only need this if you want to redraw the default Diction Masters mark.
To use your OWN logo instead, just replace the PNG files in resources/
(same names, same sizes) and run:  npm run assets

Files made:
  resources/icon-only.png        1024x1024  full icon (iPhone + old Android)
  resources/icon-foreground.png  1024x1024  Android adaptive icon, the mark only
  resources/icon-background.png  1024x1024  Android adaptive icon, the background
  resources/splash.png           2732x2732  splash screen (light mode)
  resources/splash-dark.png      2732x2732  splash screen (dark mode)
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent.parent / "resources"
OUT.mkdir(exist_ok=True)

NAVY_TOP = (36, 55, 95)
NAVY_BOTTOM = (20, 33, 61)
GOLD = (243, 211, 141)
S = 8  # draw 8x bigger than the 512 design, then shrink: smooth edges


def gradient(size):
    """Navy background, lighter top-left to darker bottom-right."""
    small = Image.new("RGB", (256, 256))
    px = small.load()
    for y in range(256):
        for x in range(256):
            t = (x + y) / 510
            px[x, y] = tuple(round(a + (b - a) * t) for a, b in zip(NAVY_TOP, NAVY_BOTTOM))
    return small.resize((size, size), Image.BICUBIC)


def mark(size, scale=1.0):
    """The gold circle-and-F mark on a transparent square of `size` px.
    `scale` shrinks the mark inside the square (1.0 = same as the web icon)."""
    big = 512 * S
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def p(v):  # a 512-design coordinate, scaled around the centre
        return (256 + (v - 256) * scale) * S

    w = 15 * scale * S  # stroke width
    r = w / 2

    # Ring
    R = 118.5 * scale * S
    c = 256 * S
    d.ellipse([c - R - r, c - R - r, c + R + r, c + R + r], outline=GOLD, width=round(w))

    def line(x1, y1, x2, y2):
        d.line([p(x1), p(y1), p(x2), p(y2)], fill=GOLD, width=round(w))
        for x, y in ((x1, y1), (x2, y2)):  # round caps
            d.ellipse([p(x) - r, p(y) - r, p(x) + r, p(y) + r], fill=GOLD)

    # The F: upright, top bar ending in a dot, middle bar
    line(202.5, 196.5, 202.5, 296)   # upright (round cap = rounded corner)
    line(202.5, 196.5, 300, 196.5)   # top bar
    line(202.5, 252, 268.5, 252)     # middle bar
    dot = 13.5 * scale * S
    d.ellipse([p(310) - dot, p(195.5) - dot, p(310) + dot, p(195.5) + dot], fill=GOLD)

    return img.resize((size, size), Image.LANCZOS)


def font(px):
    for name in ("DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf", "Arial Bold.ttf"):
        try:
            return ImageFont.truetype(name, px)
        except OSError:
            continue
    return ImageFont.load_default()


def splash(dark):
    size = 2732
    bg = Image.new("RGB", (size, size), (12, 20, 40) if dark else NAVY_BOTTOM)
    if not dark:
        bg = gradient(size)
    logo = mark(900)
    bg.paste(logo, ((size - 900) // 2, (size - 900) // 2 - 120), logo)
    d = ImageDraw.Draw(bg)
    f = font(120)
    text = "Diction Masters"
    tw = d.textlength(text, font=f)
    d.text(((size - tw) / 2, size / 2 + 360), text, font=f, fill=GOLD)
    return bg


if __name__ == "__main__":
    full = gradient(1024).convert("RGBA")
    full.alpha_composite(mark(1024))
    full.convert("RGB").save(OUT / "icon-only.png")
    # Android crops adaptive icons to a circle/squircle: keep the mark a
    # little smaller so it sits inside the safe zone.
    mark(1024, scale=0.9).save(OUT / "icon-foreground.png")
    gradient(1024).save(OUT / "icon-background.png")
    splash(False).save(OUT / "splash.png")
    splash(True).save(OUT / "splash-dark.png")
    print("Artwork written to", OUT)
