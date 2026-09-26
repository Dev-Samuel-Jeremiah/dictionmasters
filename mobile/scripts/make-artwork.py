"""
Makes every app icon and splash screen from ONE logo picture.

    cd mobile
    python3 scripts/make-artwork.py
    npm run assets            (only if you build on your own computer)

To change the logo: replace  mobile/resources/logo-source.jpg  (or .png)
with your new picture — the logo on a plain, single-colour background,
like the one there now — and run the command above. The background colour
is read from the picture's corner, so any colour works.

Files made:
  mobile/resources/icon-only.png        1024x1024  full icon (iPhone + older Android)
  mobile/resources/icon-foreground.png  1024x1024  Android adaptive icon: the logo only
  mobile/resources/icon-background.png  1024x1024  Android adaptive icon: the colour
  mobile/resources/splash.png           2732x2732  splash screen
  mobile/resources/splash-dark.png      2732x2732  splash screen (dark mode)
  static/pwa/*.png                      the website's own "installed app" icons
                                        (Add to Home Screen, browser tab)

After running it: commit and push. GitHub builds the app with the new
artwork, and the website uses the new icons as soon as it's deployed.
(A logo uploaded in the control room's Branding page still takes priority
for the website's icons.)

Needs Pillow:  pip install Pillow
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

MOBILE = Path(__file__).resolve().parent.parent
RESOURCES = MOBILE / "resources"
WEB_ICONS = MOBILE.parent / "static" / "pwa"

APP_NAME = "Diction Masters"


def load_source():
    for name in ("logo-source.png", "logo-source.jpg", "logo-source.jpeg"):
        path = RESOURCES / name
        if path.exists():
            return Image.open(path).convert("RGB")
    raise SystemExit("Put your logo in mobile/resources/logo-source.png (or .jpg) first.")


def cut_out_logo(source):
    """The logo on a transparent background, trimmed to its edges.

    Every pixel's distance from the background colour becomes how solid it
    is, so the logo's smooth edges stay smooth."""
    background = source.getpixel((2, 2))
    width, height = source.size
    out = Image.new("RGBA", source.size)
    src, dst = source.load(), out.load()
    full = 140.0  # this far from the background colour = fully solid
    for y in range(height):
        for x in range(width):
            r, g, b = src[x, y]
            dr, dg, db = r - background[0], g - background[1], b - background[2]
            alpha = min(1.0, (dr * dr + dg * dg + db * db) ** 0.5 / full)
            if alpha < 0.04:
                dst[x, y] = (0, 0, 0, 0)
                continue
            # Take the background back out of the edge pixels' colour.
            colour = tuple(
                max(0, min(255, round(background[i] + (c - background[i]) / alpha)))
                for i, c in enumerate((r, g, b))
            )
            dst[x, y] = colour + (round(alpha * 255),)
    return out.crop(out.getbbox()), background


def logo_at(logo, height):
    width = round(logo.width * height / logo.height)
    return logo.resize((width, height), Image.LANCZOS)


def square(size, colour, logo, logo_height, dy=0):
    canvas = Image.new("RGBA", (size, size), colour + (255,) if colour else (0, 0, 0, 0))
    mark = logo_at(logo, logo_height)
    canvas.alpha_composite(mark, ((size - mark.width) // 2, (size - mark.height) // 2 + dy))
    return canvas


def rounded(image, radius_ratio=0.22):
    mask = Image.new("L", image.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, image.width - 1, image.height - 1],
                                           radius=round(image.width * radius_ratio), fill=255)
    out = image.copy()
    out.putalpha(mask)
    return out


def font(px):
    for name in ("DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf", "Arial Bold.ttf", "arialbd.ttf"):
        try:
            return ImageFont.truetype(name, px)
        except OSError:
            continue
    return ImageFont.load_default()


def splash(logo, colour):
    size = 2732
    canvas = square(size, colour, logo, 760, dy=-110)
    draw = ImageDraw.Draw(canvas)
    f = font(120)
    width = draw.textlength(APP_NAME, font=f)
    draw.text(((size - width) / 2, size / 2 + 360), APP_NAME, font=f, fill=(255, 255, 255))
    return canvas.convert("RGB")


if __name__ == "__main__":
    logo, colour = cut_out_logo(load_source())

    # The app (Capacitor makes every Android and iPhone size from these).
    square(1024, colour, logo, 600).convert("RGB").save(RESOURCES / "icon-only.png")
    # Android crops its icons to a circle or squircle: keep the logo inside the safe zone.
    square(1024, None, logo, 470).save(RESOURCES / "icon-foreground.png")
    Image.new("RGB", (1024, 1024), colour).save(RESOURCES / "icon-background.png")
    splash(logo, colour).save(RESOURCES / "splash.png")
    splash(logo, colour).save(RESOURCES / "splash-dark.png")

    # The website's "installed app" icons.
    if WEB_ICONS.exists():
        big = square(1024, colour, logo, 600)
        rounded(big).resize((512, 512), Image.LANCZOS).save(WEB_ICONS / "icon-512.png")
        rounded(big).resize((192, 192), Image.LANCZOS).save(WEB_ICONS / "icon-192.png")
        # "maskable": the phone cuts its own shape, so fill edge to edge, logo smaller.
        mask = square(1024, colour, logo, 500)
        mask.convert("RGB").resize((512, 512), Image.LANCZOS).save(WEB_ICONS / "maskable-512.png")
        mask.convert("RGB").resize((192, 192), Image.LANCZOS).save(WEB_ICONS / "maskable-192.png")
        big.convert("RGB").resize((180, 180), Image.LANCZOS).save(WEB_ICONS / "apple-touch-icon.png")
        square(1024, colour, logo, 800).convert("RGB").resize((32, 32), Image.LANCZOS).save(WEB_ICONS / "favicon-32.png")

    # The app's built-in offline screen shows the logo too.
    www = MOBILE / "www"
    if www.exists():
        logo_at(logo, 240).save(www / "logo.png")

    print(f"Done. Background colour #{colour[0]:02X}{colour[1]:02X}{colour[2]:02X}.")
    print("Now commit and push; GitHub builds the app with the new icon.")
